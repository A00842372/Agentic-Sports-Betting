"""Durable queue behavior through its public API and real local storage."""

import sys
import subprocess
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from threading import Barrier

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utilities.outcome_queue import OutcomeQueue


class OutcomeQueueTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "state" / "outcomes.sqlite3"

    def test_pending_collection_survives_reopening_without_changing_values(self):
        collection = {
            "id": "collection-1", "version": 1,
            "runs": [{"id": "run-1", "started_at": "2026-11-01T17:59:01.123456+00:00",
                      "outcomes": [{"id": "attempt-1", "status": "partial",
                                    "odds": {"HT": "2.150000000000001", "DRAW": None}}]}],
        }
        OutcomeQueue(self.path).enqueue(collection)
        self.assertEqual([collection], OutcomeQueue(self.path).pending())

    def test_failed_delivery_survives_restart_and_is_acknowledged_after_recovery(self):
        collection = {"id": "collection-1", "runs": [{"id": "run-1"}]}
        queue = OutcomeQueue(self.path)
        queue.enqueue(collection)

        def unavailable_database(payload):
            raise ConnectionError("database offline")

        with self.assertRaisesRegex(ConnectionError, "offline"):
            queue.replay(unavailable_database)
        reopened = OutcomeQueue(self.path)
        self.assertEqual([collection], reopened.pending())
        delivered = []
        self.assertEqual(1, reopened.replay(delivered.append))
        self.assertEqual([collection], delivered)
        self.assertEqual([], OutcomeQueue(self.path).pending())

    def test_process_exit_after_enqueue_keeps_committed_collection(self):
        script = (
            "import os, sys; sys.path.insert(0, sys.argv[1]); "
            "from utilities.outcome_queue import OutcomeQueue; "
            "OutcomeQueue(sys.argv[2]).enqueue({'id': 'committed-before-exit'}); "
            "os._exit(0)"
        )
        subprocess.run([sys.executable, "-B", "-c", script,
                        str(Path(__file__).resolve().parents[1]), str(self.path)],
                       check=True, timeout=10)
        self.assertEqual([{"id": "committed-before-exit"}], OutcomeQueue(self.path).pending())

    def test_lost_commit_acknowledgement_redelivers_original_payload(self):
        collection = {"id": "collection-1", "runs": [{"id": "original-run"}]}
        queue = OutcomeQueue(self.path)
        queue.enqueue(collection)
        delivered = []

        def commit_without_acknowledgement(payload):
            delivered.append(payload)
            raise ConnectionError("commit acknowledgement lost")

        with self.assertRaisesRegex(ConnectionError, "acknowledgement lost"):
            queue.replay(commit_without_acknowledgement)
        OutcomeQueue(self.path).replay(delivered.append)
        self.assertEqual([collection, collection], delivered)
        self.assertEqual([], queue.pending())

    def test_replay_failure_retains_failed_and_following_collections(self):
        queue = OutcomeQueue(self.path)
        collections = [{"id": f"collection-{number}"} for number in (1, 2, 3)]
        for collection in collections:
            queue.enqueue(collection)

        def deliver(payload):
            if payload["id"] == "collection-2":
                raise ConnectionError("database offline")

        with self.assertRaises(ConnectionError):
            queue.replay(deliver)
        self.assertEqual(collections[1:], OutcomeQueue(self.path).pending())

    def test_overlapping_replays_can_acknowledge_the_same_committed_payload(self):
        collection = {"id": "collection-1"}
        OutcomeQueue(self.path).enqueue(collection)
        both_delivering = Barrier(2)
        delivered = []

        def persist(payload):
            both_delivering.wait(timeout=5)
            delivered.append(payload)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(OutcomeQueue(self.path).replay, persist) for _ in range(2)]
            self.assertEqual([1, 1], [future.result(timeout=10) for future in futures])
        self.assertEqual([collection, collection], delivered)
        self.assertEqual([], OutcomeQueue(self.path).pending())

    def test_collection_queue_preserves_attempt_identity_times_prices_and_gaps(self):
        from generate_instance import collect_bookmaker_outcomes
        from utilities.run_storage import prepare_collection
        from test_run_storage import ControlledSession, reading

        run_id, slot_id = uuid4(), uuid4()
        runs = pd.DataFrame([{
            "run_id": run_id, "slot_id": slot_id, "match": "Atlas-vs-Leon",
            "started_at": pd.Timestamp("2026-11-01T17:59:01Z"),
            "Caliente link": "https://example.test/cal", "Pinnacle link": None,
            "Playdoit link": None,
        }])
        partial = reading("cal")
        partial["cal_HT"] = "2.150000000000001"
        partial["cal_DRAW"] = pd.NA
        results = collect_bookmaker_outcomes(runs, {
            "cal": lambda: ControlledSession(partial),
            "pn": lambda: ControlledSession(None),
            "pd": lambda: ControlledSession(None),
        })
        queue = OutcomeQueue(self.path)
        queue.enqueue(prepare_collection(runs, results))
        delivered = []
        OutcomeQueue(self.path).replay(delivered.append)
        run = delivered[0]["runs"][0]
        self.assertEqual(str(run_id), run["id"])
        self.assertEqual(str(slot_id), run["slot_id"])
        self.assertEqual("2026-11-01T17:59:01+00:00", run["started_at"])
        attempt = run["outcomes"][0]
        self.assertEqual(str(results["cal"][0]["id"]), attempt["id"])
        self.assertEqual(results["cal"][0]["attempted_at"].isoformat(), attempt["attempted_at"])
        self.assertEqual("2026-11-01T17:59:12+00:00", attempt["source_timestamp"])
        self.assertEqual("2.150000000000001", attempt["odds"]["HT"])
        self.assertIsNone(attempt["odds"]["DRAW"])
        self.assertEqual(["DRAW"], attempt["missing_fields"])
        self.assertEqual(["partial", "missing_link", "missing_link"],
                         [outcome["status"] for outcome in run["outcomes"]])

    def test_offline_registration_and_completion_keep_same_run_identity(self):
        from generate_instance import collect_bookmaker_outcomes
        from utilities.run_storage import prepare_collection, prepare_runs
        from test_run_storage import ControlledSession, reading

        runs = prepare_runs(pd.DataFrame([{
            "slot_id": uuid4(), "match": "Atlas-vs-Leon",
            "Caliente link": "https://example.test/cal", "Pinnacle link": None,
            "Playdoit link": None,
        }]))
        queue = OutcomeQueue(self.path)
        registration = prepare_collection(runs)
        queue.enqueue(registration)
        results = collect_bookmaker_outcomes(runs, {
            "cal": lambda: ControlledSession(reading("cal")),
            "pn": lambda: ControlledSession(None),
            "pd": lambda: ControlledSession(None),
        })
        completed = prepare_collection(runs, results)
        queue.enqueue(completed)
        delivered = []
        self.assertEqual(2, OutcomeQueue(self.path).replay(delivered.append))
        header, result = [payload["runs"][0] for payload in delivered]
        self.assertEqual(header["id"], result["id"])
        self.assertEqual(header["started_at"], result["started_at"])
        self.assertIsNone(header["completed_at"])
        self.assertEqual([], header["outcomes"])
        self.assertIsNotNone(result["completed_at"])
        self.assertEqual(3, len(result["outcomes"]))


if __name__ == "__main__":
    unittest.main()
