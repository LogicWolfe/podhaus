from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "predeploy-mount-gate"
EXPECTED_UUID = "EAED18A9-74C7-4163-ACB4-406B2226FDC6"

FAKE_DOCKER = r'''#!/bin/sh
set -eu
printf '%s\n' "$*" >> "$FAKE_CALLS"
case "$*" in
    *'cat /sentinel'*) printf '%s\n' "${FAKE_UUID}" ;;
    *'source=/Volumes/TerraMaster/'*',target=/required,'*)
        exit "${FAKE_DIRECTORY_RC:-0}"
        ;;
    *) exit 31 ;;
esac
'''


class MountPredeployGateTest(unittest.TestCase):
    def run_gate(
        self, *paths: str, uuid: str = EXPECTED_UUID, directory_rc: str = "0"
    ) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        with tempfile.TemporaryDirectory() as temporary:
            fake_bin = Path(temporary)
            docker = fake_bin / "docker"
            docker.write_text(FAKE_DOCKER, encoding="utf-8")
            docker.chmod(0o755)
            calls = fake_bin / "calls"
            environment = os.environ.copy()
            environment.update(
                {
                    "FAKE_CALLS": str(calls),
                    "FAKE_UUID": uuid,
                    "FAKE_DIRECTORY_RC": directory_rc,
                    "PATH": f"{fake_bin}:/usr/bin:/bin",
                }
            )
            result = subprocess.run(
                [SCRIPT, *paths],
                text=True,
                capture_output=True,
                check=False,
                env=environment,
            )
            recorded = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
            return result, recorded

    def test_mounts_only_the_sentinel_and_required_directories(self) -> None:
        result, calls = self.run_gate("Movies", "Kids")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 3)
        self.assertIn("source=/Volumes/TerraMaster/.podhaus-terramaster", calls[0])
        self.assertIn("source=/Volumes/TerraMaster/Movies,target=/required", calls[1])
        self.assertIn("source=/Volumes/TerraMaster/Kids,target=/required", calls[2])
        self.assertNotIn("source=/Volumes/TerraMaster,target=", "\n".join(calls))

    def test_wrong_sentinel_fails_before_directory_probes(self) -> None:
        result, calls = self.run_gate("Movies", uuid="wrong")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(calls), 1)

    def test_missing_directory_fails(self) -> None:
        result, _ = self.run_gate("Movies", directory_rc="17")
        self.assertNotEqual(result.returncode, 0)

    def test_invalid_or_missing_path_fails_closed(self) -> None:
        result, calls = self.run_gate()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])

        result, calls = self.run_gate("../Movies")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
