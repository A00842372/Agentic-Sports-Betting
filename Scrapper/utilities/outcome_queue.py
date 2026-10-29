"""Durable local delivery of run registrations and results to PostgreSQL."""

from contextlib import closing, contextmanager
import json
import os
from pathlib import Path
import sqlite3


class OutcomeQueue:
    def __init__(self, path=None):
        state_home = Path(os.getenv("XDG_STATE_HOME") or Path.home() / ".local" / "state")
        self.path = Path(path or os.getenv("SCRAPER_QUEUE_PATH") or
                         state_home / "agentic-sports-betting" / "outcomes.sqlite3")

    @contextmanager
    def _connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=30)) as connection:
            connection.execute("PRAGMA synchronous=EXTRA")
            with connection:
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS pending_collections (
                        id TEXT PRIMARY KEY,
                        payload TEXT NOT NULL
                    )
                """)
                yield connection

    def enqueue(self, collection):
        """Commit an immutable JSON payload before attempting remote delivery."""
        payload = json.dumps(collection, allow_nan=False, sort_keys=True)
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO pending_collections (id, payload) VALUES (?, ?)",
                (collection["id"], payload),
            )

    def pending(self):
        """Read queued registrations/results without changing delivery state."""
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM pending_collections ORDER BY rowid"
            ).fetchall()
        return [json.loads(payload) for (payload,) in rows]

    def replay(self, write_collection):
        """Acknowledge each payload only after its remote transaction commits.

        A crash between remote commit and acknowledgement can deliver the same
        payload again. The writer must be idempotent by original run/attempt ID.
        """
        delivered = 0
        for collection in self.pending():
            write_collection(collection)
            with self._connection() as connection:
                connection.execute(
                    "DELETE FROM pending_collections WHERE id = ?", (collection["id"],),
                )
            delivered += 1
        return delivered
