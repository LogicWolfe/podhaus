from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "files" / "plex-deploy-gate"


class PlexDeployGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.tools = Path(self.temporary.name)
        self.preferences = self.tools / "Preferences.xml"
        self.preferences.write_text("<Preferences />", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def executable(self, name: str, body: str) -> None:
        path = self.tools / name
        path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        path.chmod(0o755)

    def run_gate(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                SCRIPT,
                "--preferences-xml", str(self.preferences),
                "--tools-dir", str(self.tools),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_requires_two_successful_session_checks(self) -> None:
        counter = self.tools / "count"
        self.executable(
            "plex-session-gate",
            'case "$*" in *--validate-only*) exit 0;; esac; '
            f"n=$(cat {counter} 2>/dev/null || echo 0); n=$((n+1)); "
            f"echo $n > {counter}; test $n -le 2",
        )
        self.executable("plex-recovery-gate", "exit 1")
        self.assertEqual(self.run_gate().returncode, 0)
        self.assertEqual(counter.read_text().strip(), "2")

    def test_active_session_refuses(self) -> None:
        self.executable(
            "plex-session-gate",
            'case "$*" in *--validate-only*) exit 0;; esac; '
            "echo active >&2; exit 1",
        )
        self.executable("plex-recovery-gate", "echo process-alive >&2; exit 1")
        result = self.run_gate()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("active", result.stderr)

    def test_proven_dead_allows_recovery(self) -> None:
        self.executable(
            "plex-session-gate",
            'case "$*" in *--validate-only*) exit 0;; esac; '
            "echo unavailable >&2; exit 2",
        )
        self.executable("plex-recovery-gate", "echo proven-dead; exit 0")
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("proven-dead", result.stdout)

    def test_live_but_unresponsive_refuses(self) -> None:
        self.executable(
            "plex-session-gate",
            'case "$*" in *--validate-only*) exit 0;; esac; '
            "echo unavailable >&2; exit 2",
        )
        self.executable("plex-recovery-gate", "echo listener-alive >&2; exit 1")
        result = self.run_gate()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("listener-alive", result.stderr)

    def test_identity_mismatch_refuses_proven_dead_recovery(self) -> None:
        self.executable("plex-session-gate", "echo wrong-identity >&2; exit 2")
        self.executable("plex-recovery-gate", "echo proven-dead; exit 0")
        result = self.run_gate()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("wrong-identity", result.stderr)


if __name__ == "__main__":
    unittest.main()
