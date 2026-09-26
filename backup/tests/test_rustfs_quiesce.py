import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[2]


class RustfsQuiesceTest(unittest.TestCase):
    def test_stop_failure_is_fatal_before_snapshot(self) -> None:
        result = self.run_control("stop", fail_stop=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.calls, ["stop"])
        self.assertFalse(result.lock_exists)

        rustfs = self.rustfs_plan()
        self.assertEqual(rustfs["hooks"][0]["conditions"], ["CONDITION_SNAPSHOT_START"])
        self.assertEqual(rustfs["hooks"][0]["onError"], "ON_ERROR_FATAL")

    def test_inspection_failure_is_fatal_before_snapshot(self) -> None:
        result = self.run_control("stop", fail_inspect=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.calls, [])
        self.assertFalse(result.lock_exists)

    def test_finish_restarts_rustfs_after_a_failed_snapshot(self) -> None:
        with self.control_environment() as environment:
            stopped = self.execute_control(environment, "stop")
            self.assertEqual(stopped.returncode, 0)
            self.assertFalse(stopped.running)
            self.assertTrue(stopped.lock_exists)

            finished = self.execute_control(environment, "finish")
            self.assertEqual(finished.returncode, 0)
            self.assertTrue(finished.running)
            self.assertFalse(finished.lock_exists)
            self.assertEqual(finished.calls, ["stop", "start"])

        self.assertEqual(self.rustfs_plan()["hooks"][1]["conditions"], ["CONDITION_SNAPSHOT_END"])

    def test_recovery_restarts_rustfs_after_an_interrupted_backup(self) -> None:
        with self.control_environment() as environment:
            self.assertEqual(self.execute_control(environment, "stop").returncode, 0)
            stale = time.time() - 901
            os.utime(environment.lock, (stale, stale))

            recovered = self.execute_control(environment, "recover")
            self.assertEqual(recovered.returncode, 0)
            self.assertTrue(recovered.running)
            self.assertFalse(recovered.lock_exists)
            self.assertEqual(recovered.calls, ["stop", "start"])

    def test_restart_failure_keeps_marker_for_recovery(self) -> None:
        with self.control_environment() as environment:
            self.assertEqual(self.execute_control(environment, "stop").returncode, 0)
            environment.variables["FAIL_START"] = "true"

            finished = self.execute_control(environment, "finish")
            self.assertNotEqual(finished.returncode, 0)
            self.assertFalse(finished.running)
            self.assertTrue(finished.lock_exists)
            self.assertEqual(finished.calls, ["stop", "start"])

    def test_preexisting_stopped_rustfs_remains_stopped(self) -> None:
        with self.control_environment(running=False) as environment:
            self.assertEqual(self.execute_control(environment, "stop").returncode, 0)
            finished = self.execute_control(environment, "finish")
            self.assertEqual(finished.returncode, 0)
            self.assertFalse(finished.running)
            self.assertFalse(finished.lock_exists)
            self.assertEqual(finished.calls, [])

    @staticmethod
    def rustfs_plan() -> dict:
        config = json.loads((ROOT / "backup/bandicoot/config.json.tmpl").read_text())
        return next(plan for plan in config["plans"] if plan["id"] == "rustfs")

    def run_control(
        self, command: str, *, fail_stop: bool = False, fail_inspect: bool = False
    ) -> "ControlResult":
        with self.control_environment(fail_stop=fail_stop, fail_inspect=fail_inspect) as environment:
            return self.execute_control(environment, command)

    def execute_control(self, environment, command: str):
        result = subprocess.run([environment.script, command], env=environment.variables, check=False)
        return ControlResult(
            returncode=result.returncode,
            calls=environment.log.read_text().splitlines(),
            running=environment.state.read_text().strip() == "true",
            lock_exists=environment.lock.exists(),
        )

    def control_environment(
        self, *, running: bool = True, fail_stop: bool = False, fail_inspect: bool = False
    ):
        return ControlEnvironment(
            running=running, fail_stop=fail_stop, fail_inspect=fail_inspect
        )


class ControlResult:
    def __init__(self, *, returncode: int, calls: list[str], running: bool, lock_exists: bool) -> None:
        self.returncode = returncode
        self.calls = calls
        self.running = running
        self.lock_exists = lock_exists


class ControlEnvironment:
    def __init__(self, *, running: bool, fail_stop: bool, fail_inspect: bool) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.state = self.root / "rustfs-state"
        self.state.write_text(f"{str(running).lower()}\n")
        self.log = self.root / "calls"
        self.log.touch()
        self.commands = self.root / "commands"
        self.commands.mkdir()
        self.lock = self.root / "rustfs-backup.lock"
        self.script = self.root / "rustfs-backup-control"
        self.script.write_text(
            (ROOT / "backup/bandicoot/scripts/rustfs-backup-control")
            .read_text()
            .replace("/data/rustfs-backup", str(self.root / "rustfs-backup"))
        )
        self.script.chmod(0o755)
        (self.commands / "docker").write_text(
            "#!/bin/sh\n"
            "case \"$1\" in\n"
            "  inspect) [ \"$FAIL_INSPECT\" != true ] || exit 1; cat \"$RUSTFS_STATE\" ;;\n"
            "  stop)\n"
            "    printf '%s\\n' stop >> \"$CALL_LOG\"\n"
            "    [ \"$FAIL_STOP\" != true ] || exit 1\n"
            "    printf '%s\\n' false > \"$RUSTFS_STATE\"\n"
            "    ;;\n"
            "  start)\n"
            "    printf '%s\\n' start >> \"$CALL_LOG\"\n"
            "    [ \"$FAIL_START\" != true ] || exit 1\n"
            "    printf '%s\\n' true > \"$RUSTFS_STATE\"\n"
            "    ;;\n"
            "esac\n"
        )
        (self.commands / "docker").chmod(0o755)
        self.variables = os.environ | {
            "PATH": f"{self.commands}:{os.environ['PATH']}",
            "RUSTFS_STATE": str(self.state),
            "CALL_LOG": str(self.log),
            "FAIL_STOP": str(fail_stop).lower(),
            "FAIL_INSPECT": str(fail_inspect).lower(),
            "FAIL_START": "false",
        }

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.temporary.cleanup()
