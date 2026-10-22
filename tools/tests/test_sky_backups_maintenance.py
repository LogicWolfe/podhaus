import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "sky-backups/scripts/maintain.sh"


class SkyBackupsMaintenanceTests(unittest.TestCase):
    def run_maintenance(self, *arguments, month="10"):
        """Run the script against stub restic, flock and date commands and
        return the process plus every restic invocation, one per line."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            bin_directory = temporary / "bin"
            bin_directory.mkdir()
            calls_path = temporary / "restic-calls"
            stubs = {
                "restic": 'printf \'%s\\n\' "$*" >> "$RESTIC_CALLS"\n',
                "flock": "exit 0\n",
                "date": 'case "$1" in +%Y) echo 2026 ;; +%m) echo "$STUB_MONTH" ;; esac\n',
            }
            for name, body in stubs.items():
                stub = bin_directory / name
                stub.write_text("#!/bin/sh\n" + body)
                stub.chmod(0o755)

            environment = os.environ | {
                "PATH": f"{bin_directory}:{os.environ['PATH']}",
                "RESTIC_CALLS": str(calls_path),
                "STUB_MONTH": month,
                "RESTIC_REPOSITORY": "s3:https://pouch.example.test/sky-backups/personal-laptop",
                "RESTIC_PASSWORD": "repository-password",
                "AWS_ACCESS_KEY_ID": "access-key",
                "AWS_SECRET_ACCESS_KEY": "secret-key",
            }
            process = subprocess.run(
                ["sh", str(SCRIPT), *arguments],
                capture_output=True,
                text=True,
                env=environment,
            )
            calls = calls_path.read_text().splitlines() if calls_path.exists() else []
            return process, calls

    def test_prune_clears_abandoned_locks_first(self):
        process, calls = self.run_maintenance("prune")

        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(calls, ["unlock", "--retry-lock 1h prune"])

    def test_read_subset_rotates_through_august_and_september(self):
        august, august_calls = self.run_maintenance("read-subset", month="08")
        september, september_calls = self.run_maintenance("read-subset", month="09")

        self.assertEqual(august.returncode, 0, august.stderr)
        self.assertEqual(september.returncode, 0, september.stderr)
        self.assertEqual(august_calls[-1], "--retry-lock 1h check --read-data-subset=1/10")
        self.assertEqual(september_calls[-1], "--retry-lock 1h check --read-data-subset=2/10")

    def test_unknown_operation_never_touches_the_repository(self):
        process, calls = self.run_maintenance("forget")

        self.assertEqual(process.returncode, 64)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
