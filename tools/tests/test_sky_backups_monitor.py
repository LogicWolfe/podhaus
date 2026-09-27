import json
import os
import subprocess
import tempfile
import unittest
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "gatus/scripts/check-sky-backups.sh"
SNAPSHOT_ID = "a" * 64


@dataclass(frozen=True)
class MonitorResult:
    process: subprocess.CompletedProcess[str]
    client_arguments: str
    heartbeat_arguments: str


class SkyBackupsMonitorTests(unittest.TestCase):
    def run_monitor(self, fixture, *, rc_exit=0, rc_fail_command=""):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            bin_directory = temporary / "bin"
            bin_directory.mkdir()
            fixture_path = temporary / "objects.json"
            fixture_path.write_text(fixture)
            rc_args_path = temporary / "rc-args"
            curl_args_path = temporary / "curl-args"
            (bin_directory / "rc").write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' \"$@\" > \"$RC_ARGS\"\n"
                "[ \"$1 $2\" != \"$RC_FAIL_COMMAND\" ] || exit \"$RC_EXIT\"\n"
                "case \"$1 $2\" in\n"
                "  'alias set') exit 0 ;;\n"
                "  'object find') cat \"$RC_FIXTURE\" ;;\n"
                "esac\n"
            )
            (bin_directory / "curl").write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' \"$@\" > \"$CURL_ARGS\"\n"
            )
            for command in (bin_directory / "rc", bin_directory / "curl"):
                command.chmod(0o755)

            environment = os.environ | {
                "PATH": f"{bin_directory}:{os.environ['PATH']}",
                "RC_CONFIG_DIR": str(temporary / "rc"),
                "RC_FIXTURE": str(fixture_path),
                "RC_ARGS": str(rc_args_path),
                "RC_EXIT": str(rc_exit),
                "RC_FAIL_COMMAND": rc_fail_command,
                "CURL_ARGS": str(curl_args_path),
                "SKY_BACKUPS_ENDPOINT": "https://pouch.example.test",
                "SKY_BACKUPS_BUCKET": "sky-backups",
                "SKY_BACKUPS_PREFIX": "personal-laptop",
                "SKY_BACKUPS_MAX_AGE": "7d",
                "SKY_BACKUPS_ACCESS_KEY": "access-key",
                "SKY_BACKUPS_SECRET_KEY": "secret-key",
                "GATUS_BASE_URL": "http://gatus.example.test",
                "GATUS_HEARTBEAT_PUSH_TOKEN": "heartbeat-token",
            }
            result = subprocess.run(
                ["sh", str(SCRIPT)],
                capture_output=True,
                text=True,
                env=environment,
            )
            return MonitorResult(
                process=result,
                client_arguments=rc_args_path.read_text() if rc_args_path.exists() else "",
                heartbeat_arguments=curl_args_path.read_text() if curl_args_path.exists() else "",
            )

    def metadata(self, *objects):
        return json.dumps({"matches": list(objects), "total_count": len(objects)})

    def object(self, key, modified):
        return {"key": key, "last_modified": modified}

    def timestamp(self, age):
        return (datetime.now(timezone.utc) - age).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        )

    def test_fresh_committed_snapshot_reports_success_from_rc_json(self):
        result = self.run_monitor(
            self.metadata(
                self.object(
                    f"personal-laptop/snapshots/{SNAPSHOT_ID}", self.timestamp(timedelta(days=1))
                )
            )
        )

        self.assertEqual(result.process.returncode, 0, result.process.stderr)
        self.assertIn("fresh committed snapshot", result.process.stdout)
        self.assertIn("object\nfind\n--json", result.client_arguments)
        self.assertIn("sky-backups-monitor/sky-backups/personal-laptop", result.client_arguments)
        self.assertIn("success=true", result.heartbeat_arguments)

    def test_recent_repository_config_gets_first_backup_grace_window(self):
        result = self.run_monitor(
            self.metadata(self.object("personal-laptop/config", self.timestamp(timedelta(days=1))))
        )

        self.assertEqual(result.process.returncode, 0, result.process.stderr)
        self.assertIn("first-backup grace window", result.process.stdout)
        self.assertIn("success=true", result.heartbeat_arguments)

    def test_stale_snapshot_and_missing_repository_report_failure(self):
        with self.subTest("stale snapshot"):
            result = self.run_monitor(
                self.metadata(
                    self.object(
                        f"personal-laptop/snapshots/{SNAPSHOT_ID}", self.timestamp(timedelta(days=8))
                    )
                )
            )
            self.assertNotEqual(result.process.returncode, 0)
            self.assertIn("Newest committed Restic snapshot", result.process.stderr)
            self.assertIn("success=false", result.heartbeat_arguments)

        with self.subTest("no config or snapshot"):
            result = self.run_monitor(self.metadata())
            self.assertNotEqual(result.process.returncode, 0)
            self.assertIn("no config or committed snapshot", result.process.stderr)
            self.assertIn("success=false", result.heartbeat_arguments)

        with self.subTest("stale configuration"):
            result = self.run_monitor(
                self.metadata(self.object("personal-laptop/config", self.timestamp(timedelta(days=8))))
            )
            self.assertNotEqual(result.process.returncode, 0)
            self.assertIn("repository initialization", result.process.stderr)
            self.assertIn("success=false", result.heartbeat_arguments)

    def test_query_and_parse_failures_never_report_success(self):
        for name, fixture, rc_exit, rc_fail_command in (
            ("query", self.metadata(), 1, "object find"),
            ("malformed json", "not json", 0, ""),
            (
                "missing timestamp",
                self.metadata({"key": f"personal-laptop/snapshots/{SNAPSHOT_ID}"}),
                0,
                "",
            ),
        ):
            with self.subTest(name):
                result = self.run_monitor(
                    fixture, rc_exit=rc_exit, rc_fail_command=rc_fail_command
                )
                self.assertNotEqual(result.process.returncode, 0)
                self.assertNotIn("success=true", result.heartbeat_arguments)


if __name__ == "__main__":
    unittest.main()
