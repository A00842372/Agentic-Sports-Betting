def caliente_links(link):
    """Return upcoming Caliente matches, UTC start times, and event links."""
    import html as html_module
    import re
    import unicodedata
    from datetime import date, datetime, time, timedelta, timezone
    from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

    import pandas as pd
    import requests

    if not isinstance(link, str):
        raise TypeError("link must be a string")

    page_url = link.strip()
    parsed_page_url = urlsplit(page_url)
    if parsed_page_url.scheme not in {"http", "https"} or not parsed_page_url.netloc:
        raise ValueError("link must be a complete http or https URL")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/138.0 Safari/537.36"
        ),
        "Accept-Language": "es-MX,es;q=0.9",
    }

    with requests.Session() as session:
        initial_response = session.get(
            page_url,
            headers=headers,
            timeout=30,
        )
        initial_response.raise_for_status()

        timezone_response = session.post(
            urljoin(initial_response.url, "/web_nr"),
            headers=headers,
            data={
                "key": "region.do_set_region_opts",
                "tz_offset": "-6",
            },
            timeout=30,
        )
        timezone_response.raise_for_status()

        response = session.get(
            page_url,
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()

    source = response.text
    final_page_url = response.url
    competition_path = urlsplit(final_page_url).path.rstrip("/")

    caliente_timezone = timezone(timedelta(hours=-6), name="GMT-6")
    now = datetime.now(caliente_timezone)
    window_end = now + timedelta(days=7)
    columns = ["match", "start_time", "Caliente link"]

    month_numbers = {
        "ene": 1,
        "feb": 2,
        "mar": 3,
        "abr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "ago": 8,
        "sep": 9,
        "set": 9,
        "oct": 10,
        "nov": 11,
        "dic": 12,
    }

    def clean_text(value):
        value = re.sub(r"<[^>]+>", " ", value)
        value = html_module.unescape(value)
        return " ".join(value.split())

    def plain_text(value):
        value = clean_text(value)
        value = unicodedata.normalize("NFKD", value.casefold())
        value = "".join(
            character for character in value if not unicodedata.combining(character)
        )
        return " ".join(value.split())

    def match_name_from_link(href_match, parsed_url):
        anchor_start = source.rfind("<a", 0, href_match.start())
        if anchor_start != -1:
            opening_tag_end = source.find(">", anchor_start, href_match.end() + 1)
            anchor_end = source.find("</a>", href_match.end())
            if (
                opening_tag_end != -1
                and anchor_end != -1
                and href_match.start() < opening_tag_end < anchor_end
            ):
                displayed_name = clean_text(
                    source[opening_tag_end + 1 : anchor_end]
                )
                teams = re.split(
                    r"\s+vs\.?\s+", displayed_name, maxsplit=1, flags=re.IGNORECASE
                )
                if len(teams) == 2 and all(team.strip() for team in teams):
                    return f"{teams[0].strip()}-vs-{teams[1].strip()}"

        slug = unquote(parsed_url.path.rstrip("/").rsplit("/", 1)[-1])
        teams = re.split(r"-vs-", slug, maxsplit=1, flags=re.IGNORECASE)
        if len(teams) != 2:
            return None
        home_team, away_team = (
            " ".join(team.replace("-", " ").split()) for team in teams
        )
        if not home_team or not away_team:
            return None
        return f"{home_team}-vs-{away_team}"

    def date_from_row(row):
        date_match = re.search(
            r'<span\b[^>]*class\s*=\s*(["\'])[^"\']*\bdate\b[^"\']*\1[^>]*>'
            r"(.*?)</span>",
            row,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not date_match:
            return None

        displayed_date = plain_text(date_match.group(2))
        if displayed_date == "hoy":
            return now.date()
        if displayed_date == "manana":
            return now.date() + timedelta(days=1)

        day_and_month = re.search(r"\b(\d{1,2})\s+([a-z]{3,})\b", displayed_date)
        if not day_and_month:
            return None

        day = int(day_and_month.group(1))
        month = month_numbers.get(day_and_month.group(2)[:3])
        if month is None:
            return None

        candidates = []
        for year in (now.year - 1, now.year, now.year + 1):
            try:
                candidates.append(date(year, month, day))
            except ValueError:
                pass
        return min(candidates, key=lambda value: abs((value - now.date()).days))

    def datetime_from_row(row, event_date):
        datetime_attribute = re.search(
            r'<time\b[^>]*\bdatetime\s*=\s*(["\'])(.*?)\1',
            row,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if datetime_attribute:
            normalized_datetime = html_module.unescape(
                datetime_attribute.group(2)
            ).strip()
            if normalized_datetime.endswith("Z"):
                normalized_datetime = normalized_datetime[:-1] + "+00:00"
            try:
                parsed_datetime = datetime.fromisoformat(normalized_datetime)
            except ValueError:
                pass
            else:
                if parsed_datetime.tzinfo is None:
                    parsed_datetime = parsed_datetime.replace(tzinfo=timezone.utc)
                return parsed_datetime.astimezone(caliente_timezone)

        time_match = re.search(
            r'<span\b[^>]*class\s*=\s*(["\'])[^"\']*\btime\b[^"\']*\1[^>]*>'
            r"(.*?)</span>",
            row,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not time_match:
            return None
        if event_date is None:
            return None

        displayed_time = plain_text(time_match.group(2))
        hours_and_minutes = re.search(r"\b(\d{1,2}):(\d{2})\b", displayed_time)
        if not hours_and_minutes:
            return None

        event_time = time(
            hour=int(hours_and_minutes.group(1)),
            minute=int(hours_and_minutes.group(2)),
        )
        return datetime.combine(event_date, event_time, tzinfo=caliente_timezone)

    def enclosing_row(position):
        row_start = source.rfind("<tr", 0, position)
        if row_start == -1:
            return ""
        opening_tag_end = source.find(">", row_start, position)
        row_end = source.find("</tr>", position)
        if opening_tag_end == -1 or row_end == -1:
            return ""
        return source[row_start : row_end + len("</tr>")]

    href_pattern = re.compile(
        r'\bhref\s*=\s*(["\'])(.*?)\1', flags=re.IGNORECASE | re.DOTALL
    )
    dated_path_pattern = re.compile(
        rf"^{re.escape(competition_path)}/(\d{{4}}-\d{{2}}-\d{{2}})/[^/]+/?$",
        flags=re.IGNORECASE,
    )
    event_path_pattern = re.compile(
        r"^/es_MX/e/\d+/[^/]+/?$", flags=re.IGNORECASE
    )

    records = []
    seen = set()
    for href_match in href_pattern.finditer(source):
        href = html_module.unescape(href_match.group(2)).strip()
        absolute_url = urljoin(final_page_url, href)
        parsed_url = urlsplit(absolute_url)

        if (parsed_url.hostname or "").casefold() != "sports.caliente.mx":
            continue

        dated_match = dated_path_pattern.fullmatch(parsed_url.path)
        is_event_path = event_path_pattern.fullmatch(parsed_url.path)
        if not dated_match and not is_event_path:
            continue

        row = enclosing_row(href_match.start())
        if dated_match:
            event_date = date.fromisoformat(dated_match.group(1))
        else:
            event_date = date_from_row(row)

        event_datetime = datetime_from_row(row, event_date)
        if event_datetime is None or not (now <= event_datetime <= window_end):
            continue

        normalized_url = urlunsplit(
            ("https", "sports.caliente.mx", parsed_url.path.rstrip("/"), "", "")
        )
        match_name = match_name_from_link(href_match, parsed_url)
        if match_name is None or normalized_url in seen:
            continue
        records.append(
            {
                "match": match_name,
                "start_time": event_datetime.astimezone(timezone.utc),
                "Caliente link": normalized_url,
            }
        )
        seen.add(normalized_url)

    dataframe = pd.DataFrame.from_records(records, columns=columns)
    dataframe["start_time"] = pd.to_datetime(
        dataframe["start_time"], errors="coerce", utc=True
    )
    return dataframe
