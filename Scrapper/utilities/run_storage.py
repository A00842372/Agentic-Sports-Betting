"""Typed bookmaker outcomes and durable identities for launched scraper runs."""

from decimal import Decimal, InvalidOperation
from uuid import uuid4

import pandas as pd

from utilities.scheduled_work import LINK_COLUMNS, utc_timestamp


BOOKMAKER_NAMES = {"cal": "caliente", "pn": "pinnacle", "pd": "playdoit"}
ODDS_FIELDS = tuple((
    "HT DRAW AT O0.5 U0.5 O1.5 U1.5 O2.5 U2.5 O3.5 U3.5 O4.5 U4.5 "
    "DC_HT_DRAW DC_HT_AT DC_AT_DRAW BTTS_YES BTTS_NO "
    "1H_O0.5 1H_U0.5 1H_O1.5 1H_U1.5 1H_O2.5 1H_U2.5 "
    "2H_O0.5 2H_U0.5 2H_O1.5 2H_U1.5 2H_O2.5 2H_U2.5"
).split())


def normalize_reading(prefix, value):
    """Convert an existing scraper Series into queryable decimal odds."""
    if not isinstance(value, pd.Series):
        raise TypeError("scraper must return a pandas Series")
    odds = {}
    for field in ODDS_FIELDS:
        price = value.get(f"{prefix}_{field}")
        try:
            number = None if pd.isna(price) else Decimal(str(price))
        except (InvalidOperation, ValueError):
            number = None
        odds[field] = number if number is not None and number.is_finite() else None
    missing_fields = [field for field, price in odds.items() if price is None]
    source_timestamp = value.get(f"{prefix}_timestamp_utc")
    errors = ["Missing odds: " + ", ".join(missing_fields)] if missing_fields else []
    try:
        source_timestamp = None if pd.isna(source_timestamp) else utc_timestamp(source_timestamp)
    except (TypeError, ValueError):
        source_timestamp = None
        errors.append("Invalid source timestamp")
    source_name = value.get(f"{prefix}_match")
    return {
        "odds": odds,
        "missing_fields": missing_fields,
        "source_name": None if pd.isna(source_name) else str(source_name),
        "source_timestamp": source_timestamp,
        "status": "partial" if missing_fields else "ok",
        "error": "; ".join(errors) or None,
    }


def _create_run_tables(connection):
    connection.execute("SELECT pg_advisory_xact_lock(756249103)")
    connection.execute("""
        CREATE TABLE IF NOT EXISTS scraper_runs (
            id UUID PRIMARY KEY,
            slot_id UUID NOT NULL REFERENCES scheduled_slots(id),
            started_at TIMESTAMPTZ NOT NULL,
            completed_at TIMESTAMPTZ
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS bookmaker_outcomes (
            id UUID PRIMARY KEY,
            run_id UUID NOT NULL REFERENCES scraper_runs(id),
            bookmaker TEXT NOT NULL CHECK (bookmaker IN ('caliente', 'pinnacle', 'playdoit')),
            attempted_at TIMESTAMPTZ NOT NULL,
            source_timestamp TIMESTAMPTZ,
            source_name TEXT,
            source_url TEXT,
            status TEXT NOT NULL CHECK (status IN ('ok', 'partial', 'failed', 'missing_link')),
            error TEXT,
            missing_fields TEXT[] NOT NULL
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS outcome_odds (
            outcome_id UUID NOT NULL REFERENCES bookmaker_outcomes(id),
            field TEXT NOT NULL,
            value NUMERIC,
            PRIMARY KEY (outcome_id, field)
        )
    """)
    # Existing final outcomes from ticket #4 are each attempt 1 of their run.
    connection.execute("""
        ALTER TABLE bookmaker_outcomes
        ADD COLUMN IF NOT EXISTS attempt_number INTEGER NOT NULL DEFAULT 1
            CHECK (attempt_number > 0)
    """)
    connection.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS bookmaker_outcomes_attempt_idx
        ON bookmaker_outcomes(run_id, bookmaker, attempt_number)
    """)
    connection.execute("CREATE INDEX IF NOT EXISTS scraper_runs_slot_idx ON scraper_runs(slot_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS bookmaker_outcomes_run_idx ON bookmaker_outcomes(run_id)")


def start_runs(connection, scheduled_links):
    """Commit one distinct run per selected slot before starting bookmaker IO."""
    runs = scheduled_links.copy()
    runs["run_id"] = [uuid4() for _ in range(len(runs))]
    runs["started_at"] = [utc_timestamp() for _ in range(len(runs))]
    with connection.transaction():
        _create_run_tables(connection)
        with connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO scraper_runs (id, slot_id, started_at) VALUES (%s, %s, %s)",
                [(row["run_id"], row["slot_id"], row["started_at"].to_pydatetime())
                 for _, row in runs.iterrows()],
            )
    return runs


def reconcile_missed_slots(connection, run_time=None):
    """Record elapsed, uncancelled slots with no launched run.

    The current UTC minute is still eligible for collection. Missed slots retain
    their intended time through scheduled_slots and never create observations.
    """
    minute = utc_timestamp(run_time).floor("min")
    with connection.transaction():
        _create_run_tables(connection)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS missed_slots (
                slot_id UUID PRIMARY KEY REFERENCES scheduled_slots(id),
                detected_at TIMESTAMPTZ NOT NULL
            )
        """)
        result = connection.execute("""
            INSERT INTO missed_slots (slot_id, detected_at)
            SELECT s.id, %s
            FROM scheduled_slots s
            WHERE s.scheduled_time < %s
              AND s.cancelled_at IS NULL
              AND NOT EXISTS (SELECT 1 FROM scraper_runs r WHERE r.slot_id = s.id)
            ON CONFLICT (slot_id) DO NOTHING
        """, (utc_timestamp().to_pydatetime(), minute.to_pydatetime()))
    return result.rowcount


def _store_attempt(connection, run, bookmaker, result):
    url = run[LINK_COLUMNS[bookmaker]]
    source_timestamp = result.get("source_timestamp")
    connection.execute("""
        INSERT INTO bookmaker_outcomes
            (id, run_id, bookmaker, attempt_number, attempted_at, source_timestamp,
             source_name, source_url, status, error, missing_fields)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        result["id"], run["run_id"], bookmaker, result["attempt_number"],
        result["attempted_at"].to_pydatetime(),
        None if source_timestamp is None else source_timestamp.to_pydatetime(),
        result.get("source_name"), None if pd.isna(url) else str(url),
        result["status"], result["error"] or None,
        result.get("missing_fields", list(ODDS_FIELDS)),
    ))
    odds = result.get("odds", dict.fromkeys(ODDS_FIELDS))
    with connection.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO outcome_odds (outcome_id, field, value) VALUES (%s, %s, %s)",
            [(result["id"], field, odds[field]) for field in ODDS_FIELDS],
        )


def store_outcomes(connection, runs, batch_results):
    """Commit every bookmaker attempt and completion timestamps together.

    Every existing odds field has a numeric row, including explicit SQL NULLs
    for failures and missing links. No comparison to previous odds is performed.
    """
    with connection.transaction():
        for row_index, run in runs.iterrows():
            for prefix, bookmaker in BOOKMAKER_NAMES.items():
                result = batch_results[prefix][row_index]
                for attempt in result["attempts"]:
                    _store_attempt(connection, run, bookmaker, attempt)
        completed_at = utc_timestamp().to_pydatetime()
        with connection.cursor() as cursor:
            cursor.executemany(
                "UPDATE scraper_runs SET completed_at = %s WHERE id = %s",
                [(completed_at, run_id) for run_id in runs["run_id"]],
            )
