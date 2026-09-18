def playdoit_links(link):
    """Return next-seven-day Playdoit matches, start times, and event links."""
    import json
    import re
    from datetime import datetime, timedelta, timezone
    from pathlib import Path
    from urllib.parse import parse_qs, urlsplit

    import pandas as pd
    import requests

    if not isinstance(link, str):
        raise TypeError("link must be a string")

    competition_url = link.strip()
    parsed_url = urlsplit(competition_url)
    hostname = (parsed_url.hostname or "").casefold()
    if (
        parsed_url.scheme not in {"http", "https"}
        or hostname not in {"playdoit.mx", "www.playdoit.mx"}
    ):
        raise ValueError("link must be a complete Playdoit http or https URL")

    fragment_parameters = {
        key.casefold(): values
        for key, values in parse_qs(
            parsed_url.fragment, keep_blank_values=True
        ).items()
    }
    championship_ids = {
        int(identifier)
        for value in fragment_parameters.get("championshipids", [])
        for identifier in re.findall(r"\d+", value)
    }
    if not championship_ids:
        raise ValueError(
            "link must be a Playdoit competition URL containing championshipIds"
        )

    window_start = datetime.now(timezone.utc)
    window_end = window_start + timedelta(days=7)
    columns = ["match", "start_time", "Playdoit link"]

    def make_dataframe(records):
        dataframe = pd.DataFrame.from_records(records, columns=columns)
        dataframe["start_time"] = pd.to_datetime(
            dataframe["start_time"], errors="coerce", utc=True
        )
        return dataframe.sort_values("start_time").reset_index(drop=True)

    def normalize_match_name(value):
        if not isinstance(value, str):
            return None
        teams = re.split(
            r"\s+vs\.?\s+", value.strip(), maxsplit=1, flags=re.IGNORECASE
        )
        if len(teams) != 2:
            return None
        home_team, away_team = (" ".join(team.split()) for team in teams)
        if not home_team or not away_team:
            return None
        return f"{home_team}-vs-{away_team}"

    def parse_start_date(value):
        if isinstance(value, (int, float)):
            timestamp = float(value)
            if timestamp > 10_000_000_000:
                timestamp /= 1000
            try:
                return datetime.fromtimestamp(timestamp, timezone.utc)
            except (OverflowError, OSError, ValueError):
                return None

        if not isinstance(value, str):
            return None
        normalized = value.strip().replace("Z", "+00:00")
        if not normalized:
            return None
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def links_from_payloads(payloads):
        records = []
        seen = set()
        competitor_names = {}

        def collect_competitors(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if str(key).casefold() == "competitors" and isinstance(item, list):
                        for competitor in item:
                            if not isinstance(competitor, dict):
                                continue
                            try:
                                competitor_id = int(competitor.get("id"))
                            except (TypeError, ValueError):
                                continue
                            name = competitor.get("name")
                            if name:
                                competitor_names[competitor_id] = " ".join(
                                    str(name).split()
                                )
                    collect_competitors(item)
            elif isinstance(value, list):
                for item in value:
                    collect_competitors(item)

        for payload in payloads:
            collect_competitors(payload)

        def visit(value):
            if isinstance(value, dict):
                normalized_keys = {
                    str(key).casefold(): item for key, item in value.items()
                }
                championship_id = normalized_keys.get(
                    "champid", normalized_keys.get("championshipid")
                )
                sport_id = normalized_keys.get("sportid")
                event_id = normalized_keys.get(
                    "eventid", normalized_keys.get("id")
                )
                start_date = normalized_keys.get(
                    "startdate", normalized_keys.get("starttime")
                )
                match_name = normalize_match_name(normalized_keys.get("name"))
                if match_name is None:
                    competitor_ids = normalized_keys.get("competitorids")
                    if isinstance(competitor_ids, list) and len(competitor_ids) >= 2:
                        try:
                            home_team = competitor_names[int(competitor_ids[0])]
                            away_team = competitor_names[int(competitor_ids[1])]
                        except (KeyError, TypeError, ValueError):
                            pass
                        else:
                            match_name = f"{home_team}-vs-{away_team}"

                try:
                    championship_id = int(championship_id)
                    sport_id = int(sport_id)
                    event_id = int(event_id)
                except (TypeError, ValueError):
                    pass
                else:
                    event_time = parse_start_date(start_date)
                    if (
                        championship_id in championship_ids
                        and event_time is not None
                        and match_name is not None
                        and window_start <= event_time <= window_end
                    ):
                        event_link = (
                            "https://www.playdoit.mx/#page=event"
                            f"&eventId={event_id}&sportId={sport_id}"
                        )
                        if event_link not in seen:
                            seen.add(event_link)
                            records.append(
                                {
                                    "match": match_name,
                                    "start_time": event_time,
                                    "Playdoit link": event_link,
                                }
                            )

                for item in value.values():
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        for payload in payloads:
            visit(payload)
        return records

    def links_from_text(source):
        source = (
            source.replace("\\u0026", "&")
            .replace("\\u002F", "/")
            .replace("\\u002f", "/")
            .replace("\\u003A", ":")
            .replace("\\u003a", ":")
            .replace("\\u003D", "=")
            .replace("\\u003d", "=")
        )
        event_pattern = re.compile(
            r'"sportId"\s*:\s*(?P<sport_id>\d+)'
            r'.{0,700}?"champId"\s*:\s*(?P<champ_id>\d+)'
            r'.{0,700}?"startDate"\s*:\s*"(?P<start_date>[^"]+)"'
            r'.{0,300}?"id"\s*:\s*(?P<event_id>\d+)'
            r'.{0,300}?"name"\s*:\s*"(?P<name>(?:\\.|[^"])*)"',
            flags=re.IGNORECASE | re.DOTALL,
        )

        records = []
        seen = set()
        for event_match in event_pattern.finditer(source):
            if int(event_match.group("champ_id")) not in championship_ids:
                continue
            event_time = parse_start_date(event_match.group("start_date"))
            if event_time is None or not (
                window_start <= event_time <= window_end
            ):
                continue
            try:
                raw_name = json.loads(f'"{event_match.group("name")}"')
            except (TypeError, ValueError):
                raw_name = event_match.group("name")
            match_name = normalize_match_name(raw_name)
            if match_name is None:
                continue
            event_link = (
                "https://www.playdoit.mx/#page=event"
                f"&eventId={event_match.group('event_id')}"
                f"&sportId={event_match.group('sport_id')}"
            )
            if event_link not in seen:
                seen.add(event_link)
                records.append(
                    {
                        "match": match_name,
                        "start_time": event_time,
                        "Playdoit link": event_link,
                    }
                )
        return records

    # Playdoit's old championship hash no longer opens the selected league on
    # a fresh page load. Query the same endpoint used by the current site so
    # the requested championship is loaded explicitly.
    overview_url = (
        "https://sb2frontend-altenar2.biahosted.com/api/widget/GetOverview"
    )
    overview_payloads = []
    overview_available = True

    with requests.Session() as session:
        session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/136.0.0.0 Safari/537.36"
                ),
            }
        )
        for championship_id in sorted(championship_ids):
            try:
                response = session.get(
                    overview_url,
                    params={
                        "culture": "es-ES",
                        "timezoneOffset": 360,
                        "integration": "playdoit2",
                        "deviceType": 1,
                        "numFormat": "en-GB",
                        "countryCode": "MX",
                        "eventCount": 0,
                        "sportId": 0,
                        "champIds": championship_id,
                        "withLive": "false",
                    },
                    timeout=30,
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict) or "events" not in payload:
                    raise ValueError("unexpected Playdoit overview response")
            except (requests.RequestException, ValueError):
                overview_available = False
                break
            overview_payloads.append(payload)

    if overview_available:
        return make_dataframe(links_from_payloads(overview_payloads))

    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    profile_path = Path(__file__).with_name("playdoit_profile")
    captured_payloads = []
    captured_text = []

    def capture_response(response):
        try:
            if response.request.resource_type not in {"xhr", "fetch"}:
                return
            body = response.text()
            if not body or len(body) > 20_000_000:
                return
            captured_text.append(body)
            stripped_body = body.lstrip()
            if stripped_body.startswith(("{", "[")):
                captured_payloads.append(json.loads(body))
        except Exception:
            pass

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_path),
            headless=False,
            locale="es-MX",
            timezone_id="America/Mexico_City",
            viewport={"width": 1440, "height": 1000},
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.on("response", capture_response)
            page.goto(
                competition_url,
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            page.wait_for_timeout(3_000)

            if page.get_by_text("Acceso bloqueado", exact=True).count():
                raise RuntimeError(
                    "Playdoit blocked the browser session. Close the browser, "
                    "retry, or complete any verification shown by Playdoit."
                )

            try:
                page.wait_for_function(
                    """() => {
                        const root = document.querySelector('#root');
                        return root && root.childElementCount > 0;
                    }""",
                    timeout=60_000,
                )
            except PlaywrightTimeoutError:
                pass

            for _ in range(30):
                if links_from_payloads(captured_payloads):
                    break
                page.wait_for_timeout(500)

            shadow_html = page.evaluate(
                """() => {
                    const fragments = [];
                    const visit = root => {
                        for (const element of root.querySelectorAll('*')) {
                            if (element.shadowRoot) {
                                fragments.push(element.shadowRoot.innerHTML);
                                visit(element.shadowRoot);
                            }
                        }
                    };
                    visit(document);
                    return fragments.join('\\n');
                }"""
            )
            rendered_source = (
                page.content()
                + "\n"
                + shadow_html
                + "\n"
                + "\n".join(captured_text)
            )
        finally:
            context.close()

    records = links_from_payloads(captured_payloads)
    if not records:
        records = links_from_text(rendered_source)

    return make_dataframe(records)
