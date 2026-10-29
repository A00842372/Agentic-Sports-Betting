import re
import unicodedata
import os
from difflib import SequenceMatcher
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pandas as pd

from utilities.caliente_links import caliente_links
from utilities.pinnacle_links import pinnacle_links
from utilities.playdoit_links import playdoit_links
from utilities.scheduled_work import refresh_scheduled_slots


def _normalize_team(team):
    team = unicodedata.normalize("NFKD", str(team))
    team = "".join(
        character
        for character in team
        if not unicodedata.combining(character)
    )
    return " ".join(re.findall(r"[a-z0-9]+", team.casefold()))


def _split_match(match):
    home_team, separator, away_team = str(match).partition("-vs-")
    if not separator:
        raise ValueError(f"Invalid match format: {match}")
    return _normalize_team(home_team), _normalize_team(away_team)


def _team_similarity(left_team, right_team):
    left_tokens = set(left_team.split())
    right_tokens = set(right_team.split())
    if not left_tokens or not right_tokens:
        return 0.0

    shared_tokens = left_tokens & right_tokens
    containment_score = len(shared_tokens) / min(
        len(left_tokens), len(right_tokens)
    )
    sequence_score = SequenceMatcher(None, left_team, right_team).ratio()
    sorted_token_score = SequenceMatcher(
        None,
        " ".join(sorted(left_tokens)),
        " ".join(sorted(right_tokens)),
    ).ratio()
    return 100 * max(containment_score, sequence_score, sorted_token_score)


def match_similarity(left_match, right_match):
    """Return a 0-100 similarity score while preserving home/away order."""
    left_home, left_away = _split_match(left_match)
    right_home, right_away = _split_match(right_match)
    return min(
        _team_similarity(left_home, right_home),
        _team_similarity(left_away, right_away),
    )


def add_bookmaker_links(
    base,
    bookmaker,
    link_column,
    tolerance=pd.Timedelta(minutes=5),
    minimum_similarity=85,
    ambiguity_margin=10,
):
    """Attach one-to-one bookmaker links using kickoff time and name similarity."""
    result = base.reset_index(drop=True).copy()
    available = bookmaker.reset_index(drop=True).copy()

    required_base_columns = {"match", "start_time"}
    required_bookmaker_columns = required_base_columns | {link_column}
    if not required_base_columns.issubset(result.columns):
        raise ValueError("base must contain match and start_time columns")
    if not required_bookmaker_columns.issubset(available.columns):
        raise ValueError(
            f"bookmaker must contain match, start_time, and {link_column} columns"
        )

    result["start_time"] = pd.to_datetime(
        result["start_time"], errors="coerce", utc=True
    )
    available["start_time"] = pd.to_datetime(
        available["start_time"], errors="coerce", utc=True
    )
    result[link_column] = pd.NA

    for result_index, base_match in result.iterrows():
        time_differences = (
            available["start_time"] - base_match["start_time"]
        ).abs()
        candidates = available[time_differences <= tolerance]
        if candidates.empty:
            continue

        scores = candidates["match"].map(
            lambda candidate: match_similarity(base_match["match"], candidate)
        ).sort_values(ascending=False)
        best_score = scores.iloc[0]
        second_best_score = scores.iloc[1] if len(scores) > 1 else None
        if best_score < minimum_similarity or (
            second_best_score is not None
            and best_score - second_best_score < ambiguity_margin
        ):
            continue
        best_index = scores.index[0]

        result.at[result_index, link_column] = available.at[
            best_index, link_column
        ]
        available = available.drop(index=best_index)

    return result


def _source_key(bookmaker, url):
    """Keep a bookmaker event's identity when its URL slug changes."""
    parsed = urlsplit(url)
    if bookmaker == "caliente":
        event = re.search(r"/e/(\d+)(?:/|$)", parsed.path)
    elif bookmaker == "pinnacle":
        event = re.search(r"/(\d+)/?$", parsed.path)
    elif bookmaker == "playdoit":
        parameters = parse_qs(parsed.fragment, keep_blank_values=True)
        ids = parameters.get("eventId", [])
        event = re.fullmatch(r"(\d+)", ids[0]) if ids else None
    else:
        raise ValueError(f"Unknown bookmaker: {bookmaker}")
    return event.group(1) if event else url


def _create_discovery_tables(connection):
    connection.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            id UUID PRIMARY KEY,
            display_name TEXT NOT NULL,
            kickoff TIMESTAMPTZ,
            review_reason TEXT,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS bookmaker_listings (
            bookmaker TEXT NOT NULL CHECK (bookmaker IN ('caliente', 'pinnacle', 'playdoit')),
            source_key TEXT NOT NULL,
            match_id UUID NOT NULL REFERENCES matches(id),
            source_name TEXT NOT NULL,
            source_kickoff TIMESTAMPTZ,
            source_url TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (bookmaker, source_key)
        )
    """)
    connection.execute(
        "CREATE INDEX IF NOT EXISTS bookmaker_listings_match_id_idx "
        "ON bookmaker_listings(match_id)"
    )


def persist_listings(connection, listings, tolerance=pd.Timedelta(minutes=5),
                     minimum_similarity=85, ambiguity_margin=10, now=None):
    """Reconcile source listings and save current evidence in one transaction.

    A source event ID takes precedence over names and kickoff during rediscovery.
    New cross-bookmaker links require name similarity even with one time candidate.
    """
    with connection.transaction():
        # Discovery writes are serialized across simultaneous processes.
        connection.execute("SELECT pg_advisory_xact_lock(756249102)")
        _create_discovery_tables(connection)
        match_rows = connection.execute(
            "SELECT id, display_name, kickoff, review_reason FROM matches"
        ).fetchall()
        matches = {
            row[0]: {"name": row[1], "kickoff": pd.Timestamp(row[2]),
                     "review_reason": row[3], "bookmakers": set()}
            for row in match_rows
        }
        source_rows = connection.execute(
            "SELECT bookmaker, source_key, match_id FROM bookmaker_listings"
        ).fetchall()
        known_sources = {}
        for bookmaker, source_key, match_id in source_rows:
            known_sources[(bookmaker, source_key)] = match_id
            matches[match_id]["bookmakers"].add(bookmaker)

        for listing in listings:
            bookmaker = listing["bookmaker"]
            name = str(listing["match"]).strip()
            url = str(listing["url"]).strip()
            kickoff = pd.Timestamp(listing["start_time"])
            if not name or not url:
                raise ValueError("Listing needs a name and URL")
            if pd.isna(kickoff):
                kickoff_value = None
            elif kickoff.tzinfo is None:
                kickoff = kickoff.tz_localize("UTC")
                kickoff_value = kickoff.to_pydatetime()
            else:
                kickoff = kickoff.tz_convert("UTC")
                kickoff_value = kickoff.to_pydatetime()
            key = _source_key(bookmaker, url)
            source = (bookmaker, key)
            match_id = known_sources.get(source)
            if match_id is None:
                candidates = []
                same_bookmaker_candidate = False
                for candidate_id, candidate in matches.items():
                    if pd.isna(kickoff) or pd.isna(candidate["kickoff"]):
                        continue
                    if abs(candidate["kickoff"] - kickoff) > tolerance:
                        continue
                    score = match_similarity(name, candidate["name"])
                    if bookmaker in candidate["bookmakers"]:
                        if score >= minimum_similarity:
                            same_bookmaker_candidate = True
                        continue
                    candidates.append((score, candidate_id))
                candidates.sort(reverse=True)
                if pd.isna(kickoff):
                    review_reason = "missing_kickoff"
                elif same_bookmaker_candidate:
                    review_reason = "source_identity_changed"
                elif not candidates:
                    review_reason = None
                elif candidates[0][0] < minimum_similarity:
                    review_reason = "low_name_similarity"
                elif (len(candidates) > 1 and
                      candidates[0][0] - candidates[1][0] < ambiguity_margin):
                    review_reason = "ambiguous_candidates"
                else:
                    review_reason = None
                    match_id = candidates[0][1]
                if match_id is None:
                    match_id = uuid4()
                    connection.execute(
                        "INSERT INTO matches (id, display_name, kickoff, review_reason) "
                        "VALUES (%s, %s, %s, %s)",
                        (match_id, name, kickoff_value, review_reason),
                    )
                    matches[match_id] = {
                        "name": name, "kickoff": kickoff,
                        "review_reason": review_reason, "bookmakers": set(),
                    }
                known_sources[source] = match_id

            connection.execute("""
                INSERT INTO bookmaker_listings
                    (bookmaker, source_key, match_id, source_name,
                     source_kickoff, source_url)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (bookmaker, source_key) DO UPDATE SET
                    source_name = EXCLUDED.source_name,
                    source_kickoff = EXCLUDED.source_kickoff,
                    source_url = EXCLUDED.source_url,
                    updated_at = now()
            """, (bookmaker, key, match_id, name, kickoff_value, url))
            matches[match_id]["bookmakers"].add(bookmaker)
            # Prefer the Caliente listing as the current display anchor.
            if kickoff_value is not None and (
                bookmaker == "caliente" or len(matches[match_id]["bookmakers"]) == 1
            ):
                connection.execute(
                    "UPDATE matches SET display_name = %s, kickoff = %s, "
                    "updated_at = now() WHERE id = %s",
                    (name, kickoff_value, match_id),
                )
                matches[match_id]["name"] = name
                matches[match_id]["kickoff"] = kickoff

        refresh_scheduled_slots(connection, now=now)

    return len(listings)


pinnacle_urls = [
    "https://www.pinnacle.com/es/soccer/germany-bundesliga/matchups/#all",
    "https://www.pinnacle.com/es/soccer/spain-la-liga/matchups/#all",
    "https://www.pinnacle.com/es/soccer/france-ligue-1/matchups/#all",
    "https://www.pinnacle.com/es/soccer/england-premier-league/matchups/#all",
    "https://www.pinnacle.com/es/soccer/italy-serie-a/matchups/#all",
    "https://www.pinnacle.com/es/soccer/brazil-serie-a/matchups/#all",
    "https://www.pinnacle.com/es/soccer/mexico-liga-mx/matchups/#all",
]
caliente_urls = [
    "https://sports.caliente.mx/es_MX/Bundesliga-1",
    "https://sports.caliente.mx/es_MX/La-Liga",
    "https://sports.caliente.mx/es_MX/Ligue-1",
    "https://sports.caliente.mx/es_MX/Premier-League",
    "https://sports.caliente.mx/es_MX/Serie-A",
    "https://sports.caliente.mx/es_MX/t/2400790/Brasil-Serie-A",
    "https://sports.caliente.mx/es_MX/Liga-MX",
]
playdoit_urls = [
    "https://www.playdoit.mx/#page=championship&championshipIds=2950&periodType=0",
    "https://www.playdoit.mx/#page=championship&championshipIds=2941&periodType=0",
    "https://www.playdoit.mx/#page=championship&championshipIds=2943&periodType=0",
    "https://www.playdoit.mx/#page=championship&championshipIds=2936&periodType=0",
    "https://www.playdoit.mx/#page=championship&championshipIds=2942&periodType=0",
    "https://www.playdoit.mx/#page=championship&championshipIds=11318",
    "https://www.playdoit.mx/#page=championship&championshipIds=10009",
]

def run_discovery(database_url=None, now=None):
    """Collect listings and atomically persist current evidence and future slots."""
    database_url = database_url or os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("Set DATABASE_URL for PostgreSQL discovery storage")

    import psycopg

    source_listings = []
    for index in range(len(caliente_urls)):
        caliente = caliente_links(caliente_urls[index])
        pinnacle = pinnacle_links(pinnacle_urls[index])
        playdoit = playdoit_links(playdoit_urls[index])
        for bookmaker, frame, column in (
            ("caliente", caliente, "Caliente link"),
            ("pinnacle", pinnacle, "Pinnacle link"),
            ("playdoit", playdoit, "Playdoit link"),
        ):
            for _, row in frame.iterrows():
                if pd.notna(row[column]):
                    source_listings.append({
                        "bookmaker": bookmaker,
                        "match": row["match"],
                        "start_time": row["start_time"],
                        "url": row[column],
                    })

    with psycopg.connect(database_url) as connection:
        persist_listings(connection, source_listings, now=now)

    return len(source_listings)


if __name__ == "__main__":
    run_discovery()
