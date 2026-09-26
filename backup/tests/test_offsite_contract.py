"""Jump repositories must have one complete, failure-signalled off-site path."""

import json
from pathlib import Path
import os
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


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
        self.assertEqual(bandicoot["hooks"], [])

        bilby_compose = (ROOT / "backup/bilby/compose.yaml").read_text()
        self.assertIn("/mnt/jump/backups-bandicoot:/repos/podhaus-bandicoot", bilby_compose)
        self.assertNotIn("/mnt/jump/backups-bandicoot:/repos/podhaus-bandicoot:ro", bilby_compose)

    def test_bandicoot_copy_is_bounded_fresh_and_reports_failures_before_success(self) -> None:
        script = (ROOT / "backup/bilby/scripts/sync-bandicoot-repository").read_text()
        expected_plans = {
            "clickstack-mongo", "rustfs", "backrest-state", "komodo",
            "onepassword", "metube", "sonarr", "fenwick",
        }
        self.assertEqual(
            set(script.split("expected_plans=", 1)[1].splitlines()[0].strip("'\"").split()),
            expected_plans,
        )
        self.assertIn('"created-by:bandicoot,plan:$plan"', script)
        self.assertNotIn("--latest 1", script)
        self.assertIn("--group-by host,paths,tags", script)
        self.assertIn("--keep-daily 14 --keep-weekly 4 --keep-monthly 6 --prune", script)
        self.assertNotIn("--no-lock", script)
        self.assertLess(
            script.index('restic -r "$destination_repository" --retry-lock 1h copy'),
            script.index("rclone sync"),
        )
        self.assertEqual(script.count("success=false&error=offsite+mirror+failed"), 2)

        hooks = plan(template("bilby"), "backrest-state")["hooks"]
        self.assertEqual(hooks[0]["onError"], "ON_ERROR_FATAL")
        self.assertEqual(hooks[1]["onError"], "ON_ERROR_IGNORE")
        self.assertEqual(hooks[2]["onError"], "ON_ERROR_IGNORE")
        for hook in hooks:
            self.assertEqual(
                hook["conditions"],
                ["CONDITION_SNAPSHOT_SUCCESS", "CONDITION_SNAPSHOT_SKIPPED"],
            )

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
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
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
                script = (ROOT / "backup/bilby/scripts/sync-bandicoot-repository").read_text()
                script = script.replace("/repos/podhaus-bandicoot", str(source))
                script = script.replace("/repos/podhaus", str(destination))
                executable = root / "sync"
                executable.write_text(script)
                executable.chmod(0o755)

                environment = os.environ | {
                    "PATH": f"{commands}:{os.environ['PATH']}",
                    "GATUS_BACKREST_PUSH_TOKEN": "bilby-token",
                    "GATUS_BANDICOOT_PUSH_TOKEN": "bandicoot-token",
                    "GATUS_BASE_URL": "http://gatus",
                    "GATUS_BACKREST_ENDPOINT_ID": "bilby",
                    "GATUS_BACKREST_BANDICOOT_ENDPOINT_ID": "bandicoot",
                    "MISSING_PLAN": "" if failure.startswith("stale:") else failure,
                    "STALE_PLAN": failure.removeprefix("stale:") if failure.startswith("stale:") else "",
                    "CALL_LOG": str(log),
                }
                result = subprocess.run([executable], env=environment, check=False)
                self.assertNotEqual(result.returncode, 0)
                calls = log.read_text().splitlines()
                self.assertEqual(calls.count("wget"), 2)
                self.assertNotIn("rclone", calls)

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
      *" /destination "*) printf '%s\\n' '{"id":"4f9bd4ec0f9b81cbf02e52b05a54892070a13f83c15f1e7c8f1b8578155cef63"}' ;;
      *) printf '%s\\n' '{"id":"af91f4420f462b9a2fe6c5f27ba1259ee3fbf0fb9ecca5629544b8d46b517791"}' ;;
    esac
    ;;
  *" snapshots "*)
    if [ "$plan" = "$MISSING_PLAN" ]; then printf '%s\\n' '[]'; exit 0; fi
    today=$(date +%Y-%m-%d)
    if [ "$plan" = "$STALE_PLAN" ]; then today=$(date -d yesterday +%Y-%m-%d); fi
    printf '[{"time":"%sT04:00:00+08:00","tags":["created-by:bandicoot","plan:%s"]}]\\n' "$today" "$plan"
    ;;
  *" copy "*) printf '%s\\n' copy >> "$CALL_LOG" ;;
  *" forget "*) printf '%s\\n' forget >> "$CALL_LOG" ;;
esac
"""
        )
        for name in ("rclone", "wget"):
            (commands / name).write_text(f"#!/bin/sh\nprintf '%s\\n' {name} >> \"$CALL_LOG\"\n")
        for command in commands.iterdir():
            command.chmod(0o755)


if __name__ == "__main__":
    unittest.main()
