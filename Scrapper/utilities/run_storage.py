"""Typed bookmaker outcomes and durable identities for launched scraper runs."""

from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid4

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
    connection.execute("""
        CREATE TABLE IF NOT EXISTS missed_slots (
            slot_id UUID PRIMARY KEY REFERENCES scheduled_slots(id),
            detected_at TIMESTAMPTZ NOT NULL
        )
    """)


def prepare_runs(scheduled_links):
    """Assign each selected slot a stable identity before remote registration."""
    runs = scheduled_links.copy()
    runs["run_id"] = [uuid4() for _ in range(len(runs))]
    runs["started_at"] = [utc_timestamp() for _ in range(len(runs))]
    return runs


def start_runs(connection, runs):
    """Register prepared runs before bookmaker IO, reusing their original IDs."""
    with connection.transaction():
        _create_run_tables(connection)
        with connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO scraper_runs (id, slot_id, started_at) VALUES (%s, %s, %s) "
                "ON CONFLICT (id) DO NOTHING",
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


def prepare_collection(runs, batch_results=None):
    """Freeze registration or completed results in a JSON-safe collection."""
    completed_at = None if batch_results is None else utc_timestamp().isoformat()
    collection = {"version": 1, "id": str(uuid4()), "runs": []}
    for row_index, run in runs.iterrows():
        record = {
            "id": str(run["run_id"]), "slot_id": str(run["slot_id"]),
            "started_at": run["started_at"].isoformat(),
            "completed_at": completed_at, "outcomes": [],
        }
        collection["runs"].append(record)
        if batch_results is None:
            continue
        for prefix, bookmaker in BOOKMAKER_NAMES.items():
            url = run[LINK_COLUMNS[bookmaker]]
            for result in batch_results[prefix][row_index]["attempts"]:
                source_timestamp = result.get("source_timestamp")
                odds = result.get("odds", dict.fromkeys(ODDS_FIELDS))
                record["outcomes"].append({
                    "id": str(result["id"]), "bookmaker": bookmaker,
                    "attempt_number": result["attempt_number"],
                    "attempted_at": result["attempted_at"].isoformat(),
                    "source_timestamp": None if source_timestamp is None else source_timestamp.isoformat(),
                    "source_name": result.get("source_name"),
                    "source_url": None if pd.isna(url) else str(url),
                    "status": result["status"], "error": result["error"] or None,
                    "missing_fields": result.get("missing_fields", list(ODDS_FIELDS)),
                    "odds": {field: None if odds[field] is None else str(odds[field])
                             for field in ODDS_FIELDS},
                })
    return collection


def _store_attempt(connection, run_id, result):
    source_timestamp = result.get("source_timestamp")
    connection.execute("""
        INSERT INTO bookmaker_outcomes
            (id, run_id, bookmaker, attempt_number, attempted_at, source_timestamp,
             source_name, source_url, status, error, missing_fields)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO NOTHING
    """, (
        UUID(result["id"]), UUID(run_id), result["bookmaker"], result["attempt_number"],
        utc_timestamp(result["attempted_at"]).to_pydatetime(),
        None if source_timestamp is None else utc_timestamp(source_timestamp).to_pydatetime(),
        result["source_name"], result["source_url"],
        result["status"], result["error"] or None,
        result.get("missing_fields", list(ODDS_FIELDS)),
    ))
    odds = result["odds"]
    with connection.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO outcome_odds (outcome_id, field, value) VALUES (%s, %s, %s) "
            "ON CONFLICT (outcome_id, field) DO NOTHING",
            [(UUID(result["id"]), field, None if odds[field] is None else Decimal(odds[field]))
             for field in ODDS_FIELDS],
        )


def store_collection(connection, collection):
    """Commit one frozen collection; replay by original IDs is idempotent."""
    if collection["version"] != 1:
        raise ValueError("Unsupported queued collection version")
    with connection.transaction():
        _create_run_tables(connection)
        for run in collection["runs"]:
            connection.execute(
                "INSERT INTO scraper_runs (id, slot_id, started_at) VALUES (%s, %s, %s) "
                "ON CONFLICT (id) DO NOTHING",
                (UUID(run["id"]), UUID(run["slot_id"]), utc_timestamp(run["started_at"]).to_pydatetime()),
            )
            for result in run["outcomes"]:
                _store_attempt(connection, run["id"], result)
            # An offline launch may have been classified as missed before its
            # registration reached PostgreSQL. Keep attempted slots distinct.
            connection.execute("DELETE FROM missed_slots WHERE slot_id = %s",
                               (UUID(run["slot_id"]),))
            if run["completed_at"] is not None:
                connection.execute(
                    "UPDATE scraper_runs SET completed_at = COALESCE(completed_at, %s) WHERE id = %s",
                    (utc_timestamp(run["completed_at"]).to_pydatetime(), UUID(run["id"])),
                )
