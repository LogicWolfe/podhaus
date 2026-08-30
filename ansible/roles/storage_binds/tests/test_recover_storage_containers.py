import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROLE = Path(__file__).resolve().parents[1]
RECOVERY_COMMAND = ROLE / "files" / "recover-storage-containers"

NAS_VOLUMES = [
    {"root": "/mnt/jump", "source": "10.0.0.25:/Jump", "fstypes": ["nfs", "nfs4"]},
    {"root": "/mnt/pouch", "source": "10.0.0.25:/Pouch", "fstypes": ["nfs", "nfs4"]},
]

# fractal: one hand-unlocked LUKS volume, no NFS anywhere.
VAULT_VOLUMES = [
    {"root": "/home", "source": "/dev/mapper/vault", "fstypes": ["ext4"]},
]


def container(
    name: str,
    sources: list[str],
    *,
    status: str = "exited",
    error: str | None = None,
    restart: str = "unless-stopped",
    autoheal: bool = True,
) -> dict[str, object]:
    mount_error = (
        f'OCI runtime create failed: error mounting "{sources[0]}" '
        f'to rootfs: no such device'
        if error is None and sources
        else error or ""
    )
    return {
        "Id": f"id-{name}",
        "Name": f"/{name}",
        "Config": {"Labels": {"autoheal": "true"} if autoheal else {}},
        "HostConfig": {"RestartPolicy": {"Name": restart}},
        "Mounts": [{"Type": "bind", "Source": source} for source in sources],
        "State": {"Status": status, "Error": mount_error},
    }


class RecoveryCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        self.start_log = self.root / "starts"
        self._install_fake_commands()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _install_fake_commands(self) -> None:
        dispatcher = self.bin_dir / "fake-command"
        dispatcher.write_text(FAKE_COMMAND)
        dispatcher.chmod(0o755)
        for name in ("docker", "findmnt", "timeout"):
            (self.bin_dir / name).symlink_to(dispatcher)

    def run_recovery(
        self,
        containers: list[dict[str, object]],
        mounts: dict[str, dict[str, object]],
        *,
        start_failure: str = "",
        volumes: list[dict[str, object]] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        inspect_file = self.root / "inspect.json"
        mounts_file = self.root / "mounts.json"
        declaration = self.root / "storage-mounts.json"
        inspect_file.write_text(json.dumps(containers))
        mounts_file.write_text(json.dumps(mounts))
        declaration.write_text(json.dumps(NAS_VOLUMES if volumes is None else volumes))
        env = os.environ | {
            "PATH": f"{self.bin_dir}:{os.environ['PATH']}",
            "FAKE_INSPECT_FILE": str(inspect_file),
            "FAKE_MOUNTS_FILE": str(mounts_file),
            "FAKE_START_LOG": str(self.start_log),
            "FAKE_START_FAILURE": start_failure,
        }
        return subprocess.run(
            [sys.executable, str(RECOVERY_COMMAND), str(declaration)],
            capture_output=True,
            env=env,
            text=True,
            check=False,
        )

    def started(self) -> list[str]:
        if not self.start_log.exists():
            return []
        return self.start_log.read_text().splitlines()

    def test_recovers_each_ready_share_independently(self) -> None:
        containers = [
            container("pouch", ["/mnt/pouch/data"]),
            container("jump", ["/mnt/jump/data"]),
        ]
        result = self.run_recovery(containers, mount_states(pouch=True, jump=False))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.started(), ["id-pouch"])

    def test_dual_mount_container_waits_for_both_shares(self) -> None:
        plex = container("plex", ["/mnt/pouch", "/mnt/jump/plex-video-thumbnails"])
        first = self.run_recovery([plex], mount_states(pouch=True, jump=False))
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(self.started(), [])
        second = self.run_recovery([plex], mount_states(pouch=True, jump=True))
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.started(), ["id-plex"])

    def test_created_container_with_mount_failure_is_recovered(self) -> None:
        target = container("first-start", ["/mnt/pouch"], status="created")
        result = self.run_recovery([target], mount_states(pouch=True, jump=True))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.started(), ["id-first-start"])

    def test_wrong_filesystem_or_missing_sentinel_fails_closed(self) -> None:
        target = container("flood", ["/mnt/pouch"])
        wrong = mount_states(pouch=True, jump=True)
        wrong["/mnt/pouch"]["source"] = "/dev/nvme0n1p3"
        first = self.run_recovery([target], wrong)
        self.assertEqual(first.returncode, 0, first.stderr)
        missing = mount_states(pouch=True, jump=True)
        missing["/mnt/pouch"]["sentinel"] = False
        second = self.run_recovery([target], missing)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.started(), [])

    def test_automount_wrapper_allows_the_exact_nfs_child(self) -> None:
        target = container("flood", ["/mnt/pouch"])
        mounts = mount_states(pouch=True, jump=True)
        mounts["/mnt/pouch"]["filesystems"] = [
            {
                "target": "/mnt/pouch",
                "source": "systemd-1",
                "fstype": "autofs",
                "options": "rw,relatime",
            },
            {
                "target": "/mnt/pouch",
                "source": "10.0.0.25:/Pouch",
                "fstype": "nfs4",
                "options": "rw,relatime",
            },
        ]
        result = self.run_recovery([target], mounts)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.started(), ["id-flood"])

    def test_preserves_operator_stops_and_non_candidates(self) -> None:
        containers = [
            container("operator-stop", ["/mnt/pouch"], error=""),
            container("one-shot", ["/mnt/pouch"], restart="no"),
            container("not-opted-in", ["/mnt/pouch"], autoheal=False),
            container("running", ["/mnt/pouch"], status="running"),
            container("local", ["/var/lib/local"]),
            container("application-exit", ["/mnt/pouch"], error="application failed"),
        ]
        result = self.run_recovery(containers, mount_states(pouch=True, jump=True))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.started(), [])

    def test_selected_start_failure_is_visible(self) -> None:
        target = container("flood", ["/mnt/pouch"])
        result = self.run_recovery(
            [target],
            mount_states(pouch=True, jump=True),
            start_failure="daemon refused start",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("daemon refused start", result.stderr)

    def test_local_volume_host_recovers_on_its_own_declaration(self) -> None:
        # fractal: /home is a LUKS ext4 volume unlocked by hand, possibly
        # hours after Docker started. Same mechanism, different declaration.
        docs = container("docs", ["/home/nathan/repos"])
        locked = {
            "/home": {
                "sentinel": False,
                "source": "/dev/mapper/vault",
                "fstype": "ext4",
                "options": "rw,relatime",
            }
        }
        first = self.run_recovery([docs], locked, volumes=VAULT_VOLUMES)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(self.started(), [], "must wait while /home is locked")

        unlocked = {"/home": dict(locked["/home"], sentinel=True)}
        second = self.run_recovery([docs], unlocked, volumes=VAULT_VOLUMES)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.started(), ["id-docs"])

    def test_local_volume_rejects_the_unmounted_root_filesystem(self) -> None:
        # The bare /home stub on the root disk carries the same path and is
        # silently writable; only the source tells them apart.
        docs = container("docs", ["/home/nathan/repos"])
        stub = {
            "/home": {
                "sentinel": True,
                "source": "/dev/sdd",
                "fstype": "ext4",
                "options": "rw,relatime",
            }
        }
        result = self.run_recovery([docs], stub, volumes=VAULT_VOLUMES)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.started(), [])

    def test_missing_declaration_fails_loudly(self) -> None:
        result = subprocess.run(
            [sys.executable, str(RECOVERY_COMMAND), str(self.root / "absent.json")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("recovery failed", result.stderr)

    def test_declaration_argument_is_required(self) -> None:
        result = subprocess.run(
            [sys.executable, str(RECOVERY_COMMAND)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("usage:", result.stderr)

    def test_recovery_command_has_no_ofelia_behavior(self) -> None:
        self.assertNotIn("ofelia", RECOVERY_COMMAND.read_text().lower())


def mount_states(*, pouch: bool, jump: bool) -> dict[str, dict[str, object]]:
    return {
        "/mnt/pouch": {
            "sentinel": pouch,
            "source": "10.0.0.25:/Pouch",
            "fstype": "nfs4",
            "options": "rw,relatime",
        },
        "/mnt/jump": {
            "sentinel": jump,
            "source": "10.0.0.25:/Jump",
            "fstype": "nfs4",
            "options": "rw,relatime",
        },
    }


FAKE_COMMAND = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

command = Path(sys.argv[0]).name
inspect_data = json.loads(Path(os.environ["FAKE_INSPECT_FILE"]).read_text())
mounts = json.loads(Path(os.environ["FAKE_MOUNTS_FILE"]).read_text())

if command == "docker" and sys.argv[1] == "ps":
    for item in inspect_data:
        if item["Config"]["Labels"].get("autoheal") == "true":
            print(item["Id"])
elif command == "docker" and sys.argv[1] == "inspect":
    requested = set(sys.argv[2:])
    print(json.dumps([item for item in inspect_data if item["Id"] in requested]))
elif command == "docker" and sys.argv[1] == "start":
    failure = os.environ["FAKE_START_FAILURE"]
    if failure:
        print(failure, file=sys.stderr)
        raise SystemExit(1)
    with Path(os.environ["FAKE_START_LOG"]).open("a") as stream:
        stream.write(sys.argv[2] + "\n")
elif command == "timeout":
    root = os.path.dirname(sys.argv[-1])
    raise SystemExit(0 if mounts[root]["sentinel"] else 1)
elif command == "findmnt":
    root = sys.argv[sys.argv.index("--target") + 1]
    state = mounts[root]
    filesystems = state.get("filesystems", [{"target": root, **state}])
    print(json.dumps({"filesystems": filesystems}))
else:
    print(f"unexpected command: {sys.argv}", file=sys.stderr)
    raise SystemExit(2)
'''


if __name__ == "__main__":
    unittest.main()
