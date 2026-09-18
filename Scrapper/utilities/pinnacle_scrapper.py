import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit

import pandas as pd
from playwright.sync_api import sync_playwright


def _launch_pinnacle_context(playwright, headless=False):
    profile_path = Path(__file__).with_name("pinnacle_profile")
    return playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile_path),
        headless=headless,
        locale="es-MX",
        timezone_id="America/Mexico_City",
        viewport={"width": 1440, "height": 1000},
    )


class PinnacleSession:
    """Reuse one Chromium context across multiple Pinnacle events."""

    def __init__(self, headless=False):
        self.headless = headless
        self._playwright = None
        self.context = None

    def __enter__(self):
        self._playwright = sync_playwright().start()
        try:
            self.context = _launch_pinnacle_context(
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
            raise RuntimeError("PinnacleSession must be opened before scraping")
        return pinnacle_scrapper(link, context=self.context)

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if self.context is not None:
                self.context.close()
        finally:
            self.context = None
            if self._playwright is not None:
                self._playwright.stop()
                self._playwright = None


def pinnacle_scrapper(link, context=None):
    """Return a Pinnacle event's core soccer odds as a pandas Series.

    When ``context`` is supplied, it is reused and only the event page is
    closed. Standalone calls retain the original open-scrape-close behavior.
    """

    if not isinstance(link, str):
        raise TypeError("link must be a string")

    parsed_link = urlsplit(link.strip())
    if parsed_link.netloc.casefold() not in {
        "pinnacle.com",
        "www.pinnacle.com",
    }:
        raise ValueError("link must point to www.pinnacle.com")

    event_id_match = re.search(r"/(\d+)/?$", parsed_link.path)
    if not event_id_match:
        raise ValueError("link must end with a numeric Pinnacle event ID")
    event_id = int(event_id_match.group(1))

    def text_key(value):
        normalized = unicodedata.normalize("NFKD", str(value))
        normalized = "".join(
            character
            for character in normalized
            if not unicodedata.combining(character)
        )
        return " ".join(normalized.casefold().split())

    def decimal_price(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if value == 0:
            return None
        if value > 0:
            decimal = 1 + value / 100
        else:
            decimal = 1 + 100 / abs(value)
        return round(decimal, 4)

    markets_payloads = []
    matchups_payloads = []
    markets_path = f"/matchups/{event_id}/markets/related/straight"
    matchups_path = f"/matchups/{event_id}/related"

    def capture_response(response):
        try:
            response_url = response.url.casefold()
            if markets_path in response_url:
                payload = json.loads(response.text())
                if isinstance(payload, list):
                    markets_payloads.append(payload)
            elif matchups_path in response_url:
                payload = json.loads(response.text())
                if isinstance(payload, list):
                    matchups_payloads.append(payload)
        except Exception:
            pass

    owned_session = None
    if context is None:
        owned_session = PinnacleSession()
        context = owned_session.__enter__().context

    try:
        page = context.new_page()
        try:
            page.on("response", capture_response)
            page.goto(
                link,
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            deadline = monotonic() + 30
            while not (markets_payloads and matchups_payloads):
                remaining_ms = int((deadline - monotonic()) * 1_000)
                if remaining_ms <= 0:
                    break
                page.wait_for_timeout(min(100, remaining_ms))
        finally:
            page.close()
    finally:
        if owned_session is not None:
            owned_session.__exit__(None, None, None)

    if not markets_payloads:
        raise ValueError(
            f"No Pinnacle market data was captured for event ID {event_id}"
        )
    if not matchups_payloads:
        raise ValueError(
            f"No Pinnacle matchup data was captured for event ID {event_id}"
        )

    markets = markets_payloads[-1]
    matchups = matchups_payloads[-1]
    matchups_by_id = {
        matchup.get("id"): matchup
        for matchup in matchups
        if isinstance(matchup, dict) and isinstance(matchup.get("id"), int)
    }
    event = matchups_by_id.get(event_id)
    if event is None:
        raise ValueError(
            f"Pinnacle did not return the requested event ID {event_id}"
        )

    event_participants = event.get("participants", [])
    home_participant = next(
        (
            participant
            for participant in event_participants
            if participant.get("alignment") == "home"
        ),
        event_participants[0] if event_participants else {},
    )
    away_participant = next(
        (
            participant
            for participant in event_participants
            if participant.get("alignment") == "away"
        ),
        event_participants[1] if len(event_participants) > 1 else {},
    )
    home_team = str(home_participant.get("name", "Home"))
    away_team = str(away_participant.get("name", "Away"))

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
        "match": f"{home_team}-vs-{away_team}",
        "Bookmarker": "Pinnacle",
    }

    event_markets = [
        market
        for market in markets
        if isinstance(market, dict)
        and market.get("matchupId") == event_id
        and market.get("status", "open") == "open"
    ]

    for market in event_markets:
        market_type = market.get("type")
        period = market.get("period")
        prices = market.get("prices", [])

        if market_type == "moneyline" and period == 0:
            for price in prices:
                column = {
                    "home": "HT",
                    "draw": "DRAW",
                    "away": "AT",
                }.get(price.get("designation"))
                if column:
                    converted = decimal_price(price.get("price"))
                    if converted is not None:
                        values[column] = converted
            continue

        if market_type != "total" or period not in {0, 1, 2}:
            continue
        prefix = {0: "", 1: "1H_", 2: "2H_"}[period]
        for price in prices:
            points = price.get("points")
            if not isinstance(points, (int, float)):
                continue
            line = f"{float(points):.1f}"
            allowed_lines = (
                {"0.5", "1.5", "2.5", "3.5", "4.5"}
                if period == 0
                else {"0.5", "1.5", "2.5"}
            )
            if line not in allowed_lines:
                continue
            designation = price.get("designation")
            side = "O" if designation == "over" else "U" if designation == "under" else None
            converted = decimal_price(price.get("price"))
            if side and converted is not None:
                values[f"{prefix}{side}{line}"] = converted

    related_markets = {
        market.get("matchupId"): market
        for market in markets
        if isinstance(market, dict)
        and market.get("type") == "moneyline"
        and market.get("period") == 0
        and market.get("status", "open") == "open"
    }

    for related_matchup in matchups:
        if not isinstance(related_matchup, dict):
            continue
        if related_matchup.get("parentId") != event_id:
            continue
        description = text_key(
            (related_matchup.get("special") or {}).get("description", "")
        )
        if description not in {"double chance", "both teams to score?"}:
            continue
        related_market = related_markets.get(related_matchup.get("id"))
        if not related_market:
            continue

        participant_names = {
            participant.get("id"): text_key(participant.get("name", ""))
            for participant in related_matchup.get("participants", [])
        }
        for price in related_market.get("prices", []):
            participant_name = participant_names.get(price.get("participantId"), "")
            converted = decimal_price(price.get("price"))
            if converted is None:
                continue

            if description == "both teams to score?":
                if participant_name == "yes":
                    values["BTTS_YES"] = converted
                elif participant_name == "no":
                    values["BTTS_NO"] = converted
                continue

            has_home = text_key(home_team) in participant_name
            has_away = text_key(away_team) in participant_name
            has_draw = "draw" in participant_name
            if has_home and has_draw:
                values["DC_HT_DRAW"] = converted
            elif has_home and has_away:
                values["DC_HT_AT"] = converted
            elif has_away and has_draw:
                values["DC_AT_DRAW"] = converted

    values["timestamp_utc"] = datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")
    return pd.Series(
        [values.get(column, pd.NA) for column in columns],
        index=[f"pn_{column}" for column in columns],
    )
