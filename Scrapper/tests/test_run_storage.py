"""Typed bookmaker readings and discovery-to-persisted-run behavior."""

import os
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utilities.run_storage import normalize_reading
from utilities.scheduled_work import utc_timestamp


def reading(prefix):
    fields = (
        "HT DRAW AT O0.5 U0.5 O1.5 U1.5 O2.5 U2.5 O3.5 U3.5 O4.5 U4.5 "
        "DC_HT_DRAW DC_HT_AT DC_AT_DRAW BTTS_YES BTTS_NO "
        "1H_O0.5 1H_U0.5 1H_O1.5 1H_U1.5 1H_O2.5 1H_U2.5 "
        "2H_O0.5 2H_U0.5 2H_O1.5 2H_U1.5 2H_O2.5 2H_U2.5"
    ).split()
    values = {f"{prefix}_{field}": 1.95 for field in fields}
    values.update({
        f"{prefix}_HT": "2.15",
        f"{prefix}_match": "Atlas-vs-Leon",
        f"{prefix}_Bookmarker": prefix,
        f"{prefix}_timestamp_utc": "2026-11-01T17:59:12Z",
    })
    return pd.Series(values)


class ReadingOutcomeTests(unittest.TestCase):
    def test_bad_source_timestamp_does_not_erase_valid_odds(self):
        value = reading("cal")
        value["cal_timestamp_utc"] = "invalid timestamp"
        outcome = normalize_reading("cal", value)
        self.assertEqual(Decimal("2.15"), outcome["odds"]["HT"])
        self.assertIsNone(outcome["source_timestamp"])
        self.assertIn("source timestamp", outcome["error"])

    def test_complete_reading_preserves_decimal_odds_and_source_time(self):
        outcome = normalize_reading("cal", reading("cal"))

        self.assertEqual("ok", outcome["status"])
        self.assertEqual(Decimal("2.15"), outcome["odds"]["HT"])
        self.assertEqual(Decimal("1.95"), outcome["odds"]["2H_U2.5"])
        self.assertEqual([], outcome["missing_fields"])
        self.assertEqual(pd.Timestamp("2026-11-01T17:59:12Z"), outcome["source_timestamp"])

    def test_partial_reading_keeps_usable_odds_and_explicit_null_gaps(self):
        value = reading("pn").drop(["pn_DRAW", "pn_timestamp_utc"])
        value["pn_AT"] = pd.NA
        outcome = normalize_reading("pn", value)

        self.assertEqual("partial", outcome["status"])
        self.assertEqual(Decimal("2.15"), outcome["odds"]["HT"])
        self.assertIsNone(outcome["odds"]["DRAW"])
        self.assertIsNone(outcome["odds"]["AT"])

        self.assertEqual(["DRAW", "AT"], outcome["missing_fields"])
        self.assertIn("DRAW", outcome["error"])
        self.assertIsNone(outcome["source_timestamp"])

    def test_invalid_prices_do_not_discard_other_usable_odds(self):
        value = reading("pd")
        value["pd_DRAW"] = "suspended"
        value["pd_AT"] = float("inf")
        outcome = normalize_reading("pd", value)

        self.assertEqual("partial", outcome["status"])
        self.assertEqual(Decimal("2.15"), outcome["odds"]["HT"])
        self.assertIsNone(outcome["odds"]["DRAW"])
        self.assertIsNone(outcome["odds"]["AT"])


class ControlledSession:
    """Stand-in for a bookmaker's external response, without browser/network IO."""

    def __init__(self, value, observer=None):
        self.value = value
        self.observer = observer

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def scrape(self, link):
        if self.observer is not None:
            self.observer()
        if isinstance(self.value, Exception):
            raise self.value
        return self.value.copy()


class ScriptedSession(ControlledSession):
    def __init__(self, responses):
        super().__init__(None)
        self.responses = iter(responses)

    def scrape(self, link):
        self.value = next(self.responses)
        return super().scrape(link)


class CollectedOutcomeTests(unittest.TestCase):
    def test_session_retries_and_scrape_retries_share_ordered_history(self):
        from generate_instance import collect_bookmaker_outcomes

        links = pd.DataFrame([
            {"match": "Atlas-vs-Leon", "Caliente link": "https://example.test/cal",
             "Pinnacle link": None, "Playdoit link": None},
            {"match": "No-Caliente-Link", "Caliente link": None,
             "Pinnacle link": None, "Playdoit link": None},
        ])
        openings = []

        def recovering_factory():
            openings.append(True)
            if len(openings) == 1:
                raise TimeoutError("startup timed out")
            return ScriptedSession([TimeoutError("scrape timed out"), reading("cal")])

        results = collect_bookmaker_outcomes(links, {
            "cal": recovering_factory,
            "pn": lambda: ControlledSession(None),
            "pd": lambda: ControlledSession(None),
        })
        attempts = results["cal"][0]["attempts"]
        self.assertEqual(["failed", "failed", "ok"], [a["status"] for a in attempts])
        self.assertEqual([1, 2, 3], [a["attempt_number"] for a in attempts])
        self.assertIn("startup timed out", attempts[0]["error"])
        self.assertIn("scrape timed out", attempts[1]["error"])
        self.assertEqual(1, len(results["cal"][1]["attempts"]))
        self.assertEqual("missing_link", results["cal"][1]["status"])

    def test_exhausted_retries_preserve_each_failure(self):
        from generate_instance import collect_bookmaker_outcomes

        links = pd.DataFrame([{
            "match": "Atlas-vs-Leon", "Caliente link": "https://example.test/cal",
            "Pinnacle link": "https://example.test/pn", "Playdoit link": None,
        }])
        results = collect_bookmaker_outcomes(links, {
            "cal": lambda: ControlledSession(TimeoutError("still unavailable")),
            "pn": lambda: ControlledSession(ValueError("bad response")),
            "pd": lambda: ControlledSession(None),
        })
        attempts = results["cal"][0]["attempts"]
        self.assertEqual(["failed"] * 3, [a["status"] for a in attempts])
        self.assertEqual([1, 2, 3], [a["attempt_number"] for a in attempts])
        self.assertEqual(3, len({a["id"] for a in attempts}))
        self.assertEqual(1, len(results["pn"][0]["attempts"]))
        missing = results["pd"][0]["attempts"]
        self.assertEqual(["missing_link"], [a["status"] for a in missing])
        self.assertEqual(1, missing[0]["attempt_number"])

    def test_retry_preserves_failed_attempt_before_success(self):
        from generate_instance import collect_bookmaker_outcomes

        links = pd.DataFrame([{
            "match": "Atlas-vs-Leon", "Caliente link": "https://example.test/cal",
            "Pinnacle link": None, "Playdoit link": None,
        }])

        results = collect_bookmaker_outcomes(links, {
            "cal": lambda: ScriptedSession([TimeoutError("bookmaker timed out"), reading("cal")]),
            "pn": lambda: ControlledSession(None),
            "pd": lambda: ControlledSession(None),
        })
        result = results["cal"][0]
        self.assertEqual("ok", result["status"])
        attempts = result["attempts"]
        self.assertEqual(["failed", "ok"], [a["status"] for a in attempts])
        self.assertEqual([1, 2], [a["attempt_number"] for a in attempts])
        self.assertNotEqual(attempts[0]["id"], attempts[1]["id"])
        self.assertIn("bookmaker timed out", attempts[0]["error"])
        self.assertLessEqual(attempts[0]["attempted_at"], attempts[1]["attempted_at"])
        self.assertEqual(Decimal("2.15"), attempts[1]["odds"]["HT"])

    def test_session_startup_failure_does_not_discard_other_bookmakers(self):
        from generate_instance import collect_bookmaker_outcomes

        links = pd.DataFrame([{
            "match": "Atlas-vs-Leon", "Caliente link": "https://example.test/cal",
            "Pinnacle link": "https://example.test/pn", "Playdoit link": "https://example.test/pd",
        }])

        def unavailable_browser():
            raise ValueError("browser not available")

        before = utc_timestamp()
        results = collect_bookmaker_outcomes(links, {
            "cal": lambda: ControlledSession(reading("cal")),
            "pn": unavailable_browser,
            "pd": lambda: ControlledSession(reading("pd")),
        })
        after = utc_timestamp()
        self.assertEqual("ok", results["cal"][0]["status"])
        self.assertEqual("ok", results["pd"][0]["status"])
        self.assertEqual("failed", results["pn"][0]["status"])
        self.assertIn("Session failure", results["pn"][0]["error"])
        self.assertIn("browser not available", results["pn"][0]["error"])
        self.assertLessEqual(before, results["pn"][0]["attempted_at"])
        self.assertLessEqual(results["pn"][0]["attempted_at"], after)

    def test_collection_timestamps_partial_failed_and_missing_link_outcomes(self):
        from generate_instance import collect_bookmaker_outcomes

        links = pd.DataFrame([{
            "match": "Atlas-vs-Leon", "Caliente link": "https://example.test/cal",
            "Pinnacle link": "https://example.test/pn", "Playdoit link": None,
        }])
        partial = reading("cal")
        partial["cal_DRAW"] = pd.NA
        opened_missing_sessions = []

        def missing_session():
            opened_missing_sessions.append(True)
            return ControlledSession(AssertionError("no link"))

        before = utc_timestamp()
        results = collect_bookmaker_outcomes(links, {
            "cal": lambda: ControlledSession(partial),
            "pn": lambda: ControlledSession(ValueError("invalid response")),
            "pd": missing_session,
        })
        after = utc_timestamp()

        self.assertEqual("partial", results["cal"][0]["status"])
        self.assertEqual(Decimal("2.15"), results["cal"][0]["odds"]["HT"])
        self.assertIsNone(results["cal"][0]["odds"]["DRAW"])
        self.assertEqual("failed", results["pn"][0]["status"])
        self.assertIn("invalid response", results["pn"][0]["error"])
        self.assertEqual("missing_link", results["pd"][0]["status"])
        self.assertEqual([], opened_missing_sessions)
        for prefix in ("cal", "pn", "pd"):
            self.assertLessEqual(before, results[prefix][0]["attempted_at"])
            self.assertLessEqual(results[prefix][0]["attempted_at"], after)


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL is required")
class PersistedRunTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        from psycopg.conninfo import make_conninfo

        self.schema = "run_test_" + uuid4().hex
        self.admin = psycopg.connect(os.environ["TEST_DATABASE_URL"], autocommit=True)
        self.admin.execute(f'CREATE SCHEMA "{self.schema}"')
        self.database_url = make_conninfo(os.environ["TEST_DATABASE_URL"],
                                         options=f"-c search_path={self.schema}")
        self.connection = psycopg.connect(self.database_url, autocommit=True)
        self.queue_directory = TemporaryDirectory()
        self.addCleanup(self.queue_directory.cleanup)
        self.queue_path = Path(self.queue_directory.name) / "outcomes.sqlite3"

    def tearDown(self):
        self.connection.close()
        self.admin.execute(f'DROP SCHEMA "{self.schema}" CASCADE')
        self.admin.close()

    def seed(self, bookmakers=("caliente", "pinnacle", "playdoit")):
        from match_discovery import persist_listings
        from test_discovery_storage import listing

        persist_listings(self.connection, [
            listing(bookmaker, "Atlas-vs-Leon", "2026-11-01T18:00:00Z", index + 100)
            for index, bookmaker in enumerate(bookmakers)
        ], now="2026-11-01T17:40:00Z")

    def collect(self, values=None, run_time="2026-11-01T17:59:00Z"):
        from generate_instance import generate_instance

        values = values or {prefix: reading(prefix) for prefix in ("cal", "pn", "pd")}
        factories = {prefix: lambda value=value: ControlledSession(value)
                     for prefix, value in values.items()}
        return generate_instance(database_url=self.database_url, run_time=run_time,
                                 session_factories=factories, queue_path=self.queue_path)

    def test_outage_after_collection_replays_retries_and_partial_results(self):
        from generate_instance import generate_instance

        self.seed(bookmakers=("caliente", "pinnacle"))
        self.collect(run_time="2026-11-01T17:39:00Z")
        self.connection.execute("""
            CREATE FUNCTION reject_outcome_writes() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'database unavailable' USING ERRCODE = '08006';
            END;
            $$
        """)
        self.connection.execute("""
            CREATE TRIGGER reject_outcome_writes BEFORE INSERT ON bookmaker_outcomes
            FOR EACH ROW EXECUTE FUNCTION reject_outcome_writes()
        """)
        partial = reading("cal")
        partial["cal_DRAW"] = pd.NA
        before = utc_timestamp()
        result = generate_instance(
            database_url=self.database_url, run_time="2026-11-01T17:59:00Z",
            queue_path=self.queue_path,
            session_factories={
                "cal": lambda: ScriptedSession([TimeoutError("temporary timeout"), partial]),
                "pn": lambda: ControlledSession(ValueError("bad response")),
                "pd": lambda: ControlledSession(None),
            },
        )
        after = utc_timestamp()
        self.assertEqual("queued", result.attrs["storage_status"])
        self.assertEqual(0, self.connection.execute("SELECT count(*) FROM bookmaker_outcomes").fetchone()[0])
        self.connection.execute("DROP TRIGGER reject_outcome_writes ON bookmaker_outcomes")
        self.assertTrue(self.collect(run_time="2026-11-01T18:01:00Z").empty)
        rows = self.connection.execute(
            "SELECT o.bookmaker, o.attempt_number, o.status, o.attempted_at, d.value "
            "FROM bookmaker_outcomes o JOIN outcome_odds d ON d.outcome_id = o.id "
            "WHERE d.field = 'HT' ORDER BY o.bookmaker, o.attempt_number"
        ).fetchall()
        self.assertEqual(["failed", "partial", "failed", "missing_link"], [r[2] for r in rows])
        self.assertEqual([1, 2, 1, 1], [r[1] for r in rows])
        self.assertEqual([None, Decimal("2.15"), None, None], [r[4] for r in rows])
        for row in rows:
            self.assertLessEqual(before, row[3])
            self.assertLessEqual(row[3], after)
        completed_at = self.connection.execute("SELECT completed_at FROM scraper_runs").fetchone()[0]
        self.assertLessEqual(before, completed_at)
        self.assertLessEqual(completed_at, after)

    def test_replay_after_lost_commit_acknowledgement_preserves_each_original_record_once(self):
        import psycopg
        from generate_instance import collect_bookmaker_outcomes
        from utilities.outcome_queue import OutcomeQueue
        from utilities.run_storage import prepare_collection, prepare_runs, start_runs, store_collection
        from utilities.scheduled_work import select_due_work

        self.seed()
        runs = start_runs(self.connection, prepare_runs(select_due_work(self.connection, "2026-11-01T17:59:00Z")))
        results = collect_bookmaker_outcomes(runs, {
            prefix: lambda prefix=prefix: ControlledSession(reading(prefix))
            for prefix in ("cal", "pn", "pd")
        })
        collection = prepare_collection(runs, results)
        queue = OutcomeQueue(self.queue_path)
        queue.enqueue(collection)

        def persist(payload):
            with psycopg.connect(self.database_url, autocommit=True) as connection:
                store_collection(connection, payload)

        def commit_without_acknowledgement(payload):
            persist(payload)
            raise psycopg.OperationalError("commit acknowledgement lost")

        with self.assertRaises(psycopg.OperationalError):
            queue.replay(commit_without_acknowledgement)
        snapshot = self.connection.execute(
            "SELECT o.id, o.run_id, o.attempted_at, o.source_timestamp, o.status, "
            "d.field, d.value, r.started_at, r.completed_at "
            "FROM bookmaker_outcomes o JOIN outcome_odds d ON d.outcome_id = o.id "
            "JOIN scraper_runs r ON r.id = o.run_id ORDER BY o.id, d.field"
        ).fetchall()
        OutcomeQueue(self.queue_path).replay(persist)
        self.assertEqual([], queue.pending())
        self.assertEqual(snapshot, self.connection.execute(
            "SELECT o.id, o.run_id, o.attempted_at, o.source_timestamp, o.status, "
            "d.field, d.value, r.started_at, r.completed_at "
            "FROM bookmaker_outcomes o JOIN outcome_odds d ON d.outcome_id = o.id "
            "JOIN scraper_runs r ON r.id = o.run_id ORDER BY o.id, d.field"
        ).fetchall())
        self.assertEqual(90, len(snapshot))
        expected_ids = {outcome["id"] for outcome in collection["runs"][0]["outcomes"]}
        self.assertEqual(expected_ids, {str(row[0]) for row in snapshot})
        self.assertEqual(pd.Timestamp(collection["runs"][0]["completed_at"]), snapshot[0][8])

    def test_outage_before_due_selection_opens_no_sessions_and_later_records_gaps(self):
        import psycopg
        from generate_instance import generate_instance

        self.seed()

        def unexpected_session():
            raise AssertionError("no work was selected")

        with patch("psycopg.connect", side_effect=psycopg.OperationalError("database offline")):
            with self.assertRaises(psycopg.OperationalError):
                generate_instance(
                    database_url=self.database_url, run_time="2026-11-01T17:59:00Z",
                    queue_path=self.queue_path,
                    session_factories={prefix: unexpected_session for prefix in ("cal", "pn", "pd")},
                )
        self.assertTrue(self.collect(run_time="2026-11-01T18:01:00Z").empty)
        self.assertEqual(16, self.connection.execute("SELECT count(*) FROM missed_slots").fetchone()[0])
        self.assertEqual(0, self.connection.execute("SELECT count(*) FROM scraper_runs").fetchone()[0])
        self.assertEqual(0, self.connection.execute("SELECT count(*) FROM bookmaker_outcomes").fetchone()[0])

    def test_outage_after_selection_collects_and_replay_corrects_provisional_missed_slot(self):
        self.seed()
        self.collect(run_time="2026-11-01T17:39:00Z")
        self.connection.execute("""
            CREATE FUNCTION unavailable_run_storage() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'database unavailable' USING ERRCODE = '08006';
            END;
            $$
        """)
        self.connection.execute("""
            CREATE TRIGGER unavailable_run_storage BEFORE INSERT ON scraper_runs
            FOR EACH ROW EXECUTE FUNCTION unavailable_run_storage()
        """)
        result = self.collect()
        self.assertEqual("queued", result.attrs["storage_status"])
        self.assertEqual("ok", result.iloc[0]["cal_status"])
        self.assertEqual(0, self.connection.execute("SELECT count(*) FROM scraper_runs").fetchone()[0])
        # A concurrent/restarted check can see a gap before the offline run arrives.
        self.assertTrue(self.collect(run_time="2026-11-01T18:01:00Z").empty)
        self.assertEqual(16, self.connection.execute("SELECT count(*) FROM missed_slots").fetchone()[0])
        self.connection.execute("DROP TRIGGER unavailable_run_storage ON scraper_runs")
        self.assertTrue(self.collect(run_time="2026-11-01T18:02:00Z").empty)
        self.assertEqual(0, self.connection.execute(
            "SELECT count(*) FROM missed_slots WHERE slot_id = %s", (result.iloc[0]["slot_id"],),
        ).fetchone()[0])
        self.assertEqual(15, self.connection.execute("SELECT count(*) FROM missed_slots").fetchone()[0])
        self.assertEqual([(result.iloc[0]["run_id"], result.iloc[0]["started_at"])],
                         self.connection.execute("SELECT id, started_at FROM scraper_runs").fetchall())
        self.assertEqual(3, self.connection.execute("SELECT count(*) FROM bookmaker_outcomes").fetchone()[0])

    def test_discovery_to_scrape_stores_typed_outcomes_without_csv(self):
        self.seed()
        before = utc_timestamp()
        with patch("pandas.read_csv", side_effect=AssertionError("CSV input forbidden")), \
             patch.object(pd.DataFrame, "to_csv", side_effect=AssertionError("CSV output forbidden")):
            result = self.collect()
        after = utc_timestamp()

        run = self.connection.execute(
            "SELECT r.id, s.match_id, s.scheduled_time, r.started_at, r.completed_at "
            "FROM scraper_runs r JOIN scheduled_slots s ON s.id = r.slot_id"
        ).fetchone()
        self.assertEqual(result.iloc[0]["run_id"], run[0])
        self.assertEqual(result.iloc[0]["match_id"], run[1])
        self.assertEqual(pd.Timestamp("2026-11-01T17:59:00Z"), run[2])
        self.assertLessEqual(before, run[3])
        self.assertLessEqual(run[3], run[4])
        self.assertLessEqual(run[4], after)
        rows = self.connection.execute(
            "SELECT o.bookmaker, o.status, o.attempted_at, o.source_timestamp, d.value "
            "FROM bookmaker_outcomes o JOIN outcome_odds d ON d.outcome_id = o.id "
            "WHERE d.field = 'HT' ORDER BY o.bookmaker"
        ).fetchall()
        self.assertEqual(["caliente", "pinnacle", "playdoit"], [r[0] for r in rows])
        for _, status, attempted_at, source_timestamp, price in rows:
            self.assertEqual("ok", status)
            self.assertLessEqual(run[3], attempted_at)
            self.assertLessEqual(attempted_at, run[4])
            self.assertEqual(pd.Timestamp("2026-11-01T17:59:12Z"), source_timestamp)
            self.assertEqual(Decimal("2.15"), price)

    def test_partial_failure_and_missing_link_are_persisted_explicitly(self):
        self.seed(bookmakers=("caliente", "pinnacle"))
        partial = reading("cal")
        partial["cal_DRAW"] = pd.NA
        result = self.collect({"cal": partial, "pn": ValueError("invalid response"),
                               "pd": AssertionError("missing link must not be scraped")})
        rows = self.connection.execute(
            "SELECT o.bookmaker, o.status, o.error, o.missing_fields, d.value "
            "FROM bookmaker_outcomes o JOIN outcome_odds d ON d.outcome_id = o.id "
            "WHERE d.field = 'DRAW' ORDER BY o.bookmaker"
        ).fetchall()
        self.assertEqual(["partial", "failed", "missing_link"], [r[1] for r in rows])
        self.assertEqual("partial", result.iloc[0]["cal_status"])
        self.assertIn("DRAW", rows[0][3])
        self.assertIn("invalid response", rows[1][2])
        self.assertIn("No event link", rows[2][2])
        self.assertTrue(all(r[4] is None for r in rows))

    def test_unchanged_reading_is_stored_again_in_a_distinct_run(self):
        self.seed()
        first = self.collect()
        second = self.collect()
        self.assertNotEqual(first.iloc[0]["run_id"], second.iloc[0]["run_id"])
        self.assertEqual(first.iloc[0]["slot_id"], second.iloc[0]["slot_id"])
        self.assertEqual(2, self.connection.execute("SELECT count(*) FROM scraper_runs").fetchone()[0])
        self.assertEqual(6, self.connection.execute("SELECT count(*) FROM bookmaker_outcomes").fetchone()[0])

    def test_retry_history_keeps_ids_order_errors_and_final_odds(self):
        from generate_instance import generate_instance

        self.seed()

        result = generate_instance(
            database_url=self.database_url, run_time="2026-11-01T17:59:00Z",
            queue_path=self.queue_path,
            session_factories={
                "cal": lambda: ScriptedSession([TimeoutError("temporary timeout"), reading("cal")]),
                "pn": lambda: ControlledSession(reading("pn")),
                "pd": lambda: ControlledSession(reading("pd")),
            },
        )
        rows = self.connection.execute(
            "SELECT o.id, o.attempt_number, o.status, o.error, o.attempted_at, d.value "
            "FROM bookmaker_outcomes o JOIN outcome_odds d ON d.outcome_id = o.id "
            "WHERE o.run_id = %s AND o.bookmaker = 'caliente' AND d.field = 'HT' "
            "ORDER BY o.attempt_number", (result.iloc[0]["run_id"],),
        ).fetchall()
        self.assertEqual([1, 2], [r[1] for r in rows])
        self.assertEqual(["failed", "ok"], [r[2] for r in rows])
        self.assertNotEqual(rows[0][0], rows[1][0])
        self.assertIn("temporary timeout", rows[0][3])
        self.assertLessEqual(rows[0][4], rows[1][4])
        self.assertEqual([None, Decimal("2.15")], [r[5] for r in rows])
        self.assertEqual("ok", result.iloc[0]["cal_status"])

    def test_existing_outcomes_survive_retry_schema_upgrade(self):
        self.seed()
        self.collect()
        original = self.connection.execute(
            "SELECT id, attempted_at, status FROM bookmaker_outcomes ORDER BY id"
        ).fetchall()
        # Recreate the schema from ticket #4, retaining its real stored data.
        self.connection.execute("ALTER TABLE bookmaker_outcomes DROP COLUMN attempt_number CASCADE")
        self.collect()
        for outcome_id, attempted_at, status in original:
            row = self.connection.execute(
                "SELECT attempted_at, status, attempt_number FROM bookmaker_outcomes WHERE id = %s",
                (outcome_id,),
            ).fetchone()
            self.assertEqual((attempted_at, status, 1), row)
        self.assertEqual(6, self.connection.execute("SELECT count(*) FROM bookmaker_outcomes").fetchone()[0])

    def test_run_is_visible_to_another_connection_before_bookmaker_io(self):
        from generate_instance import generate_instance

        self.seed()
        observed = []

        def observe_started_run():
            observed.extend(self.connection.execute(
                "SELECT id, completed_at FROM scraper_runs"
            ).fetchall())

        result = generate_instance(
            database_url=self.database_url, run_time="2026-11-01T17:59:00Z",
            queue_path=self.queue_path,
            session_factories={
                "cal": lambda: ControlledSession(reading("cal"), observe_started_run),
                "pn": lambda: ControlledSession(reading("pn")),
                "pd": lambda: ControlledSession(reading("pd")),
            },
        )
        self.assertEqual([(result.iloc[0]["run_id"], None)], observed)

    def test_no_due_work_creates_no_run(self):
        self.seed()
        self.assertTrue(self.collect(run_time="2026-11-01T17:44:00Z").empty)
        self.assertEqual(0, self.connection.execute("SELECT count(*) FROM scraper_runs").fetchone()[0])

    def test_resume_records_missed_slots_without_fabricating_runs(self):
        self.seed()
        before = utc_timestamp()
        self.assertTrue(self.collect(run_time="2026-11-01T18:01:00Z").empty)
        after = utc_timestamp()
        rows = self.connection.execute(
            "SELECT s.match_id, s.scheduled_time, m.detected_at "
            "FROM missed_slots m JOIN scheduled_slots s ON s.id = m.slot_id "
            "ORDER BY s.scheduled_time"
        ).fetchall()
        expected = [pd.Timestamp("2026-11-01T17:40:00Z"),
                    *pd.date_range("2026-11-01T17:45:00Z", "2026-11-01T17:59:00Z", freq="min")]
        self.assertEqual(expected, [row[1] for row in rows])
        self.assertEqual(1, len({row[0] for row in rows}))
        for _, _, detected_at in rows:
            self.assertLessEqual(before, detected_at)
            self.assertLessEqual(detected_at, after)
        self.assertEqual(0, self.connection.execute("SELECT count(*) FROM scraper_runs").fetchone()[0])
        self.assertEqual(0, self.connection.execute("SELECT count(*) FROM bookmaker_outcomes").fetchone()[0])
        self.assertEqual(0, self.connection.execute("SELECT count(*) FROM outcome_odds").fetchone()[0])
        # Another check must neither duplicate gaps nor replace detection times.
        self.assertTrue(self.collect(run_time="2026-11-01T18:02:00Z").empty)
        self.assertEqual(rows, self.connection.execute(
            "SELECT s.match_id, s.scheduled_time, m.detected_at "
            "FROM missed_slots m JOIN scheduled_slots s ON s.id = m.slot_id "
            "ORDER BY s.scheduled_time"
        ).fetchall())

    def test_resume_scrapes_only_current_minute_and_preserves_actual_start_time(self):
        self.seed()
        before = utc_timestamp()
        result = self.collect(run_time="2026-11-01T17:46:30Z")
        after = utc_timestamp()
        self.assertEqual(1, len(result))
        run = result.iloc[0]
        self.assertEqual(pd.Timestamp("2026-11-01T17:46:00Z"), run["scheduled_time"])
        self.assertLessEqual(before, run["started_at"])
        self.assertLessEqual(run["started_at"], after)
        self.assertEqual([
            (pd.Timestamp("2026-11-01T17:40:00Z"),),
            (pd.Timestamp("2026-11-01T17:45:00Z"),),
        ], self.connection.execute(
            "SELECT s.scheduled_time FROM missed_slots m "
            "JOIN scheduled_slots s ON s.id = m.slot_id ORDER BY s.scheduled_time"
        ).fetchall())
        self.assertEqual(1, self.connection.execute("SELECT count(*) FROM scraper_runs").fetchone()[0])
        self.assertEqual(3, self.connection.execute("SELECT count(*) FROM bookmaker_outcomes").fetchone()[0])

    def test_failed_and_incomplete_runs_are_not_missed_slots(self):
        from utilities.run_storage import prepare_runs, start_runs
        from utilities.scheduled_work import select_due_work

        self.seed()
        failed = self.collect(
            values={prefix: ValueError("invalid response") for prefix in ("cal", "pn", "pd")},
            run_time="2026-11-01T17:45:00Z",
        )
        incomplete = start_runs(self.connection, prepare_runs(select_due_work(
            self.connection, run_time="2026-11-01T17:46:00Z",
        )))
        self.assertTrue(self.collect(run_time="2026-11-01T18:01:00Z").empty)
        for slot_id in (failed.iloc[0]["slot_id"], incomplete.iloc[0]["slot_id"]):
            self.assertEqual(0, self.connection.execute(
                "SELECT count(*) FROM missed_slots WHERE slot_id = %s", (slot_id,),
            ).fetchone()[0])
        self.assertIsNone(self.connection.execute(
            "SELECT completed_at FROM scraper_runs WHERE id = %s",
            (incomplete.iloc[0]["run_id"],),
        ).fetchone()[0])
        self.assertEqual(14, self.connection.execute("SELECT count(*) FROM missed_slots").fetchone()[0])

    def test_run_registration_failure_rolls_back_missed_slot_reconciliation(self):
        import psycopg

        self.seed()
        self.assertTrue(self.collect(run_time="2026-11-01T17:39:00Z").empty)
        # Reject new runs at the database boundary to exercise atomic recovery.
        self.connection.execute("""
            CREATE FUNCTION reject_run_registration() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'run registration unavailable';
            END;
            $$
        """)
        self.connection.execute("""
            CREATE TRIGGER reject_run_registration
            BEFORE INSERT ON scraper_runs FOR EACH ROW
            EXECUTE FUNCTION reject_run_registration()
        """)
        with self.assertRaisesRegex(psycopg.errors.RaiseException, "run registration unavailable"):
            self.collect(run_time="2026-11-01T17:45:00Z")
        self.assertEqual(0, self.connection.execute("SELECT count(*) FROM missed_slots").fetchone()[0])
        self.assertEqual(0, self.connection.execute("SELECT count(*) FROM scraper_runs").fetchone()[0])

    def test_rescheduling_preserves_elapsed_gaps_and_excludes_cancelled_slots(self):
        from match_discovery import persist_listings
        from test_discovery_storage import listing

        self.seed()
        old_slots = self.connection.execute(
            "SELECT id FROM scheduled_slots "
            "WHERE scheduled_time <= '2026-11-01T17:46:00Z'"
        ).fetchall()
        persist_listings(self.connection, [
            listing(bookmaker, "Atlas-vs-Leon", "2026-11-01T19:00:00Z", index + 100)
            for index, bookmaker in enumerate(("caliente", "pinnacle", "playdoit"))
        ], now="2026-11-01T17:46:00Z")
        self.assertTrue(self.collect(run_time="2026-11-01T18:01:00Z").empty)
        for (slot_id,) in old_slots:
            self.assertEqual(1, self.connection.execute(
                "SELECT count(*) FROM missed_slots WHERE slot_id = %s", (slot_id,),
            ).fetchone()[0])
        self.assertEqual(0, self.connection.execute(
            "SELECT count(*) FROM missed_slots m JOIN scheduled_slots s ON s.id = m.slot_id "
            "WHERE s.cancelled_at IS NOT NULL"
        ).fetchone()[0])
        self.assertEqual(0, self.connection.execute(
            "SELECT count(*) FROM missed_slots m JOIN scheduled_slots s ON s.id = m.slot_id "
            "WHERE s.scheduled_time >= '2026-11-01T18:01:00Z'"
        ).fetchone()[0])
