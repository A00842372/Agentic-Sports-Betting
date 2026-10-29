"""Persist scrape opportunities and select current links by stable match ID."""

from uuid import uuid4

import pandas as pd

from utilities.schedule import schedule


LINK_COLUMNS = {"caliente": "Caliente link", "pinnacle": "Pinnacle link",
                "playdoit": "Playdoit link"}
DUE_COLUMNS = ["slot_id", "match_id", "scheduled_time", "match", "start_time",
               *LINK_COLUMNS.values()]


def utc_timestamp(value=None):
    timestamp = pd.Timestamp.now(tz="UTC") if value is None else pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError("Time must be a valid UTC timestamp")
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def refresh_scheduled_slots(connection, now=None):
    """Refresh future slots inside the caller's discovery transaction.

    Keep elapsed slots and the identity of unchanged future slots. Superseded
    future slots remain stored as cancelled so future run references stay valid.
    """
    now = utc_timestamp(now)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_slots (
            id UUID PRIMARY KEY,
            match_id UUID NOT NULL REFERENCES matches(id),
            scheduled_time TIMESTAMPTZ NOT NULL,
            kickoff TIMESTAMPTZ NOT NULL,
            cancelled_at TIMESTAMPTZ,
            UNIQUE (match_id, scheduled_time, kickoff)
        )
    """)
    connection.execute(
        "CREATE INDEX IF NOT EXISTS scheduled_slots_due_idx "
        "ON scheduled_slots(scheduled_time) WHERE cancelled_at IS NULL"
    )
    rows = connection.execute(
        "SELECT id, kickoff FROM matches WHERE kickoff > %s", (now.to_pydatetime(),)
    ).fetchall()
    matches = pd.DataFrame(rows, columns=["match", "start_time"])
    slots = schedule(matches, now=now)
    connection.execute(
        "UPDATE scheduled_slots SET cancelled_at = %s "
        "WHERE scheduled_time > %s AND cancelled_at IS NULL",
        (now.to_pydatetime(), now.to_pydatetime()),
    )
    with connection.cursor() as cursor:
        cursor.executemany("""
            INSERT INTO scheduled_slots (id, match_id, scheduled_time, kickoff)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (match_id, scheduled_time, kickoff)
            DO UPDATE SET cancelled_at = NULL
        """, [
            (uuid4(), row.match, row.scheduled_time.to_pydatetime(),
             row.start_time.to_pydatetime())
            for row in slots.itertuples(index=False)
        ])


def select_due_work(connection, run_time=None):
    """Return active slots in one UTC minute with the current source URLs.

    Never read CSV inputs or replay slots from earlier minutes. Missing links
    remain null for the existing scraper's missing-link handling.
    """
    minute = utc_timestamp(run_time).floor("min")
    rows = connection.execute("""
        SELECT s.id, m.id, s.scheduled_time, m.display_name, m.kickoff,
               l.bookmaker, l.source_url
        FROM scheduled_slots s
        JOIN matches m ON m.id = s.match_id
        LEFT JOIN bookmaker_listings l ON l.match_id = m.id
        WHERE s.cancelled_at IS NULL
          AND s.kickoff = m.kickoff
          AND s.scheduled_time >= %s AND s.scheduled_time < %s
        ORDER BY s.scheduled_time, s.id, l.bookmaker
    """, (minute.to_pydatetime(), (minute + pd.Timedelta(minutes=1)).to_pydatetime())).fetchall()
    slots = {}
    for slot_id, match_id, scheduled_time, name, kickoff, bookmaker, url in rows:
        slot = slots.setdefault(slot_id, dict.fromkeys(DUE_COLUMNS))
        slot.update(slot_id=slot_id, match_id=match_id, scheduled_time=scheduled_time,
                    match=name, start_time=kickoff)
        if bookmaker in LINK_COLUMNS:
            slot[LINK_COLUMNS[bookmaker]] = url
    return pd.DataFrame(slots.values(), columns=DUE_COLUMNS)
