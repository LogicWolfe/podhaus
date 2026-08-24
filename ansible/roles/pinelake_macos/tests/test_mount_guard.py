#!/usr/bin/env python3
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROLE_DIR = Path(__file__).resolve().parents[1]
SCRIPT = ROLE_DIR / "files" / "pinelake-mount-guard"
EXPECTED_UUID = "EAED18A9-74C7-4163-ACB4-406B2226FDC6"


class MountGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.mount = self.root / "TerraMaster"
        self.mount.mkdir()
        (self.mount / ".podhaus-terramaster").write_text(
            f"{EXPECTED_UUID}\n", encoding="utf-8"
        )
        for relative in ("Movies", "TV", "Sports", "Torrents"):
            (self.mount / relative).mkdir()

        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        self._write_executable(
            "diskutil", '#!/bin/sh\ncat "$FAKE_DISKUTIL_PLIST"\n'
        )
        self._write_executable(
            "docker",
            '#!/usr/bin/env python3\nimport os, sys\n'
            'sys.exit(int(os.environ.get("FAKE_DOCKER_EXIT", "0")))\n',
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _write_executable(self, name: str, content: str) -> None:
        path = self.bin_dir / name
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)

    def _run(
        self,
        *,
        plist_overrides: dict[str, object] | None = None,
        container_check: bool = False,
        docker_exit: int = 0,
        initialize_sentinel: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        info: dict[str, object] = {
            "MountPoint": str(self.mount),
            "VolumeUUID": EXPECTED_UUID,
            "Writable": True,
            "FilesystemType": "apfs",
        }
        info.update(plist_overrides or {})
        plist_path = self.root / "disk.plist"
        with plist_path.open("wb") as stream:
            plistlib.dump(info, stream)

        command = [
            sys.executable,
            str(SCRIPT),
            "--mount-point",
            str(self.mount),
            "--volume-uuid",
            EXPECTED_UUID,
            "--sentinel",
            ".podhaus-terramaster",
        ]
        for relative in ("Movies", "TV", "Sports", "Torrents"):
            command.extend(["--require", relative])
        if container_check:
            command.append("--container-check")
        if initialize_sentinel:
            command.append("--initialize-sentinel")

        env = os.environ.copy()
        env["PATH"] = f"{self.bin_dir}{os.pathsep}{env['PATH']}"
        env["FAKE_DISKUTIL_PLIST"] = str(plist_path)
        env["FAKE_DOCKER_EXIT"] = str(docker_exit)
        return subprocess.run(
            command,
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )

    def test_accepts_exact_writable_volume_and_required_paths(self) -> None:
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("TerraMaster guard passed", result.stdout)

    def test_rejects_wrong_uuid(self) -> None:
        result = self._run(plist_overrides={"VolumeUUID": "WRONG"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("UUID", result.stderr)

    def test_rejects_read_only_volume(self) -> None:
        result = self._run(plist_overrides={"Writable": False})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("writable", result.stderr)

    def test_rejects_missing_sentinel(self) -> None:
        (self.mount / ".podhaus-terramaster").unlink()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("sentinel", result.stderr)

    def test_rejects_sentinel_for_another_volume(self) -> None:
        (self.mount / ".podhaus-terramaster").write_text(
            "another-volume\n", encoding="utf-8"
        )
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("sentinel", result.stderr)

    def test_initializes_only_a_missing_sentinel_after_volume_checks(self) -> None:
        sentinel = self.mount / ".podhaus-terramaster"
        sentinel.unlink()
        result = self._run(initialize_sentinel=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), f"{EXPECTED_UUID}\n")

        sentinel.write_text("another-volume\n", encoding="utf-8")
        result = self._run(initialize_sentinel=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "another-volume\n")

    def test_rejects_required_path_that_escapes_mount(self) -> None:
        (self.mount / "Movies").rmdir()
        (self.mount / "Movies").symlink_to(self.root)
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("escapes", result.stderr)

    def test_checks_global_container_view_without_naming_a_context(self) -> None:
        result = self._run(container_check=True)
        self.assertEqual(result.returncode, 0, result.stderr)

        result = self._run(container_check=True, docker_exit=17)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("container", result.stderr)


if __name__ == "__main__":
    unittest.main()
