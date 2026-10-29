"""Read-only, match-ID-based PostgreSQL history for model inputs."""

from contextlib import contextmanager
import os
from uuid import UUID

import pandas as pd


_BOOKMAKERS = ("caliente", "pinnacle", "playdoit")
_STATUSES = ("ok", "partial", "failed", "missing_link", "missed", "incomplete")
_TIME_COLUMNS = (
    "scheduled_time", "kickoff", "started_at", "completed_at", "attempted_at",
    "source_timestamp", "detected_at", "history_time",
)
_HISTORY_SQL = """
    WITH match_slots AS (
        SELECT s.*, m.display_name AS match_name
        FROM scheduled_slots s JOIN matches m ON m.id = s.match_id
        WHERE s.match_id = %(match_id)s
    ), history AS (
        SELECT s.match_id, s.match_name, s.id AS slot_id, s.scheduled_time, s.kickoff,
               r.id AS run_id, r.started_at, r.completed_at,
               o.id AS outcome_id, o.bookmaker, o.attempt_number, o.attempted_at,
               o.source_timestamp, o.source_name, o.source_url,
               CASE WHEN o.id IS NULL THEN 'incomplete' ELSE o.status END AS status,
               o.error, COALESCE(o.missing_fields, ARRAY[]::TEXT[]) AS missing_fields,
               d.field, d.value, NULL::TIMESTAMPTZ AS detected_at,
               COALESCE(o.attempted_at, r.started_at) AS history_time
        FROM match_slots s JOIN scraper_runs r ON r.slot_id = s.id
        LEFT JOIN bookmaker_outcomes o ON o.run_id = r.id
        LEFT JOIN outcome_odds d ON d.outcome_id = o.id
        UNION ALL
        SELECT s.match_id, s.match_name, s.id, s.scheduled_time, s.kickoff,
               NULL::UUID, NULL::TIMESTAMPTZ, NULL::TIMESTAMPTZ,
               NULL::UUID, NULL::TEXT, NULL::INTEGER, NULL::TIMESTAMPTZ,
               NULL::TIMESTAMPTZ, NULL::TEXT, NULL::TEXT, 'missed', NULL::TEXT,
               ARRAY[]::TEXT[], NULL::TEXT, NULL::NUMERIC, m.detected_at,
               s.scheduled_time
        FROM match_slots s JOIN missed_slots m ON m.slot_id = s.id
    )
    SELECT * FROM history
    WHERE (%(bookmaker)s::TEXT IS NULL OR bookmaker = %(bookmaker)s)
      AND (%(status)s::TEXT IS NULL OR status = %(status)s)
      AND (%(start_time)s::TIMESTAMPTZ IS NULL OR history_time >= %(start_time)s)
      AND (%(end_time)s::TIMESTAMPTZ IS NULL OR history_time < %(end_time)s)
    ORDER BY history_time, scheduled_time, slot_id, run_id, bookmaker,
             attempt_number, outcome_id, field
"""


@contextmanager
def connect_history(database_url=None):
    """Open model credentials with read-only transactions and close on exit."""
    database_url = database_url or os.getenv("MODEL_DATABASE_URL")
    if not database_url:
        raise RuntimeError("Set MODEL_DATABASE_URL to the model reader's PostgreSQL connection")
    import psycopg

    with psycopg.connect(database_url) as connection:
        connection.read_only = True
        yield connection


def _utc_bound(value):
    if value is None:
        return None
    try:
        timestamp = pd.Timestamp(value)
        if pd.isna(timestamp):
            raise ValueError("Time bounds must be valid timestamps")
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("UTC")
        return timestamp.tz_convert("UTC").to_pydatetime()
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("Time bounds must be valid timestamps") from error


def read_match_history(match_id, *, bookmaker=None, status=None,
                       start_time=None, end_time=None, database_url=None):
    """Return all matching attempts/odds and gaps, in actual observation order.

    Time bounds are inclusive start/exclusive end. Missed slots use intended
    scheduled time and incomplete runs use their actual start time instead.
    Decimal odds are retained; no records are deduplicated or forward filled.
    """
    match_id = match_id if isinstance(match_id, UUID) else UUID(str(match_id))
    if bookmaker is not None and bookmaker not in _BOOKMAKERS:
        raise ValueError("bookmaker must be caliente, pinnacle, or playdoit")
    if status is not None and status not in _STATUSES:
        raise ValueError("Unknown history status")
    start_time, end_time = _utc_bound(start_time), _utc_bound(end_time)
    if start_time is not None and end_time is not None and start_time >= end_time:
        raise ValueError("start_time must be before end_time")
    parameters = {
        "match_id": match_id, "bookmaker": bookmaker, "status": status,
        "start_time": start_time, "end_time": end_time,
    }
    with connect_history(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(_HISTORY_SQL, parameters)
            dataframe = pd.DataFrame(cursor.fetchall(), columns=[column.name for column in cursor.description])
    for column in _TIME_COLUMNS:
        dataframe[column] = pd.to_datetime(dataframe[column], utc=True)
    dataframe["attempt_number"] = pd.array(dataframe["attempt_number"], dtype="Int64")
    return dataframe
