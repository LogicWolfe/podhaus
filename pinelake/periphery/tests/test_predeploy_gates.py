from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "predeploy-plex-gate"


FAKE_DOCKER = r'''#!/bin/sh
set -eu
if [ "$1 $2" = "container inspect" ]; then
    if [ "${FAKE_STATE:-absent}" = absent ]; then
        exit 1
    fi
    printf '%s\n' "$FAKE_STATE"
    exit 0
fi
if [ "$1 $2" = "container ls" ]; then
    [ "${FAKE_LISTED:-false}" = true ] && echo pinelake-plex
    exit 0
fi
case "$*" in
    *'/tools/plex-session-gate'*)
        case "$*" in
            *--validate-only*) exit "${FAKE_IDENTITY_RC:-0}" ;;
        esac
        count=$(cat "$FAKE_COUNT")
        count=$((count + 1))
        echo "$count" > "$FAKE_COUNT"
        exit "${FAKE_SESSION_RC:-0}"
        ;;
    *'python3 -c'*) exit "${FAKE_PORT_RC:-0}" ;;
    *) exit "${FAKE_READY_RC:-0}" ;;
esac
'''


class PlexPredeployGateTest(unittest.TestCase):
    def run_gate(self, **values: str) -> tuple[subprocess.CompletedProcess[str], int]:
        with tempfile.TemporaryDirectory() as temporary:
            fake_bin = Path(temporary)
            docker = fake_bin / "docker"
            docker.write_text(FAKE_DOCKER, encoding="utf-8")
            docker.chmod(0o755)
            count = fake_bin / "count"
            count.write_text("0\n", encoding="utf-8")
            environment = os.environ.copy()
            environment.update(values)
            environment["FAKE_COUNT"] = str(count)
            environment["PATH"] = f"{fake_bin}:/usr/bin:/bin"
            result = subprocess.run(
                [SCRIPT], text=True, capture_output=True, check=False, env=environment
            )
            return result, int(count.read_text())

    def test_running_container_requires_two_zero_session_checks(self) -> None:
        result, count = self.run_gate(FAKE_STATE="true")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(count, 2)

    def test_running_container_blocks_an_active_session(self) -> None:
        result, count = self.run_gate(FAKE_STATE="true", FAKE_SESSION_RC="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(count, 1)

    def test_stopped_container_requires_a_closed_port(self) -> None:
        result, count = self.run_gate(FAKE_STATE="false", FAKE_PORT_RC="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(count, 0)

    def test_absent_container_and_closed_port_allows_initial_cutover(self) -> None:
        result, count = self.run_gate(FAKE_STATE="absent", FAKE_PORT_RC="0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(count, 0)

    def test_inspect_failure_for_a_listed_container_fails_closed(self) -> None:
        result, _ = self.run_gate(FAKE_STATE="absent", FAKE_LISTED="true")
        self.assertNotEqual(result.returncode, 0)

    def test_missing_preferences_or_cutover_marker_fails_closed(self) -> None:
        result, _ = self.run_gate(FAKE_READY_RC="1", FAKE_STATE="true")
        self.assertNotEqual(result.returncode, 0)

    def test_identity_mismatch_blocks_initial_cutover(self) -> None:
        result, count = self.run_gate(
            FAKE_STATE="absent", FAKE_IDENTITY_RC="2"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
