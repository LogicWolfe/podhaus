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


def plan(config: dict, plan_id: str) -> dict:
    return next(item for item in config["plans"] if item["id"] == plan_id)


class OffsiteContractTest(unittest.TestCase):
    def test_every_jump_repository_reaches_onedrive_without_a_second_bandicoot_writer(self) -> None:
        bilby = plan(template("bilby"), "backrest-state")
        kangaroo = plan(template("kangaroo"), "backrest-state")
        bandicoot = plan(template("bandicoot"), "backrest-state")

        bilby_commands = [hook["actionCommand"]["command"] for hook in bilby["hooks"]]
        kangaroo_commands = [hook["actionCommand"]["command"] for hook in kangaroo["hooks"]]
        self.assertEqual(bilby_commands[0], "/hooks/sync-bandicoot-repository")
        self.assertIn("onedrive:Backups/podhaus-kangaroo-restic", kangaroo_commands[0])
        self.assertEqual(
            bandicoot["hooks"][0]["conditions"],
            ["CONDITION_SNAPSHOT_SUCCESS", "CONDITION_SNAPSHOT_SKIPPED"],
        )
        self.assertIn(
            "${GATUS_BACKREST_ENDPOINT_ID}/external?success=true",
            bandicoot["hooks"][0]["actionCommand"]["command"],
        )
        self.assertIn(
            "success=false&error=backrest+{{ .Task }}+failed",
            template("bandicoot")["repos"][0]["hooks"][0]["actionCommand"]["command"],
        )

        bilby_compose = (ROOT / "backup/bilby/compose.yaml").read_text()
        self.assertIn("/mnt/jump/backups-bandicoot:/repos/podhaus-bandicoot", bilby_compose)
        self.assertNotIn("/mnt/jump/backups-bandicoot:/repos/podhaus-bandicoot:ro", bilby_compose)

    def test_bandicoot_copy_is_bounded_fresh_and_reports_failures_before_success(self) -> None:
        script = (ROOT / "backup/bilby/scripts/sync-bandicoot-repository").read_text()
        copy_script = (ROOT / "backup/bilby/scripts/sync-bandicoot-copy").read_text()
        expected_plans = {item["id"] for item in template("bandicoot")["plans"]}
        self.assertEqual(
            set(copy_script.split("expected_plans=", 1)[1].splitlines()[0].strip("'\"").split()),
            expected_plans,
        )
        self.assertIn('"created-by:bandicoot,plan:$plan"', copy_script)
        self.assertNotIn("--latest 1", copy_script)
        self.assertIn("--group-by host,paths,tags", copy_script)
        self.assertIn("--keep-daily 14 --keep-weekly 4 --keep-monthly 6", copy_script)
        self.assertNotIn("--prune", copy_script)
        self.assertNotIn("--no-lock", copy_script)
        self.assertIn("if /hooks/sync-bandicoot-copy", script)
        self.assertEqual(script.count("success=false&error=offsite+mirror+failed"), 1)
        self.assertNotIn("GATUS_BANDICOOT", script)

        hooks = plan(template("bilby"), "backrest-state")["hooks"]
        self.assertEqual(hooks[0]["onError"], "ON_ERROR_FATAL")
        self.assertEqual(hooks[1]["onError"], "ON_ERROR_IGNORE")
        self.assertEqual(len(hooks), 2)
        for hook in hooks:
            self.assertEqual(
                hook["conditions"],
                ["CONDITION_SNAPSHOT_SUCCESS", "CONDITION_SNAPSHOT_SKIPPED"],
            )
        self.assertNotIn("GATUS_BANDICOOT", (ROOT / "backup/bilby/compose.yaml").read_text())
        self.assertNotIn("GATUS_BANDICOOT", (ROOT / "backup/bilby/stack.toml").read_text())

        dockerfile = (ROOT / "backup/bilby/Backrest.Dockerfile").read_text()
        self.assertIn("apk add --no-cache jq", dockerfile)

    def test_rustfs_replaces_active_minio_and_pets_asset_binds(self) -> None:
        bandicoot = template("bandicoot")
        rustfs = plan(bandicoot, "rustfs")
        self.assertEqual(rustfs["paths"], ["/userdata/rustfs"])
        self.assertEqual(
            rustfs["retention"]["policyTimeBucketed"],
            {"daily": 14, "weekly": 4, "monthly": 6},
        )
        self.assertTrue(all(item["skipIfUnchanged"] is False for item in bandicoot["plans"]))

        bilby = template("bilby")
        self.assertNotIn("minio", {item["id"] for item in bilby["plans"]})
        bilby_compose = (ROOT / "backup/bilby/compose.yaml").read_text()
        self.assertNotIn("/var/lib/minio:/userdata/minio", bilby_compose)
        self.assertNotIn("/var/lib/minio/pets-alive-assets", bilby_compose)
        self.assertEqual(plan(bilby, "pets")["paths"], ["/userdata/pets"])

    def test_freshness_gate_rejects_missing_or_stale_source_plans(self) -> None:
        for failure in ("rustfs", "stale:rustfs"):
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
