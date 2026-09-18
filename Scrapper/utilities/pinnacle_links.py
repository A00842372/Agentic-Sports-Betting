def pinnacle_links(link):
    """Return matches, UTC start times, and links for a Pinnacle competition."""
    import html
    import json
    import re
    from datetime import datetime, timezone
    from pathlib import Path
    from urllib.parse import unquote, urlsplit, urlunsplit

    import pandas as pd

    if not isinstance(link, str):
        raise TypeError("link must be a string")

    supplied_url = link.strip()
    parsed_url = urlsplit(supplied_url)
    hostname = (parsed_url.hostname or "").casefold()
    if (
        parsed_url.scheme not in {"http", "https"}
        or hostname not in {"pinnacle.com", "www.pinnacle.com"}
    ):
        raise ValueError("link must be a complete Pinnacle http or https URL")

    competition_path = parsed_url.path.rstrip("/")
    if competition_path.casefold().endswith("/matchups"):
        competition_path = competition_path[: -len("/matchups")].rstrip("/")

    path_parts = [part for part in competition_path.split("/") if part]
    if len(path_parts) < 3:
        raise ValueError("link must point to a Pinnacle competition page")

    competition_url = urlunsplit(
        (
            "https",
            "www.pinnacle.com",
            f"{competition_path}/matchups/",
            "",
            "all",
        )
    )
    columns = ["match", "start_time", "Pinnacle link"]

    event_pattern = re.compile(
        r"(?:(?:https?:)?//(?:www\.)?pinnacle\.com)?"
        rf"(?P<path>{re.escape(competition_path)}/"
        r"(?!matchups(?:/|$))"
        r"[^/?#\"'<>\\\s]+/\d+/?)"
        r"(?:#all)?",
        flags=re.IGNORECASE,
    )

    def extract_links(text):
        text = html.unescape(text)
        text = re.sub(r"\\u002[fF]", "/", text)
        text = re.sub(r"\\u003[aA]", ":", text)
        text = re.sub(r"\\u0023", "#", text)
        text = re.sub(r"\\u002[dD]", "-", text)
        text = text.replace("\\/", "/")

        links = []
        seen = set()
        for match in event_pattern.finditer(text):
            path = match.group("path")
            event_url = f"https://www.pinnacle.com{path.rstrip('/')}/#all"
            comparison_key = event_url.casefold()
            if comparison_key not in seen:
                seen.add(comparison_key)
                links.append(event_url)
        return links

    def parse_start_time(value):
        if isinstance(value, bool):
            return None
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
            parsed_datetime = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed_datetime.tzinfo is None:
            parsed_datetime = parsed_datetime.replace(tzinfo=timezone.utc)
        return parsed_datetime.astimezone(timezone.utc)

    def normalize_match_name(value):
        if not isinstance(value, str):
            return None
        teams = re.split(
            r"\s+vs\.?\s+", html.unescape(value).strip(), maxsplit=1,
            flags=re.IGNORECASE,
        )
        if len(teams) != 2:
            return None
        home_team, away_team = (" ".join(team.split()) for team in teams)
        if not home_team or not away_team:
            return None
        return f"{home_team}-vs-{away_team}"

    def match_name_from_url(event_url):
        path_parts = [part for part in urlsplit(event_url).path.split("/") if part]
        if len(path_parts) < 2:
            return None
        slug = unquote(path_parts[-2])
        teams = re.split(r"-vs-", slug, maxsplit=1, flags=re.IGNORECASE)
        if len(teams) != 2:
            return None
        home_team, away_team = (
            " ".join(team.replace("-", " ").split()) for team in teams
        )
        if not home_team or not away_team:
            return None
        return f"{home_team}-vs-{away_team}"

    def metadata_from_payloads(payloads):
        events = {}

        def participant_name(participants, alignment, fallback_index):
            aligned_participant = next(
                (
                    participant
                    for participant in participants
                    if isinstance(participant, dict)
                    and str(participant.get("alignment", "")).casefold()
                    == alignment
                ),
                None,
            )
            if aligned_participant is None and len(participants) > fallback_index:
                aligned_participant = participants[fallback_index]
            if not isinstance(aligned_participant, dict):
                return None
            name = aligned_participant.get("name")
            return " ".join(str(name).split()) if name else None

        def visit(value):
            if isinstance(value, dict):
                normalized = {
                    str(key).casefold(): item for key, item in value.items()
                }
                event_id = normalized.get("id")
                start_time = parse_start_time(
                    normalized.get(
                        "starttime",
                        normalized.get("startdate", normalized.get("scheduledat")),
                    )
                )
                participants = normalized.get("participants")
                match_name = normalize_match_name(normalized.get("name"))

                try:
                    event_id = int(event_id)
                except (TypeError, ValueError):
                    pass
                else:
                    if start_time is not None:
                        if match_name is None and isinstance(participants, list):
                            home_team = participant_name(participants, "home", 0)
                            away_team = participant_name(participants, "away", 1)
                            if home_team and away_team:
                                match_name = f"{home_team}-vs-{away_team}"
                        if match_name is not None:
                            events[event_id] = {
                                "match": match_name,
                                "start_time": start_time,
                            }

                for item in value.values():
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        for payload in payloads:
            visit(payload)
        return events

    def json_scripts_from_page(page_source):
        payloads = []
        for script_match in re.finditer(
            r'<script\b[^>]*type\s*=\s*(["\'])application/(?:ld\+)?json\1'
            r"[^>]*>(.*?)</script>",
            page_source,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            try:
                payloads.append(json.loads(html.unescape(script_match.group(2))))
            except (TypeError, ValueError):
                pass
        return payloads

    from playwright.sync_api import sync_playwright

    profile_path = Path(__file__).with_name("pinnacle_profile")
    captured_payloads = []

    def capture_response(response):
        try:
            if response.request.resource_type not in {"xhr", "fetch"}:
                return
            body = response.text()
            if not body or len(body) > 20_000_000:
                return
            stripped_body = body.lstrip()
            if not stripped_body.startswith(("{", "[")):
                return
            payload = json.loads(body)
            captured_payloads.append(payload)
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
            page = context.new_page()
            page.on("response", capture_response)
            page.goto(
                competition_url,
                wait_until="domcontentloaded",
                timeout=60_000,
            )

            rendered_links = []
            for _ in range(60):
                rendered_links = page.locator("a[href]").evaluate_all(
                    """elements => elements.map(
                        element => element.href || element.getAttribute('href')
                    ).filter(Boolean)"""
                )
                if extract_links("\n".join(rendered_links)):
                    break
                page.wait_for_timeout(500)

            page.wait_for_timeout(2_000)
            rendered_source = (
                page.content()
                + "\n"
                + "\n".join(rendered_links)
                + "\n"
                + "\n".join(
                    json.dumps(payload, ensure_ascii=False)
                    for payload in captured_payloads
                )
            )
        finally:
            context.close()

    event_metadata = metadata_from_payloads(
        captured_payloads + json_scripts_from_page(rendered_source)
    )
    records = []
    seen = set()
    for event_url in extract_links(rendered_source):
        event_id_match = re.search(r"/(\d+)/?$", urlsplit(event_url).path)
        if not event_id_match:
            continue
        event_id = int(event_id_match.group(1))
        metadata = event_metadata.get(event_id, {})
        match_name = metadata.get("match") or match_name_from_url(event_url)
        if match_name is None or event_url.casefold() in seen:
            continue
        records.append(
            {
                "match": match_name,
                "start_time": metadata.get("start_time"),
                "Pinnacle link": event_url,
            }
        )
        seen.add(event_url.casefold())

    dataframe = pd.DataFrame.from_records(records, columns=columns)
    dataframe["start_time"] = pd.to_datetime(
        dataframe["start_time"], errors="coerce", utc=True
    )
    return dataframe
