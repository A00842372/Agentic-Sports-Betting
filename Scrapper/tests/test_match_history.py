"""History input and credential contracts, without a database dependency."""

import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from match_history import connect_history, read_match_history


class HistoryInputTests(unittest.TestCase):
    def test_invalid_requests_fail_before_opening_a_database(self):
        invalid_requests = [
            {"match_id": "not-a-uuid"},
            {"match_id": None},
            {"bookmaker": "unknown"},
            {"status": "unknown"},
            {"start_time": "not-a-time"},
            {"end_time": "NaT"},
            {"start_time": "2026-11-02", "end_time": "2026-11-01"},
            {"start_time": "2026-11-01", "end_time": "2026-11-01"},
        ]
        driver = SimpleNamespace(connect=MagicMock(side_effect=AssertionError("database opened")))
        with patch.dict(sys.modules, {"psycopg": driver}):
            for request in invalid_requests:
                with self.subTest(request=request):
                    with self.assertRaises(ValueError):
                        read_match_history(**({"match_id": uuid4()} | request))
        driver.connect.assert_not_called()

    def test_writer_credentials_cannot_substitute_for_missing_model_credentials(self):
        with patch.dict(os.environ, {"DATABASE_URL": "writer-must-not-be-used"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "MODEL_DATABASE_URL"):
                with connect_history():
                    self.fail("connection was yielded without model credentials")

    def test_model_credentials_and_explicit_override_use_read_only_connections(self):
        for override, expected in ((None, "model-connection"), ("explicit-reader", "explicit-reader")):
            with self.subTest(override=override):
                connection = SimpleNamespace(read_only=False)
                context = MagicMock()
                context.__enter__.return_value = connection
                driver = SimpleNamespace(connect=MagicMock(return_value=context))
                with patch.dict(os.environ, {"MODEL_DATABASE_URL": "model-connection",
                                             "DATABASE_URL": "writer-must-not-be-used"}, clear=True):
                    with patch.dict(sys.modules, {"psycopg": driver}):
                        with connect_history(override) as opened:
                            self.assertIs(connection, opened)
                            self.assertTrue(opened.read_only)
                driver.connect.assert_called_once_with(expected)
                context.__exit__.assert_called_once()


if __name__ == "__main__":
    unittest.main()
