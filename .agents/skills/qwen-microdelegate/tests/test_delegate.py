"""Behavioral tests for the local microdelegation helper; Ollama is mocked."""

import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "delegate.py"
spec = importlib.util.spec_from_file_location("qwen_delegate", SCRIPT)
delegate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(delegate)


class DelegateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / ".git").mkdir()
        (self.root / "src").mkdir()
        (self.root / "proposals").mkdir()
        self.source = self.root / "src" / "users.py"
        self.source.write_text("def normalize(users):\n    return users\n", encoding="utf-8")
        self.old_cwd = Path.cwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.temp.cleanup()

    def model_reply(self, old="    return users\n", new="    return users or []\n"):
        content = json.dumps({"summary": "Handle missing users", "edits": [
            {"old_text": old, "new_text": new}
        ]})
        return io.BytesIO(json.dumps({"message": {"content": content}}).encode())

    def run_command(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = delegate.main(list(args))
        return status, out.getvalue(), err.getvalue()

    def propose(self):
        with patch.object(delegate.urllib.request, "urlopen", return_value=self.model_reply()) as send:
            status, output, error = self.run_command(
                "propose", "--task", "Return [] for missing users",
                "--file", "src/users.py", "--output", "proposals/task.json"
            )
        return status, output, error, send

    def test_successful_proposal_check_and_apply(self):
        status, output, error, send = self.propose()
        self.assertEqual((status, error), (0, ""))
        self.assertIn("+    return users or []", output)
        self.assertEqual(self.source.read_text(), "def normalize(users):\n    return users\n")
        request = send.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(payload["model"], "qwen2.5-coder:7b")
        self.assertEqual(payload["options"]["temperature"], 0)
        self.assertEqual(self.run_command("check", "--proposal", "proposals/task.json")[0], 0)
        self.assertEqual(self.run_command("apply", "--proposal", "proposals/task.json")[0], 0)
        self.assertIn("return users or []", self.source.read_text())

    def test_invalid_model_response_leaves_source_and_no_proposal(self):
        bad = io.BytesIO(b'{"message": {"content": "not json"}}')
        with patch.object(delegate.urllib.request, "urlopen", return_value=bad):
            status, _, error = self.run_command(
                "propose", "--task", "Add guard", "--file", "src/users.py",
                "--output", "proposals/task.json"
            )
        self.assertEqual(status, 1)
        self.assertIn("invalid JSON", error)
        self.assertFalse((self.root / "proposals/task.json").exists())
        self.assertIn("return users\n", self.source.read_text())

    def test_missing_source(self):
        status, _, error = self.run_command(
            "propose", "--task", "Add guard", "--file", "src/missing.py",
            "--output", "proposals/task.json"
        )
        self.assertEqual(status, 1)
        self.assertIn("does not exist", error)

    def test_outside_and_symlink_paths(self):
        outside = self.root.parent / "other.py"
        status, _, error = self.run_command(
            "propose", "--task", "Add guard", "--file", str(outside),
            "--output", "proposals/task.json"
        )
        self.assertEqual(status, 1)
        self.assertIn("outside", error)
        try:
            (self.root / "linked").symlink_to(self.root / "src", target_is_directory=True)
        except OSError:
            return  # Windows may require Developer Mode to create symlinks.
        status, _, error = self.run_command(
            "propose", "--task", "Add guard", "--file", "linked/users.py",
            "--output", "proposals/task.json"
        )
        self.assertEqual(status, 1)
        self.assertIn("Symlink", error)

    def test_git_metadata_path_is_rejected(self):
        (self.root / ".git" / "config").write_text("private metadata")
        status, _, error = self.run_command(
            "propose", "--task", "Edit config", "--file", ".git/config",
            "--output", "proposals/task.json"
        )
        self.assertEqual(status, 1)
        self.assertIn("Git metadata", error)

    def test_cloud_model_is_rejected(self):
        with patch.dict(os.environ, {"QWEN_MODEL": "qwen2.5-coder:cloud"}):
            status, _, error = self.run_command(
                "propose", "--task", "Add guard", "--file", "src/users.py",
                "--output", "proposals/task.json"
            )
        self.assertEqual(status, 1)
        self.assertIn("local Ollama model", error)

    def test_stale_proposal(self):
        self.assertEqual(self.propose()[0], 0)
        self.source.write_text("def normalize(users):\n    return tuple(users)\n")
        status, _, error = self.run_command("apply", "--proposal", "proposals/task.json")
        self.assertEqual(status, 1)
        self.assertIn("Stale proposal", error)
        self.assertIn("tuple(users)", self.source.read_text())

    def test_failed_exact_match_replacement(self):
        proposal = {
            "schema_version": 1, "task": "Guard", "file": "src/users.py",
            "base_sha256": hashlib.sha256(self.source.read_bytes()).hexdigest(),
            "excerpt": self.source.read_text(),
            "result": {"summary": "Bad edit", "edits": [
                {"old_text": "return missing", "new_text": "return []"}
            ]},
        }
        (self.root / "proposals/task.json").write_text(json.dumps(proposal))
        status, _, error = self.run_command("apply", "--proposal", "proposals/task.json")
        self.assertEqual(status, 1)
        self.assertIn("match exactly once", error)
        self.assertIn("return users\n", self.source.read_text())

    def test_connection_failure(self):
        with patch.object(delegate.urllib.request, "urlopen",
                          side_effect=urllib.error.URLError("offline")):
            status, _, error = self.run_command(
                "propose", "--task", "Add guard", "--file", "src/users.py",
                "--output", "proposals/task.json"
            )
        self.assertEqual(status, 1)
        self.assertIn("request failed", error)

    def test_timeout(self):
        with patch.object(delegate.urllib.request, "urlopen", side_effect=TimeoutError()):
            status, _, error = self.run_command(
                "propose", "--task", "Add guard", "--file", "src/users.py",
                "--output", "proposals/task.json"
            )
        self.assertEqual(status, 1)
        self.assertIn("request failed", error)

    def test_edit_outside_selected_excerpt_is_rejected(self):
        with patch.object(delegate.urllib.request, "urlopen", return_value=self.model_reply()):
            status, _, error = self.run_command(
                "propose", "--task", "Add guard", "--file", "src/users.py",
                "--start-line", "1", "--end-line", "1",
                "--output", "proposals/task.json"
            )
        self.assertEqual(status, 1)
        self.assertIn("match exactly once", error)


if __name__ == "__main__":
    unittest.main()
