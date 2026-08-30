"""Contract tests for the storage_binds role and the inventory that feeds it.

Run under the project's pipenv (pyyaml is a dev dependency):
    pipenv run python -m unittest discover -s ansible/roles/storage_binds/tests
"""

from pathlib import Path
import unittest

import yaml


ROLE = Path(__file__).resolve().parents[1]
ANSIBLE = ROLE.parents[1]
HOST_VARS = ANSIBLE / "inventory" / "host_vars"


def storage_hosts() -> list[str]:
    inventory = yaml.safe_load((ANSIBLE / "inventory" / "hosts.yml").read_text())

    def find(node: object) -> dict[str, object] | None:
        if not isinstance(node, dict):
            return None
        if "storage_binds_hosts" in node:
            return node["storage_binds_hosts"]["hosts"]
        for value in node.values():
            found = find(value)
            if found is not None:
                return found
        return None

    hosts = find(inventory)
    assert hosts, "storage_binds_hosts group not found in inventory"
    return sorted(hosts)


def host_vars(host: str) -> dict[str, object]:
    return yaml.safe_load((HOST_VARS / f"{host}.yml").read_text())


class RoleContractTest(unittest.TestCase):
    def test_recovery_service_is_bounded_and_reads_the_declaration(self) -> None:
        service = (
            ROLE / "files" / "podhaus-storage-container-recovery.service"
        ).read_text()
        self.assertIn("Type=oneshot", service)
        self.assertIn("TimeoutStartSec=45", service)
        self.assertIn("After=docker.service", service)
        self.assertIn(
            "/usr/local/sbin/recover-storage-containers /etc/podhaus/storage-mounts.json",
            service,
        )

    def test_timer_recurs_forever_with_no_readiness_deadline(self) -> None:
        # The whole point: a volume that returns hours later — a QNAP outage,
        # or Nathan unlocking fractal's vault by hand — must take the same
        # path as one that returns in seconds. Any deadline would break that.
        timer = (ROLE / "files" / "podhaus-storage-container-recovery.timer").read_text()
        self.assertIn("OnUnitInactiveSec=60s", timer)
        self.assertIn("WantedBy=timers.target", timer)
        self.assertNotIn("OnFailure", timer)

    def test_role_removes_its_superseded_units_and_the_finite_gate(self) -> None:
        tasks = (ROLE / "tasks" / "main.yml").read_text()
        for stale in (
            "podhaus-nfs-container-recovery.timer",
            "podhaus-nfs-container-recovery.service",
            "recover-nfs-containers",
            "wait-for-qnap-nfs.service",
            "10-wait-for-qnap.conf",
        ):
            self.assertIn(stale, tasks, f"{stale} must be explicitly removed")
        self.assertIn("state: absent", tasks)

    def test_rate_limit_dropin_disables_the_cap(self) -> None:
        dropin = (ROLE / "files" / "10-no-rate-limit.conf").read_text()
        self.assertIn("StartLimitIntervalSec=0", dropin)
        self.assertIn("StartLimitBurst=0", dropin)

    def test_tripwire_covers_every_declared_volume_root(self) -> None:
        tasks = (ROLE / "tasks" / "main.yml").read_text()
        self.assertIn("chattr-tripwire.sh", tasks)
        self.assertIn("storage_binds_mounts | map(attribute='root')", tasks)

    def test_every_storage_host_declares_its_volumes(self) -> None:
        for host in storage_hosts():
            with self.subTest(host=host):
                mounts = host_vars(host).get("storage_binds_mounts")
                self.assertTrue(mounts, f"{host} declares no storage_binds_mounts")
                for mount in mounts:
                    self.assertTrue(mount["root"].startswith("/"))
                    self.assertTrue(mount["source"])
                    self.assertTrue(mount["fstypes"])

    def test_rate_limit_dropins_cover_both_halves_of_each_pair(self) -> None:
        # systemd rate-limits the .mount unit, not the .automount that
        # triggers it: an automount whose mount trips the cap records
        # 'mount-start-limit-hit' and never retries. Covering only the
        # .automount half is what re-wedged both shares on 2026-08-30, so
        # the pairing is asserted rather than left to review.
        for host in storage_hosts():
            declared = set(host_vars(host).get("storage_binds_rate_limit_dropin_dirs", []))
            for entry in declared:
                with self.subTest(host=host, dropin=entry):
                    self.assertTrue(entry.endswith((".mount.d", ".automount.d")))
                    stem = entry.removesuffix(".automount.d").removesuffix(".mount.d")
                    self.assertIn(
                        f"{stem}.mount.d",
                        declared,
                        f"{host}: {stem} needs its .mount half — systemd caps that unit",
                    )
                    self.assertIn(
                        f"{stem}.automount.d",
                        declared,
                        f"{host}: {stem} needs its .automount half",
                    )


if __name__ == "__main__":
    unittest.main()
