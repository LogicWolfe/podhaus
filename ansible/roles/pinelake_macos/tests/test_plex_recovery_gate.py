from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "files" / "plex-recovery-gate"


class PlexRecoveryGateTest(unittest.TestCase):
    def run_gate(self, pgrep_status: int, lsof_status: int) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary:
            fake_bin = Path(temporary)
            for name, status in (("pgrep", pgrep_status), ("lsof", lsof_status)):
                executable = fake_bin / name
                executable.write_text(f"#!/bin/sh\nexit {status}\n", encoding="utf-8")
                executable.chmod(0o755)
            environment = os.environ.copy()
            environment["PATH"] = f"{fake_bin}:/usr/bin:/bin"
            return subprocess.run(
                [SCRIPT],
                text=True,
                capture_output=True,
                check=False,
                env=environment,
            )

    def test_allows_recovery_only_when_process_and_listener_are_absent(self) -> None:
        result = self.run_gate(pgrep_status=1, lsof_status=1)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("proven dead", result.stdout)

    def test_refuses_when_plex_process_is_alive(self) -> None:
        result = self.run_gate(pgrep_status=0, lsof_status=1)
        self.assertEqual(result.returncode, 1)
        self.assertIn("process", result.stderr)

    def test_refuses_when_port_is_still_listening(self) -> None:
        result = self.run_gate(pgrep_status=1, lsof_status=0)
        self.assertEqual(result.returncode, 1)
        self.assertIn("listener", result.stderr)

    def test_fails_closed_when_process_probe_errors(self) -> None:
        result = self.run_gate(pgrep_status=2, lsof_status=1)
        self.assertEqual(result.returncode, 2)

    def test_fails_closed_when_listener_probe_errors(self) -> None:
        result = self.run_gate(pgrep_status=1, lsof_status=2)
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
