import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from urllib.parse import parse_qs, urlsplit

import pandas as pd
from playwright.sync_api import sync_playwright


def _launch_playdoit_context(playwright, headless=False):
    profile_path = Path(__file__).with_name("playwright_profile")
    return playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile_path),
        headless=headless,
        locale="es-MX",
        timezone_id="America/Mexico_City",
        viewport={"width": 1440, "height": 1000},
    )


class PlaydoitSession:
    """Reuse one Chromium context across multiple Playdoit events."""

    def __init__(self, headless=False):
        self.headless = headless
        self._playwright = None
        self.context = None

    def __enter__(self):
        self._playwright = sync_playwright().start()
        try:
            self.context = _launch_playdoit_context(
                self._playwright,
                headless=self.headless,
            )
        except Exception:
            self._playwright.stop()
            self._playwright = None
            raise
        return self

    def scrape(self, link):
        if self.context is None:
            raise RuntimeError("PlaydoitSession must be opened before scraping")
        return playdoit_scrapper(link, context=self.context)

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if self.context is not None:
                self.context.close()
        finally:
            self.context = None
            if self._playwright is not None:
                self._playwright.stop()
                self._playwright = None


def playdoit_scrapper(link, context=None):
    """Render a Playdoit event and return its core odds as a pandas Series.

    When ``context`` is supplied, it is reused and only the event page is
    closed. Standalone calls retain the original open-scrape-close behavior.
    """

    if not isinstance(link, str):
        raise TypeError("link must be a string")
    parsed_link = urlsplit(link.strip())
    if parsed_link.netloc.casefold() not in {"playdoit.mx", "www.playdoit.mx"}:
        raise ValueError("link must point to www.playdoit.mx")
    parameters = parse_qs(parsed_link.fragment)
    if parameters.get("page", [""])[0].casefold() != "event":
        raise ValueError("link must be a Playdoit event link")
    event_id_text = parameters.get("eventId", parameters.get("eventid", [""]))[0]
    sport_id_text = parameters.get("sportId", parameters.get("sportid", [""]))[0]
    if not event_id_text.isdigit() or not sport_id_text.isdigit():
        raise ValueError("link must contain numeric eventId and sportId values")
    event_id = int(event_id_text)

    def text_key(value):
        value = unicodedata.normalize("NFKD", str(value))
        value = "".join(
            character for character in value if not unicodedata.combining(character)
        )
        value = value.replace("ª", "a").replace("º", "o").casefold()
        return " ".join(value.split())

    payloads = []
    requested_event_payloads = []

    def capture_response(response):
        try:
            if response.request.resource_type not in {"xhr", "fetch"}:
                return
            body = response.text()
            if not body or len(body) > 25_000_000:
                return
            stripped_body = body.lstrip()
            if not stripped_body.startswith(("{", "[", '"')):
                return
            payload = json.loads(body)
            for _ in range(2):
                if not isinstance(payload, str):
                    break
                stripped_payload = payload.lstrip()
                if not stripped_payload.startswith(("{", "[")):
                    break
                payload = json.loads(payload)
            payloads.append(payload)

            request_url = str(response.url)
            request_post_data = response.request.post_data or ""
            request_details = f"{request_url}\n{request_post_data}".casefold()
            is_event_details_response = "geteventdetails" in request_url.casefold()
            request_event_match = re.search(
                rf"eventid\D{{0,30}}{event_id}(?!\d)",
                request_details,
            )
            if is_event_details_response and (
                request_event_match or not request_post_data
            ):
                requested_event_payloads.append(
                    {
                        "payload": payload,
                        "url": request_url,
                        "post_data": request_post_data,
                    }
                )
        except Exception:
            pass

    def records_named(value, record_name):
        records = []

        def visit(current):
            if isinstance(current, dict):
                found = current.get(record_name)
                if isinstance(found, list):
                    records.extend(
                        record for record in found if isinstance(record, dict)
                    )
                for nested in current.values():
                    visit(nested)
            elif isinstance(current, list):
                for nested in current:
                    visit(nested)

        visit(value)
        return records

    def identifier(value):
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
        return None

    def market_odd_ids(market):
        """Return flattened selection IDs from summary and full-detail markets."""
        selection_ids = []
        seen_selection_ids = set()

        def add_ids(value):
            if isinstance(value, (list, tuple)):
                for nested in value:
                    add_ids(nested)
                return
            selection_id = identifier(value)
            if (
                selection_id is not None
                and selection_id not in seen_selection_ids
            ):
                seen_selection_ids.add(selection_id)
                selection_ids.append(selection_id)

        for key in ("oddIds", "desktopOddIds", "mobileOddIds"):
            add_ids(market.get(key, []))
        return selection_ids

    def event_detail_containers(value, assume_requested_event=False):
        """Find single-event responses containing markets and odds."""
        containers = []

        def visit(current):
            if isinstance(current, dict):
                nested_event = current.get("event")
                nested_event_id = (
                    identifier(nested_event.get("id"))
                    if isinstance(nested_event, dict)
                    else None
                )
                is_requested_event = (
                    assume_requested_event
                    or identifier(current.get("id")) == event_id
                    or nested_event_id == event_id
                )
                if (
                    is_requested_event
                    and isinstance(current.get("markets"), list)
                    and isinstance(current.get("odds"), list)
                ):
                    containers.append(current)
                for nested in current.values():
                    visit(nested)
            elif isinstance(current, list):
                for nested in current:
                    visit(nested)

        visit(value)
        return containers

    def captured_event_has_odds():
        captured_events = []
        captured_markets = []
        captured_odds = []
        for captured_payload in payloads:
            captured_events.extend(records_named(captured_payload, "events"))
            captured_markets.extend(records_named(captured_payload, "markets"))
            captured_odds.extend(records_named(captured_payload, "odds"))

        captured_market_ids = {
            identifier(market_id)
            for event in captured_events
            if identifier(event.get("id")) == event_id
            for market_id in event.get("marketIds", [])
        }
        for captured_payload in payloads:
            for container in event_detail_containers(captured_payload):
                captured_market_ids.update(
                    identifier(market.get("id"))
                    for market in container["markets"]
                    if isinstance(market, dict)
                )
        for captured_response in requested_event_payloads:
            for container in event_detail_containers(
                captured_response["payload"],
                assume_requested_event=True,
            ):
                captured_market_ids.update(
                    identifier(market.get("id"))
                    for market in container["markets"]
                    if isinstance(market, dict)
                )
        captured_market_ids.discard(None)
        captured_odd_ids = {
            odd_id
            for market in captured_markets
            if identifier(market.get("id")) in captured_market_ids
            for odd_id in market_odd_ids(market)
        }
        captured_odd_ids.discard(None)
        available_odd_ids = {
            identifier(odd.get("id"))
            for odd in captured_odds
            if odd.get("price") not in (None, "")
        }
        available_odd_ids.discard(None)
        return bool(captured_odd_ids & available_odd_ids)

    def captured_full_event_details():
        for captured_response in requested_event_payloads:
            for container in event_detail_containers(
                captured_response["payload"],
                assume_requested_event=True,
            ):
                market_count = len(container.get("markets", []))
                odd_count = len(container.get("odds", []))
                if container.get("showAll") is True:
                    return True
                if market_count >= 20 and odd_count >= 40:
                    return True
        return False

    def wait_for_payload(page, condition, timeout_ms):
        """Yield to browser events until captured data satisfies condition."""
        deadline = monotonic() + timeout_ms / 1_000
        while not condition():
            remaining_ms = int((deadline - monotonic()) * 1_000)
            if remaining_ms <= 0:
                break
            page.wait_for_timeout(min(100, remaining_ms))
        return condition()

    def load_all_market_groups(page):
        """Select every event tab so Playdoit's by-group API returns all markets."""
        tab_selector = (
            'button[class*="EventDetailsTabContainer"], '
            '[class*="EventDetailsTabsContainer"] button'
        )
        tab_frame = None
        tabs = None

        # Receiving the initial moneyline response does not mean React has
        # rendered the market tabs. Wait for them instead of taking an
        # immediate count of zero. Check child frames as well because the
        # sportsbook widget can be embedded there.
        for _ in range(60):
            for frame in page.frames:
                candidate_tabs = frame.locator(tab_selector)
                try:
                    if candidate_tabs.count() and candidate_tabs.first.is_visible():
                        tab_frame = frame
                        tabs = candidate_tabs
                        break
                except Exception:
                    continue
            if tabs is not None:
                break
            page.wait_for_timeout(500)

        if tabs is None or tab_frame is None:
            raise RuntimeError(
                "Playdoit loaded the moneyline but its event market tabs "
                "did not render within 30 seconds"
            )

        tab_count = tabs.count()
        clicked_tabs = 0
        for tab_index in range(tab_count):
            try:
                # React can replace the tab elements after every selection, so
                # resolve the locator again before each click.
                tabs = tab_frame.locator(tab_selector)
                if tab_index >= tabs.count():
                    break
                tab = tabs.nth(tab_index)
                if not tab.is_visible() or not tab.is_enabled():
                    continue
                tab.scroll_into_view_if_needed(timeout=5_000)
                payload_count = len(payloads)
                tab.click(timeout=5_000)
                clicked_tabs += 1
                deadline = monotonic() + 2
                while len(payloads) == payload_count:
                    remaining_ms = int((deadline - monotonic()) * 1_000)
                    if remaining_ms <= 0:
                        break
                    page.wait_for_timeout(min(100, remaining_ms))
            except Exception:
                # Some tabs are replaced while a newly selected market group
                # renders. Continue with the remaining stable tab positions.
                continue

        if clicked_tabs == 0:
            raise RuntimeError(
                "Playdoit's event market tabs rendered, but none could be selected"
            )

    owned_session = None
    if context is None:
        owned_session = PlaydoitSession()
        context = owned_session.__enter__().context

    try:
        page = context.new_page()
        try:
            # A new page is important here. Reusing Chromium's restored page can
            # turn page.goto() into only a hash change, which may not request the
            # complete data for the new event.
            page.on("response", capture_response)
            page.goto(link, wait_until="domcontentloaded", timeout=60_000)
            if page.get_by_text("Acceso bloqueado", exact=True).count():
                raise RuntimeError("Playdoit blocked the browser session")
            wait_for_payload(page, captured_event_has_odds, timeout_ms=16_000)
            if page.get_by_text("Acceso bloqueado", exact=True).count():
                raise RuntimeError("Playdoit blocked the browser session")

            if not captured_event_has_odds():
                # Retry with a real document reload if the SPA supplied only
                # cached event metadata during the first navigation.
                payloads.clear()
                requested_event_payloads.clear()
                page.reload(wait_until="domcontentloaded", timeout=60_000)
                wait_for_payload(
                    page,
                    captured_event_has_odds,
                    timeout_ms=16_000,
                )

            # Playdoit normally returns every event market in one detail
            # response. Give that request time to finish before falling back
            # to selecting individual market tabs.
            wait_for_payload(
                page,
                captured_full_event_details,
                timeout_ms=5_000,
            )

            if not captured_full_event_details():
                load_all_market_groups(page)
        finally:
            page.close()
    finally:
        if owned_session is not None:
            owned_session.__exit__(None, None, None)

    events = []
    markets = []
    odds = []

    for payload in payloads:
        events.extend(records_named(payload, "events"))
        markets.extend(records_named(payload, "markets"))
        odds.extend(records_named(payload, "odds"))

    direct_event_details = []
    for captured_response in requested_event_payloads:
        direct_event_details.extend(
            event_detail_containers(
                captured_response["payload"],
                assume_requested_event=True,
            )
        )

    matching_events = [
        event
        for event in events
        if identifier(event.get("id")) == event_id
        and identifier(event.get("sportId", sport_id_text)) == int(sport_id_text)
    ]
    if not matching_events:
        matching_events.extend(
            {
                "id": event_id,
                "sportId": int(sport_id_text),
                "name": container.get("name", str(event_id)),
                "marketIds": [
                    market_id
                    for market in container.get("markets", [])
                    if isinstance(market, dict)
                    if (market_id := identifier(market.get("id"))) is not None
                ],
            }
            for container in direct_event_details
            if identifier(container.get("id")) in (None, event_id)
        )
    if not matching_events:
        raise ValueError(f"No event data was captured for eventId={event_id}")

    event = max(matching_events, key=lambda item: len(item.get("marketIds", [])))
    event_name = str(event.get("name", event_id))
    name_parts = re.split(r"\s+vs\.?\s+", event_name, maxsplit=1, flags=re.IGNORECASE)
    match_name = "-vs-".join(name_parts) if len(name_parts) == 2 else event_name

    market_ids = set()
    for matching_event in matching_events:
        market_ids.update(
            normalized_id
            for market_id in matching_event.get("marketIds", [])
            if (normalized_id := identifier(market_id)) is not None
        )
    for payload in payloads:
        for container in event_detail_containers(payload):
            market_ids.update(
                normalized_id
                for market in container["markets"]
                if isinstance(market, dict)
                if (normalized_id := identifier(market.get("id"))) is not None
            )
    for captured_response in requested_event_payloads:
        for container in event_detail_containers(
            captured_response["payload"],
            assume_requested_event=True,
        ):
            market_ids.update(
                normalized_id
                for market in container["markets"]
                if isinstance(market, dict)
                if (normalized_id := identifier(market.get("id"))) is not None
            )

    # The same market can occur in several responses. Keep the richest version
    # instead of allowing a later summary record to erase its oddIds.
    event_markets = {}
    for market in markets:
        market_id = identifier(market.get("id"))
        if market_id not in market_ids:
            continue
        previous = event_markets.get(market_id, {})
        merged = dict(previous)
        merged.update(
            {
                key: value
                for key, value in market.items()
                if value not in (None, "", [], {})
            }
        )
        if len(previous.get("oddIds", [])) > len(market.get("oddIds", [])):
            merged["oddIds"] = previous["oddIds"]
        event_markets[market_id] = merged

    event_odd_ids = {
        odd_id
        for market in event_markets.values()
        for odd_id in market_odd_ids(market)
    }

    def numeric_price(value):
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip().replace(",", "."))
            except ValueError:
                return None
        return None

    event_odds = {}
    for odd in odds:
        odd_id = identifier(odd.get("id"))
        price = numeric_price(odd.get("price"))
        odd_status = odd.get("oddStatus", 0)
        if odd_id not in event_odd_ids or price is None:
            continue
        if odd_status not in (None, 0, "0"):
            continue
        previous = event_odds.get(odd_id, {})
        merged = dict(previous)
        merged.update(
            {
                key: value
                for key, value in odd.items()
                if value not in (None, "", [], {})
            }
        )
        merged["price"] = price
        event_odds[odd_id] = merged

    columns = [
        "match", "Bookmarker", "HT", "DRAW", "AT",
        "O0.5", "U0.5", "O1.5", "U1.5", "O2.5", "U2.5",
        "O3.5", "U3.5", "O4.5", "U4.5",
        "DC_HT_DRAW", "DC_HT_AT", "DC_AT_DRAW", "BTTS_YES", "BTTS_NO",
        "1H_O0.5", "1H_U0.5", "1H_O1.5", "1H_U1.5", "1H_O2.5", "1H_U2.5",
        "2H_O0.5", "2H_U0.5", "2H_O1.5", "2H_U1.5", "2H_O2.5", "2H_U2.5",
        "timestamp_utc",
    ]
    values = {
        "match": match_name,
        "Bookmarker": "Playdoit",
    }

    for market in event_markets.values():
        market_name = text_key(market.get("name", ""))
        market_type = identifier(market.get("typeId"))
        selections = [
            event_odds[odd_id]
            for odd_id in market_odd_ids(market)
            if odd_id in event_odds
        ]

        if market_type == 1 or market_name == "resultado final (tiempo regular)":
            for selection in selections:
                selection_type = identifier(selection.get("typeId"))
                if selection_type == 1:
                    values["HT"] = float(selection["price"])
                elif selection_type == 2:
                    values["DRAW"] = float(selection["price"])
                elif selection_type == 3:
                    values["AT"] = float(selection["price"])
            continue

        if market_type == 10 or market_name == "doble oportunidad":
            for selection in selections:
                selection_type = identifier(selection.get("typeId"))
                if selection_type == 9:
                    values["DC_HT_DRAW"] = float(selection["price"])
                elif selection_type == 10:
                    values["DC_HT_AT"] = float(selection["price"])
                elif selection_type == 11:
                    values["DC_AT_DRAW"] = float(selection["price"])
            continue

        if market_type == 29 or market_name == "ambos equipos marcan":
            for selection in selections:
                selection_type = identifier(selection.get("typeId"))
                if selection_type == 74:
                    values["BTTS_YES"] = float(selection["price"])
                elif selection_type == 76:
                    values["BTTS_NO"] = float(selection["price"])
            continue

        if market_type == 68 or market_name in {
            "1a mitad - total",
            "1er tiempo - total",
            "primera mitad - total",
        }:
            prefix = "1H_"
        elif market_type == 90 or market_name in {
            "2a mitad - total",
            "2do tiempo - total",
            "segunda mitad - total",
        }:
            prefix = "2H_"
        elif market_type == 18 or market_name in {"total", "total de goles"}:
            prefix = ""
        else:
            continue

        market_line = (
            str(market.get("sv", market.get("sn", "")))
            .split("|", 1)[0]
            .replace(",", ".")
        )
        for selection in selections:
            selection_name = text_key(selection.get("name", ""))
            line_match = re.search(r"(\d+(?:\.\d+)?)", selection_name)
            line = line_match.group(1) if line_match else market_line
            if line not in {"0.5", "1.5", "2.5", "3.5", "4.5"}:
                continue
            selection_type = identifier(selection.get("typeId"))
            if selection_type == 12 or selection_name.startswith(("mas de", "over")):
                values[f"{prefix}O{line}"] = float(selection["price"])
            elif selection_type == 13 or selection_name.startswith(("menos de", "under")):
                values[f"{prefix}U{line}"] = float(selection["price"])

    values["timestamp_utc"] = datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")
    return pd.Series(
        [values.get(column, pd.NA) for column in columns],
        index=[f"pd_{column}" for column in columns],
    )
