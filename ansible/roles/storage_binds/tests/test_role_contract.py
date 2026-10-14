"""Contract tests for the inventory that feeds the storage_binds role.

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
