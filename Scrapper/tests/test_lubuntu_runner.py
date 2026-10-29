"""Launcher command behavior with controlled logind/display responses.

This proves guard and exit-code behavior, not a real Lubuntu graphical login.
"""

import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest


@unittest.skipUnless(os.name == "posix" and shutil.which("bash") and shutil.which("timeout"),
                     "POSIX, bash and timeout are required")
class LubuntuRunnerTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.runner = self.root / "run_lubuntu_minute.sh"
        shutil.copy2(Path(__file__).resolve().parents[1] / self.runner.name, self.runner)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.python_log = self.root / "python.log"
        self.environment = os.environ | {
            "PATH": str(self.bin) + os.pathsep + os.defpath,
            "DISPLAY": ":7", "RUNNER_TEST_UID": str(os.getuid()),
            "RUNNER_TEST_PYTHON_LOG": str(self.python_log),
            "RUNNER_TEST_REMOTE": "no", "RUNNER_TEST_TYPE": "x11",
            "RUNNER_TEST_DISPLAY": ":7", "RUNNER_TEST_ACTIVE": "yes",
            "RUNNER_TEST_PYTHON_EXIT": "0", "RUNNER_TEST_DISPLAY_EXIT": "0",
            "RUNNER_TEST_LOGIND_EXIT": "0", "RUNNER_TEST_NO_SESSIONS": "no",
        }
        self.executable(self.bin / "loginctl", '''#!/bin/bash
if [[ $RUNNER_TEST_LOGIND_EXIT != 0 ]]; then exit "$RUNNER_TEST_LOGIND_EXIT"; fi
if [[ $1 == list-sessions ]]; then
    [[ $RUNNER_TEST_NO_SESSIONS != yes ]] || exit 0
    printf 'session %s user seat0 tty1\n' "$RUNNER_TEST_UID"
else
    printf 'User=%s\nActive=%s\nRemote=%s\nType=%s\nDisplay=%s\n' \
        "$RUNNER_TEST_UID" "$RUNNER_TEST_ACTIVE" "$RUNNER_TEST_REMOTE" \
        "$RUNNER_TEST_TYPE" "$RUNNER_TEST_DISPLAY"
fi
''')
        self.executable(self.bin / "xdpyinfo", '#!/bin/bash\nexit "$RUNNER_TEST_DISPLAY_EXIT"\n')
        python = self.root / ".venv" / "bin" / "python"
        python.parent.mkdir(parents=True)
        self.executable(python, '''#!/bin/bash
printf '%s\n' "$PWD" "$@" > "$RUNNER_TEST_PYTHON_LOG"
exit "$RUNNER_TEST_PYTHON_EXIT"
''')

    def executable(self, path, script):
        path.write_text(script)
        path.chmod(0o700)

    def run_launcher(self, *arguments, **environment):
        return subprocess.run(["bash", str(self.runner), *arguments],
                              env=self.environment | environment, cwd=self.bin,
                              capture_output=True, text=True, timeout=10)

    def test_absent_display_skips_before_python_for_check_and_direct_runner(self):
        for arguments in ((), ("--check-session",)):
            with self.subTest(arguments=arguments):
                result = self.run_launcher(*arguments, DISPLAY="")
                self.assertEqual(1, result.returncode, result.stderr)
                self.assertIn("DISPLAY is not set", result.stdout)
                self.assertFalse(self.python_log.exists())

    def test_logout_stale_display_ssh_and_inactive_sessions_skip_before_python(self):
        scenarios = [
            {"RUNNER_TEST_NO_SESSIONS": "yes"},
            {"RUNNER_TEST_REMOTE": "yes"},
            {"RUNNER_TEST_TYPE": "tty"},
            {"RUNNER_TEST_ACTIVE": "no"},
            {"RUNNER_TEST_DISPLAY": ":8"},
            {"RUNNER_TEST_DISPLAY_EXIT": "1"},
            {"RUNNER_TEST_LOGIND_EXIT": "1"},
            {"RUNNER_TEST_UID": str(os.getuid() + 1)},
        ]
        for scenario in scenarios:
            for arguments in ((), ("--check-session",)):
                with self.subTest(scenario=scenario, arguments=arguments):
                    result = self.run_launcher(*arguments, **scenario)
                    self.assertEqual(1, result.returncode, result.stderr)
                    self.assertFalse(self.python_log.exists())

    def test_valid_session_check_does_not_launch_python(self):
        result = self.run_launcher("--check-session")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse(self.python_log.exists())

    def test_direct_runner_executes_existing_cli_once_in_scrapper_directory(self):
        result = self.run_launcher()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([str(self.root), "-u", "generate_instance.py"],
                         self.python_log.read_text().splitlines())

    def test_display_screen_suffix_matches_the_same_x_server(self):
        result = self.run_launcher("--check-session", DISPLAY=":7.0")
        self.assertEqual(0, result.returncode, result.stderr)

    def test_scraper_failure_reaches_the_calling_service(self):
        result = self.run_launcher(RUNNER_TEST_PYTHON_EXIT="23")
        self.assertEqual(23, result.returncode, result.stderr)
        self.assertTrue(self.python_log.exists())

    def test_invalid_arguments_do_not_launch_python(self):
        result = self.run_launcher("--check-session", "unexpected")
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertFalse(self.python_log.exists())


if __name__ == "__main__":
    unittest.main()
