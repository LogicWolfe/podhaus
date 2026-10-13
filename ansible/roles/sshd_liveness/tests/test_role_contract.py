"""Contract tests for dropping SSH clients that stopped answering."""

from pathlib import Path
import unittest

import yaml


ROLE = Path(__file__).resolve().parents[1]
ANSIBLE = ROLE.parents[1]
DEV_HOSTS = ["bandicoot", "bilby", "fractal", "quokka", "voltaire"]


class RoleContractTest(unittest.TestCase):
    def test_dead_clients_are_dropped_within_a_minute(self) -> None:
        task = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())[0]
        settings = dict(
            line.split()
            for line in task["ansible.builtin.copy"]["content"].splitlines()
            if line and not line.startswith("#")
        )
        interval = int(settings["ClientAliveInterval"])
        misses = int(settings["ClientAliveCountMax"])
        self.assertGreater(interval, 0)
        self.assertLessEqual(interval * misses, 60)

    def test_a_reconnect_replaces_a_stale_forwarded_socket(self) -> None:
        tasks = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
        copies = [t["ansible.builtin.copy"] for t in tasks if "ansible.builtin.copy" in t]
        unlink = next(c for c in copies if "StreamLocalBindUnlink" in c["content"])
        self.assertTrue(unlink["dest"].startswith("/etc/ssh/sshd_config.d/"))
        self.assertIn("StreamLocalBindUnlink yes", unlink["content"].splitlines())
        self.assertEqual(unlink["validate"], "/usr/sbin/sshd -t -f %s")

    def test_every_dev_host_applies_the_role(self) -> None:
        for host in DEV_HOSTS:
            with self.subTest(host=host):
                play = yaml.safe_load((ANSIBLE / "playbooks" / f"{host}.yml").read_text())[0]
                self.assertIn("sshd_liveness", [entry["role"] for entry in play["roles"]])
        site = yaml.safe_load((ANSIBLE / "playbooks" / "site.yml").read_text())[0]
        entry = next(entry for entry in site["roles"] if entry["role"] == "sshd_liveness")
        self.assertEqual(entry["when"], "inventory_hostname in groups['remote_dev_machines']")
        inventory = yaml.safe_load((ANSIBLE / "inventory" / "hosts.yml").read_text())
        dev_machines = inventory["all"]["children"]["remote_dev_machines"]["hosts"]
        self.assertLessEqual(set(DEV_HOSTS), set(dev_machines))


if __name__ == "__main__":
    unittest.main()
