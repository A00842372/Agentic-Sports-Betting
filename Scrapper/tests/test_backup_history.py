"""Backup publication and failure safety at the external command boundary.

Tiny executable PostgreSQL stand-ins exercise real subprocesses and temporary
storage. These tests do not establish that a PostgreSQL archive can be restored.
"""

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backup_history import create_backup, main, verify_backup


_POSTGRES_COMMAND = '''
import json
import os
from pathlib import Path
import sys

sys.argv = sys.argv[1:]
command = Path(sys.argv[0]).name
with open(os.environ["BACKUP_TEST_LOG"], "a") as stream:
    stream.write(json.dumps({"command": command, "arguments": sys.argv[1:]}) + "\\n")
if command == "pg_dump":
    Path(sys.argv[sys.argv.index("--file") + 1]).write_bytes(b"controlled archive")
if command in os.environ.get("BACKUP_TEST_FAIL", "").split(","):
    sys.exit(9)
'''


@unittest.skipUnless(os.name == "posix", "POSIX command execution and permissions are required")
class BackupCommandTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name in ("pg_dump", "pg_restore", "createdb", "dropdb"):
            executable = self.bin / name
            executable.write_text(
                f'#!/bin/sh\nexec {shlex.quote(sys.executable)} -c '
                f'{shlex.quote(_POSTGRES_COMMAND)} "$0" "$@"\n'
            )
            executable.chmod(0o700)
        self.log = self.root / "commands.jsonl"
        self.backups = self.root / "backups"
        environment = {
            "PATH": str(self.bin) + os.pathsep + os.defpath,
            "BACKUP_TEST_LOG": str(self.log),
        }
        environment["BACKUP_TEST_FAIL"] = ""
        environment_patch = patch.dict(os.environ, environment)
        environment_patch.start()
        self.addCleanup(environment_patch.stop)

    def commands(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def bundle(self, reference=None):
        backup = create_backup(self.backups, source_service="test_source")
        metadata = backup / "manifest.json"
        manifest = json.loads(metadata.read_text())
        manifest["reference"] = reference
        metadata.write_text(json.dumps(manifest))
        self.log.unlink()
        return backup

    def oracle(self):
        return {"match_id": str(uuid4()), "rows": [{"outcome_id": str(uuid4()), "field": "HT"}]}

    def test_success_publishes_private_complete_bundle_without_changing_earlier_backup(self):
        first = create_backup(self.backups, source_service="test_source")
        original = {path.name: path.read_bytes() for path in first.iterdir()}
        second = create_backup(self.backups, source_service="test_source")
        self.assertNotEqual(first, second)
        self.assertEqual(original, {path.name: path.read_bytes() for path in first.iterdir()})
        self.assertEqual({"database.dump", "manifest.json"}, {path.name for path in second.iterdir()})
        self.assertEqual(0o700, stat.S_IMODE(second.stat().st_mode))
        for path in second.iterdir():
            self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))
        manifest = json.loads((second / "manifest.json").read_text())
        self.assertEqual(hashlib.sha256(b"controlled archive").hexdigest(), manifest["sha256"])
        self.assertEqual(1, manifest["version"])
        self.assertIsNone(manifest["reference"])
        self.assertNotIn("test_source", (second / "manifest.json").read_text())
        self.assertFalse(list(self.backups.glob(".incomplete-*")))

    def test_dump_failure_removes_partial_bundle_and_preserves_earlier_backup(self):
        earlier = create_backup(self.backups, source_service="test_source")
        original = (earlier / "database.dump").read_bytes()
        with patch.dict(os.environ, {"BACKUP_TEST_FAIL": "pg_dump"}):
            with self.assertRaises(subprocess.CalledProcessError):
                create_backup(self.backups, source_service="test_source")
        self.assertEqual([earlier], list(self.backups.iterdir()))
        self.assertEqual(original, (earlier / "database.dump").read_bytes())

    def test_archive_check_failure_publishes_nothing(self):
        with patch.dict(os.environ, {"BACKUP_TEST_FAIL": "pg_restore"}):
            with self.assertRaises(subprocess.CalledProcessError):
                create_backup(self.backups, source_service="test_source")
        self.assertEqual([], list(self.backups.iterdir()))

    def test_manifest_write_failure_publishes_nothing(self):
        with patch("json.dump", side_effect=OSError("storage full")):
            with self.assertRaisesRegex(OSError, "storage full"):
                create_backup(self.backups, source_service="test_source")
        self.assertEqual([], list(self.backups.iterdir()))

    def test_publication_failure_preserves_earlier_bundle_and_cleans_staging(self):
        earlier = create_backup(self.backups, source_service="test_source")
        with patch.object(Path, "rename", side_effect=OSError("publication failed")):
            with self.assertRaisesRegex(OSError, "publication failed"):
                create_backup(self.backups, source_service="test_source")
        self.assertEqual([earlier], list(self.backups.iterdir()))

    def test_corrupt_archive_is_rejected_before_any_database_command(self):
        backup = self.bundle(self.oracle())
        (backup / "database.dump").write_bytes(b"corrupted")
        with self.assertRaisesRegex(ValueError, "checksum"):
            verify_backup(backup, restore_service="test_restore")
        self.assertEqual([], self.commands())

    def test_missing_or_empty_oracle_is_rejected_before_any_database_command(self):
        for reference in (None, {"match_id": str(uuid4()), "rows": []}):
            with self.subTest(reference=reference):
                backup = self.bundle(reference)
                with self.assertRaisesRegex(ValueError, "match-id"):
                    verify_backup(backup, restore_service="test_restore")
                self.assertEqual([], self.commands())

    def test_invalid_match_is_rejected_before_dump_or_publication(self):
        with self.assertRaises(ValueError):
            create_backup(self.backups, source_service="test_source", match_id="bad-id")
        self.assertFalse(self.backups.exists())
        self.assertEqual([], self.commands())

    def test_invalid_service_name_is_rejected_before_external_commands(self):
        with self.assertRaises(ValueError):
            create_backup(self.backups, source_service="source password=secret")
        self.assertEqual([], self.commands())

    def test_failed_creation_never_drops_a_database(self):
        backup = self.bundle(self.oracle())
        with patch.dict(os.environ, {"BACKUP_TEST_FAIL": "createdb"}):
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(subprocess.CalledProcessError):
                    verify_backup(backup, restore_service="test_restore")
        self.assertEqual(["createdb"], [call["command"] for call in self.commands()])

    def test_failed_restore_drops_only_the_database_created_by_this_invocation(self):
        backup = self.bundle(self.oracle())
        with patch.dict(os.environ, {"BACKUP_TEST_FAIL": "pg_restore"}):
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(subprocess.CalledProcessError):
                    verify_backup(backup, restore_service="test_restore")
        created, restored, dropped = self.commands()
        self.assertEqual(["createdb", "pg_restore", "dropdb"],
                         [call["command"] for call in (created, restored, dropped)])
        database = created["arguments"][-1]
        self.assertRegex(database, r"^agentic_restore_[0-9a-f]{32}$")
        self.assertEqual(database, dropped["arguments"][-1])

    def test_keep_option_retains_failed_restore_for_inspection(self):
        backup = self.bundle(self.oracle())
        with patch.dict(os.environ, {"BACKUP_TEST_FAIL": "pg_restore"}):
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(subprocess.CalledProcessError):
                    verify_backup(backup, restore_service="test_restore", keep_database=True)
        self.assertEqual(["createdb", "pg_restore"], [call["command"] for call in self.commands()])

    def test_cli_reports_dump_failure_with_nonzero_exit(self):
        output = io.StringIO()
        with patch.dict(os.environ, {"BACKUP_TEST_FAIL": "pg_dump"}):
            with contextlib.redirect_stderr(output):
                with self.assertRaises(SystemExit) as raised:
                    main(["backup", "--directory", str(self.backups),
                          "--source-service", "test_source"])
        self.assertEqual(1, raised.exception.code)
        self.assertIn("Backup operation failed", output.getvalue())
        self.assertEqual([], list(self.backups.iterdir()))

    def test_cli_reports_cleanup_failure_and_identifies_retained_database(self):
        backup = self.bundle(self.oracle())
        output, errors = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {"BACKUP_TEST_FAIL": "pg_restore,dropdb"}):
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                with self.assertRaises(SystemExit) as raised:
                    main(["verify", str(backup), "--restore-service", "test_restore"])
        self.assertEqual(1, raised.exception.code)
        database = self.commands()[0]["arguments"][-1]
        self.assertIn(database, output.getvalue())
        self.assertIn("dropdb", errors.getvalue())
        self.assertNotIn("Verified", output.getvalue())

    def test_unsupported_manifest_is_rejected_before_any_database_command(self):
        backup = self.bundle(self.oracle())
        metadata = backup / "manifest.json"
        manifest = json.loads(metadata.read_text())
        manifest["version"] = 2
        metadata.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            verify_backup(backup, restore_service="test_restore")
        self.assertEqual([], self.commands())


if __name__ == "__main__":
    unittest.main()
