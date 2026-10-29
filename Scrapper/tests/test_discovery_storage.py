"""Discovery behavior at the persisted PostgreSQL boundary.

Set TEST_DATABASE_URL to an expendable PostgreSQL database to run these tests.
Each test uses a fresh schema and leaves other schemas untouched.
"""

import os
import sys
import unittest
from pathlib import Path
from uuid import uuid4

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from match_discovery import add_bookmaker_links, persist_listings


def listing(bookmaker, name, kickoff, event_id):
    links = {
        "caliente": f"https://sports.caliente.mx/es_MX/e/{event_id}/old-slug",
        "pinnacle": f"https://www.pinnacle.com/es/soccer/league/old-slug/{event_id}/#all",
        "playdoit": f"https://www.playdoit.mx/#page=event&eventId={event_id}&sportId=1",
    }
    return {
        "bookmaker": bookmaker,
        "match": name,
        "start_time": kickoff,
        "url": links[bookmaker],
    }


class LinkMatchingTests(unittest.TestCase):
    def test_same_opponent_does_not_make_different_home_teams_confident(self):
        base = pd.DataFrame([{
            "match": "Manchester City-vs-Chelsea", "start_time": "2026-11-01T18:00:00Z",
        }])
        other = pd.DataFrame([{
            "match": "Manchester United-vs-Chelsea", "start_time": "2026-11-01T18:00:00Z",
            "Pinnacle link": "https://example.test/different-event",
        }])
        result = add_bookmaker_links(base, other, "Pinnacle link")
        self.assertTrue(pd.isna(result.iloc[0]["Pinnacle link"]))

    def test_single_time_candidate_with_unrelated_teams_is_not_attached(self):
        caliente = pd.DataFrame([{
            "match": "Atlas-vs-Leon", "start_time": "2026-11-01T18:00:00Z",
        }])
        pinnacle = pd.DataFrame([{
            "match": "Tigres-vs-America", "start_time": "2026-11-01T18:03:00Z",
            "Pinnacle link": "https://example.test/unrelated",
        }])

        result = add_bookmaker_links(caliente, pinnacle, "Pinnacle link")

        self.assertTrue(pd.isna(result.iloc[0]["Pinnacle link"]))


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL is required")
class DiscoveryStorageTests(unittest.TestCase):
    def setUp(self):
        import psycopg

        self.psycopg = psycopg
        self.schema = "discovery_test_" + uuid4().hex
        self.admin = psycopg.connect(os.environ["TEST_DATABASE_URL"], autocommit=True)
        self.admin.execute(f'CREATE SCHEMA "{self.schema}"')
        self.connection = psycopg.connect(
            os.environ["TEST_DATABASE_URL"],
            options=f"-c search_path={self.schema}",
        )

    def tearDown(self):
        self.connection.close()
        self.admin.execute(f'DROP SCHEMA "{self.schema}" CASCADE')
        self.admin.close()

    def test_three_confident_listings_share_one_persisted_match_id(self):
        kickoff = "2026-11-01T18:00:00Z"
        persist_listings(self.connection, [
            listing("caliente", "Atlas-vs-Leon", kickoff, 101),
            listing("pinnacle", "Atlas-vs-León", kickoff, 202),
            listing("playdoit", "Atlas-vs-Leon", kickoff, 303),
        ])

        rows = self.connection.execute(
            "SELECT bookmaker, match_id, source_name, source_kickoff, "
            "source_url FROM bookmaker_listings ORDER BY bookmaker"
        ).fetchall()
        self.assertEqual(3, len(rows))
        self.assertEqual(1, len({row[1] for row in rows}))
        self.assertEqual({"caliente", "pinnacle", "playdoit"}, {row[0] for row in rows})
        self.assertEqual(1, self.connection.execute("SELECT count(*) FROM matches").fetchone()[0])

    def test_rediscovery_updates_evidence_and_keeps_match_id(self):
        persist_listings(self.connection, [
            listing("caliente", "Atlas-vs-Leon", "2026-11-01T18:00:00Z", 101),
            listing("pinnacle", "Atlas-vs-Leon", "2026-11-01T18:00:00Z", 202),
        ])
        original_id = self.connection.execute(
            "SELECT match_id FROM bookmaker_listings WHERE bookmaker = 'caliente'"
        ).fetchone()[0]
        changed = listing("caliente", "Atlas FC-vs-Club Leon", "2026-11-01T19:00:00Z", 101)
        changed["url"] = "https://sports.caliente.mx/es_MX/e/101/new-slug"
        persist_listings(self.connection, [changed])

        row = self.connection.execute(
            "SELECT match_id, source_name, source_kickoff, source_url "
            "FROM bookmaker_listings WHERE bookmaker = 'caliente'"
        ).fetchone()
        self.assertEqual(original_id, row[0])
        self.assertEqual("Atlas FC-vs-Club Leon", row[1])
        self.assertEqual(pd.Timestamp("2026-11-01T19:00:00Z"), pd.Timestamp(row[2]))
        self.assertTrue(row[3].endswith("/new-slug"))
        self.assertEqual(1, self.connection.execute("SELECT count(*) FROM matches").fetchone()[0])

    def test_single_time_candidate_with_unrelated_teams_is_reviewable(self):
        persist_listings(self.connection, [
            listing("caliente", "Atlas-vs-Leon", "2026-11-01T18:00:00Z", 101),
            listing("pinnacle", "Tigres-vs-America", "2026-11-01T18:03:00Z", 202),
        ])

        rows = self.connection.execute(
            "SELECT l.bookmaker, l.match_id, l.source_name, l.source_url, m.review_reason "
            "FROM bookmaker_listings l JOIN matches m ON m.id = l.match_id "
            "ORDER BY l.bookmaker"
        ).fetchall()
        self.assertEqual(2, len({row[1] for row in rows}))
        self.assertEqual("low_name_similarity", rows[1][4])
        self.assertTrue(rows[1][3].endswith("/202/#all"))

    def test_missing_kickoff_is_preserved_for_review(self):
        persist_listings(self.connection, [
            listing("pinnacle", "Atlas-vs-Leon", None, 202),
        ])
        row = self.connection.execute(
            "SELECT l.source_name, l.source_kickoff, m.review_reason "
            "FROM bookmaker_listings l JOIN matches m ON m.id = l.match_id"
        ).fetchone()
        self.assertEqual(("Atlas-vs-Leon", None, "missing_kickoff"), row)
