"""Discovery-to-due-work checks with controlled time and isolated PostgreSQL."""

import os
import unittest
from uuid import uuid4

import pandas as pd

from test_discovery_storage import listing
from match_discovery import persist_listings
from utilities.scheduled_work import select_due_work
from utilities.schedule import schedule


class ScheduleCadenceTests(unittest.TestCase):
    def test_existing_cadence_at_each_spacing_boundary(self):
        kickoff = pd.Timestamp("2026-11-04T12:00:00Z")
        slots = schedule(pd.DataFrame([{"match": "Atlas-vs-Leon", "start_time": kickoff}]),
                         now="2026-11-01T12:00:00Z")
        offsets = set((kickoff - slots["scheduled_time"]).dt.total_seconds() / 60)
        for offset in (1, 14, 15, 20, 115, 120, 150, 690, 720, 780,
                       1380, 1440, 1560, 2760, 2880, 3120, 4320):
            with self.subTest(expected_offset=offset):
                self.assertIn(offset, offsets)
        for offset in (0, 16, 119, 121, 719, 721, 1439, 1441, 2879, 2881):
            with self.subTest(absent_offset=offset):
                self.assertNotIn(offset, offsets)


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL is required")
class ScheduledWorkTests(unittest.TestCase):
    def setUp(self):
        import psycopg

        self.schema = "schedule_test_" + uuid4().hex
        self.admin = psycopg.connect(os.environ["TEST_DATABASE_URL"], autocommit=True)
        self.admin.execute(f'CREATE SCHEMA "{self.schema}"')
        self.connection = psycopg.connect(
            os.environ["TEST_DATABASE_URL"], options=f"-c search_path={self.schema}",
        )

    def tearDown(self):
        self.connection.close()
        self.admin.execute(f'DROP SCHEMA "{self.schema}" CASCADE')
        self.admin.close()

    def test_discovery_makes_all_current_links_due_by_stable_match_id(self):
        kickoff = "2026-11-01T18:00:00Z"
        persist_listings(self.connection, [
            listing("caliente", "Atlas-vs-Leon", kickoff, 101),
            listing("pinnacle", "Atlas-vs-León", kickoff, 202),
            listing("playdoit", "Atlas-vs-Leon", kickoff, 303),
        ], now="2026-11-01T17:40:00Z")

        due = select_due_work(self.connection, "2026-11-01T17:45:30Z")

        self.assertEqual(1, len(due))
        row = due.iloc[0]
        self.assertEqual("Atlas-vs-Leon", row["match"])
        self.assertTrue(row["match_id"])
        self.assertTrue(row["slot_id"])
        self.assertEqual(pd.Timestamp("2026-11-01T17:45:00Z"), row["scheduled_time"])
        for bookmaker, column, event_id in (
            ("caliente", "Caliente link", 101),
            ("pinnacle", "Pinnacle link", 202),
            ("playdoit", "Playdoit link", 303),
        ):
            self.assertEqual(listing(bookmaker, "", kickoff, event_id)["url"], row[column])
        self.assertTrue(select_due_work(self.connection, "2026-11-01T17:44:00Z").empty)

    def test_rescheduling_replaces_future_work_and_preserves_elapsed_slots(self):
        persist_listings(self.connection, [
            listing("caliente", "Atlas-vs-Leon", "2026-11-01T18:00:00Z", 101),
        ], now="2026-11-01T17:40:00Z")
        before = select_due_work(self.connection, "2026-11-01T17:45:00Z").iloc[0]
        history = self.connection.execute(
            "SELECT id, scheduled_time, kickoff, cancelled_at FROM scheduled_slots "
            "WHERE scheduled_time <= '2026-11-01T17:46:00Z' ORDER BY scheduled_time"
        ).fetchall()
        changed = listing("caliente", "Atlas FC-vs-Club Leon", "2026-11-01T19:00:00Z", 101)
        changed["url"] = "https://sports.caliente.mx/es_MX/e/101/updated-name"
        persist_listings(self.connection, [changed], now="2026-11-01T17:46:00Z")

        self.assertTrue(select_due_work(self.connection, "2026-11-01T17:47:00Z").empty)
        after = select_due_work(self.connection, "2026-11-01T18:45:00Z").iloc[0]
        self.assertEqual(before["match_id"], after["match_id"])
        self.assertEqual("Atlas FC-vs-Club Leon", after["match"])
        self.assertEqual(changed["url"], after["Caliente link"])
        self.assertIsNone(after["Pinnacle link"])
        self.assertEqual(history, self.connection.execute(
            "SELECT id, scheduled_time, kickoff, cancelled_at FROM scheduled_slots "
            "WHERE scheduled_time <= '2026-11-01T17:46:00Z' ORDER BY scheduled_time"
        ).fetchall())

    def test_unchanged_rediscovery_keeps_slot_identity(self):
        sources = [listing("caliente", "Atlas-vs-Leon", "2026-11-01T18:00:00Z", 101)]
        persist_listings(self.connection, sources, now="2026-11-01T17:40:00Z")
        first = select_due_work(self.connection, "2026-11-01T17:59:00Z").iloc[0]
        persist_listings(self.connection, sources, now="2026-11-01T17:41:00Z")
        second = select_due_work(self.connection, "2026-11-01T17:59:00Z").iloc[0]
        self.assertEqual(first["slot_id"], second["slot_id"])
        self.assertEqual(first["match_id"], second["match_id"])

    def test_kickoff_seconds_change_does_not_select_two_slots_in_one_minute(self):
        persist_listings(self.connection, [
            listing("caliente", "Atlas-vs-Leon", "2026-11-01T18:00:00Z", 101),
        ], now="2026-11-01T17:58:00Z")
        original = select_due_work(self.connection, "2026-11-01T17:59:00Z").iloc[0]
        persist_listings(self.connection, [
            listing("caliente", "Atlas-vs-Leon", "2026-11-01T18:00:30Z", 101),
        ], now="2026-11-01T17:59:10Z")

        due = select_due_work(self.connection, "2026-11-01T17:59:10Z")
        self.assertEqual(1, len(due))
        self.assertEqual(original["match_id"], due.iloc[0]["match_id"])
        self.assertNotEqual(original["slot_id"], due.iloc[0]["slot_id"])
        self.assertEqual((original["scheduled_time"], None), self.connection.execute(
            "SELECT scheduled_time, cancelled_at FROM scheduled_slots WHERE id = %s",
            (original["slot_id"],),
        ).fetchone())
