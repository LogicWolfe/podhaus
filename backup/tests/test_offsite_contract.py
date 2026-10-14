"""Jump repositories must have one complete, failure-signalled off-site path."""

import json
from dataclasses import dataclass
from pathlib import Path
import os
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


@dataclass
class SyncRun:
    returncode: int
    calls: list[str]


def template(host: str) -> dict:
    return json.loads((ROOT / "backup" / host / "config.json.tmpl").read_text())


class OffsiteContractTest(unittest.TestCase):
    def test_freshness_gate_checks_every_bandicoot_plan(self) -> None:
        """A plan the gate does not check is mirrored off-site however old it is."""
        run = self.run_sync()
        checked = {call.split(":", 2)[2] for call in run.calls if call.startswith("snapshots:source:")}
        self.assertEqual(checked, {item["id"] for item in template("bandicoot")["plans"]})

    def test_every_bandicoot_plan_snapshots_even_when_unchanged(self) -> None:
        """The gate refuses a plan with no snapshot from today, so a skipped one fails the mirror."""
        for item in template("bandicoot")["plans"]:
            with self.subTest(plan=item["id"]):
                self.assertIs(item["skipIfUnchanged"], False)

    def test_freshness_gate_rejects_missing_or_stale_source_plans(self) -> None:
        plan_id = template("bandicoot")["plans"][0]["id"]
        for failure in (plan_id, f"stale:{plan_id}"):
            with self.subTest(failure=failure):
                run = self.run_sync(
                    missing_plan="" if failure.startswith("stale:") else failure,
                    stale_plan=failure.removeprefix("stale:") if failure.startswith("stale:") else "",
                )
                self.assertNotEqual(run.returncode, 0)
                self.assertEqual(run.calls.count("wget"), 1)
                self.assertNotIn("copy", run.calls)
                self.assertIn("rclone", run.calls)

    def test_fresh_source_copies_forgets_checks_destination_then_uploads(self) -> None:
        run = self.run_sync()
        self.assertEqual(run.returncode, 0)
        self.assertNotIn("wget", run.calls)
        self.assertLess(run.calls.index("copy"), run.calls.index("forget"))
        destination_check = next(
            index for index, call in enumerate(run.calls) if call.startswith("snapshots:destination:")
        )
        self.assertLess(run.calls.index("forget"), destination_check)
        self.assertLess(destination_check, run.calls.index("rclone"))

    def test_copy_failure_still_uploads_and_reports_failure(self) -> None:
        run = self.run_sync(fail_copy=True)
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(run.calls.count("wget"), 1)
        self.assertIn("copy", run.calls)
        self.assertNotIn("forget", run.calls)
        self.assertIn("rclone", run.calls)

    def test_upload_failure_reports_failure(self) -> None:
        run = self.run_sync(fail_rclone=True)
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(run.calls.count("wget"), 1)
        self.assertIn("rclone", run.calls)

    def run_sync(
        self,
        *,
        missing_plan: str = "",
        stale_plan: str = "",
        fail_copy: bool = False,
        fail_rclone: bool = False,
    ) -> SyncRun:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            (source / ".podhaus-share-mounted").touch()
            (destination / ".podhaus-share-mounted").touch()
            log = root / "calls"
            commands = root / "commands"
            commands.mkdir()
            self.write_fake_commands(commands, log)
            copy = root / "sync-bandicoot-copy"
            copy.write_text(
                (ROOT / "backup/bilby/scripts/sync-bandicoot-copy").read_text()
                .replace("/repos/podhaus-bandicoot", str(source))
                .replace("/repos/podhaus", str(destination))
            )
            copy.chmod(0o755)
            executable = root / "sync"
            executable.write_text(
                (ROOT / "backup/bilby/scripts/sync-bandicoot-repository").read_text()
                .replace("/repos/podhaus", str(destination))
                .replace("/hooks/sync-bandicoot-copy", str(copy))
            )
            executable.chmod(0o755)
            result = subprocess.run(
                [executable],
                env=os.environ | {
                    "PATH": f"{commands}:{os.environ['PATH']}",
                    "GATUS_BACKREST_PUSH_TOKEN": "bilby-token",
                    "GATUS_BASE_URL": "http://gatus",
                    "GATUS_BACKREST_ENDPOINT_ID": "bilby",
                    "MISSING_PLAN": missing_plan,
                    "STALE_PLAN": stale_plan,
                    "FAIL_COPY": str(fail_copy).lower(),
                    "FAIL_RCLONE": str(fail_rclone).lower(),
                    "CALL_LOG": str(log),
                },
                check=False,
            )
            return SyncRun(result.returncode, log.read_text().splitlines())

    @staticmethod
    def write_fake_commands(commands: Path, log: Path) -> None:
        (commands / "restic").write_text(
            """#!/bin/sh
set -eu
for argument in "$@"; do
  case "$argument" in
    created-by:bandicoot,plan:*) plan=${argument#*plan:} ;;
  esac
done
case " $* " in
  *" cat config "*)
    case " $* " in
      *"/destination "*) printf '%s\\n' '{"id":"4f9bd4ec0f9b81cbf02e52b05a54892070a13f83c15f1e7c8f1b8578155cef63"}' ;;
      *) printf '%s\\n' '{"id":"af91f4420f462b9a2fe6c5f27ba1259ee3fbf0fb9ecca5629544b8d46b517791"}' ;;
    esac
    ;;
  *" snapshots "*)
    repository=source
    case " $* " in
      *"/destination "*) repository=destination ;;
    esac
    printf 'snapshots:%s:%s\\n' "$repository" "$plan" >> "$CALL_LOG"
    if [ "$plan" = "$MISSING_PLAN" ]; then printf '%s\\n' '[]'; exit 0; fi
    today=$(date +%Y-%m-%d)
    if [ "$plan" = "$STALE_PLAN" ]; then today=$(date -d yesterday +%Y-%m-%d); fi
    printf '[{"time":"%sT04:00:00+08:00","tags":["created-by:bandicoot","plan:%s"]}]\\n' "$today" "$plan"
    ;;
  *" copy "*)
    printf '%s\\n' copy >> "$CALL_LOG"
    [ "$FAIL_COPY" != true ] || exit 1
    ;;
  *" forget "*) printf '%s\\n' forget >> "$CALL_LOG" ;;
esac
"""
        )
        (commands / "rclone").write_text(
            "#!/bin/sh\nprintf '%s\\n' rclone >> \"$CALL_LOG\"\n"
            "[ \"$FAIL_RCLONE\" != true ] || exit 1\n"
        )
        (commands / "wget").write_text("#!/bin/sh\nprintf '%s\\n' wget >> \"$CALL_LOG\"\n")
        for command in commands.iterdir():
            command.chmod(0o755)


if __name__ == "__main__":
    unittest.main()
