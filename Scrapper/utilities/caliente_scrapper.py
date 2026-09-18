import requests


class CalienteSession:
    """Reuse one HTTP session across multiple Caliente events."""

    def __init__(self):
        self.session = None

    def __enter__(self):
        self.session = requests.Session()
        return self

    def scrape(self, link):
        if self.session is None:
            raise RuntimeError("CalienteSession must be opened before scraping")
        return caliente_scrapper(link, session=self.session)

    def __exit__(self, exc_type, exc_value, traceback):
        if self.session is not None:
            self.session.close()
            self.session = None


def caliente_scrapper(link, session=None):
    """Fetch a Caliente event link and return one CSV-ready pandas Series.

    When ``session`` is supplied, its cookies and HTTP connection pool are
    reused. Standalone calls still create and close their own session.
    """
    import html as html_module
    import re
    import unicodedata
    from datetime import datetime, timezone
    from urllib.parse import urljoin, urlsplit

    import pandas as pd

    if not isinstance(link, str):
        raise TypeError("link must be a string")

    event_url = link.strip()
    parsed_url = urlsplit(event_url)
    if (
        parsed_url.scheme not in {"http", "https"}
        or (parsed_url.hostname or "").casefold() != "sports.caliente.mx"
    ):
        raise ValueError("link must point to sports.caliente.mx")

    event_path = parsed_url.path.rstrip("/")
    is_numbered_event = re.fullmatch(
        r"/es_MX/e/\d+/[^/]+",
        event_path,
        flags=re.IGNORECASE,
    )
    is_scheduled_event = re.fullmatch(
        r"/es_MX/[^/]+/\d{4}-\d{2}-\d{2}/[^/]+",
        event_path,
        flags=re.IGNORECASE,
    )
    if not (is_numbered_event or is_scheduled_event):
        raise ValueError("link must be a Caliente event link")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/138.0 Safari/537.36"
        ),
        "Accept-Language": "es-MX,es;q=0.9",
    }
    owned_session = session is None
    if owned_session:
        session = requests.Session()
    try:
        initial_response = session.get(event_url, headers=headers, timeout=30)
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

        response = session.get(event_url, headers=headers, timeout=30)
        response.raise_for_status()
        source = response.text
    finally:
        if owned_session:
            session.close()

    def clean(value):
        value = re.sub(r"<[^>]+>", " ", value)
        return " ".join(html_module.unescape(value).split())

    def key(value):
        value = unicodedata.normalize("NFKD", clean(value))
        value = "".join(
            character for character in value if not unicodedata.combining(character)
        )
        value = value.casefold()
        value = re.sub(r"\bmas\s+de\b", "over", value)
        value = re.sub(r"\bmenos\s+de\b", "under", value)
        value = " ".join(value.split())
        aliases = {
            "tijuana xolos de caliente": "tijuana",
            "guadalajara chivas": "chivas guadalajara",
            "atlas de guadalajara": "atlas",
        }
        for caliente_name, canonical_name in aliases.items():
            value = value.replace(caliente_name, canonical_name)
        return value

    performers = [
        clean(value)
        for value in re.findall(
            r'<meta\s+itemprop=["\']performer["\']\s+content=["\']([^"\']+)',
            source,
            flags=re.IGNORECASE,
        )
    ]
    if len(performers) < 2:
        raise ValueError("Could not find the home and away teams in the HTML file")
    home_team, away_team = performers[:2]

    match_name = f"{home_team}-vs-{away_team}"

    event_source_match = re.search(
        r'<div\s+class=["\'][^"\']*\bselections-for-event\b[^"\']*["\']',
        source,
        flags=re.IGNORECASE,
    )
    event_source = source[event_source_match.start():] if event_source_match else source

    markets = {}
    market_parts = re.split(
        r'(?=<div\s+class=["\']expander[^>]*\bmkt\b)',
        event_source,
        flags=re.IGNORECASE,
    )
    for part in market_parts:
        market_match = re.search(
            r'<span\s+class=["\']mkt-name["\'][^>]*>(.*?)</span>',
            part,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not market_match:
            continue
        market_name = key(market_match.group(1))
        selections = markets.setdefault(market_name, {})
        for button_match in re.finditer(
            r'<button\b(?=[^>]*\bname=["\']add-to-slip["\'])'
            r'(?P<attrs>[^>]*)>(?P<body>.*?)</button>',
            part,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            decimal_match = re.search(
                r'<span\s+class=["\']price dec["\'][^>]*>(.*?)</span>',
                button_match.group("body"),
                flags=re.IGNORECASE | re.DOTALL,
            )
            title_match = re.search(
                r'\btitle=["\']([^"\']*)["\']',
                button_match.group("attrs"),
                flags=re.IGNORECASE,
            )
            if not decimal_match or not title_match:
                continue
            title = key(title_match.group(1))
            try:
                price = float(clean(decimal_match.group(1)))
            except ValueError:
                continue
            selections.setdefault(title, price)

    def odd(market_name, selection_name):
        return markets.get(key(market_name), {}).get(key(selection_name), pd.NA)

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
        "Bookmarker": "Caliente",
        "HT": odd("Resultado Final (Tiempo Regular)", home_team),
        "DRAW": odd("Resultado Final (Tiempo Regular)", "Empate"),
        "AT": odd("Resultado Final (Tiempo Regular)", away_team),
    }

    for line in ("0.5", "1.5", "2.5", "3.5", "4.5"):
        values[f"O{line}"] = odd("Total Goles Over/Under", f"Over {line}")
        values[f"U{line}"] = odd("Total Goles Over/Under", f"Under {line}")

    values.update(
        {
            "DC_HT_DRAW": odd("Doble Oportunidad", f"{home_team}/Empate"),
            "DC_HT_AT": odd("Doble Oportunidad", f"{home_team}/{away_team}"),
            "DC_AT_DRAW": odd("Doble Oportunidad", f"{away_team}/Empate"),
            "BTTS_YES": odd("Ambos Equipos Anotan", "Sí"),
            "BTTS_NO": odd("Ambos Equipos Anotan", "No"),
        }
    )

    for line in ("0.5", "1.5", "2.5"):
        values[f"2H_O{line}"] = odd("2da Mitad - Over/Under", f"Over {line}")
        values[f"2H_U{line}"] = odd("2da Mitad - Over/Under", f"Under {line}")
    for line in ("0.5", "1.5", "2.5"):
        values[f"1H_O{line}"] = odd("1ra Mitad Total de Goles Over/Under", f"Over {line}")
        values[f"1H_U{line}"] = odd("1ra Mitad Total de Goles Over/Under", f"Under {line}")

    values["timestamp_utc"] = datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")

    return pd.Series(
        [values.get(column, pd.NA) for column in columns],
        index=[f"cal_{column}" for column in columns],
    )
