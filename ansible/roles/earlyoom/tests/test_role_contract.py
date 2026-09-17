"""Contract tests for the earlyoom kill-order host provisioning."""

from pathlib import Path
import shlex
import unittest

import yaml


ROLE = Path(__file__).resolve().parents[1]
ANSIBLE = ROLE.parents[1]
DEV_HOSTS = ["bandicoot", "bilby", "voltaire"]


def earlyoom_arguments() -> list[str]:
    for line in (ROLE / "files" / "earlyoom").read_text().splitlines():
        if line.startswith("EARLYOOM_ARGS="):
            return shlex.split(shlex.split(line.removeprefix("EARLYOOM_ARGS="))[0])
    raise AssertionError("EARLYOOM_ARGS is not set")


class RoleContractTest(unittest.TestCase):
    def test_kills_at_ten_percent_memory_and_swap_ranked_by_score(self) -> None:
        arguments = earlyoom_arguments()
        self.assertEqual(arguments[arguments.index("-m") + 1], "10")
        self.assertEqual(arguments[arguments.index("-s") + 1], "10")
        for overriding in ("-M", "-S", "--prefer", "--sort-by-rss"):
            self.assertNotIn(overriding, arguments)

    def test_session_plumbing_is_never_a_victim(self) -> None:
        arguments = earlyoom_arguments()
        avoid = arguments[arguments.index("--avoid") + 1]
        self.assertTrue(avoid.startswith("^(") and avoid.endswith(")$"), avoid)
        names = set(avoid.removeprefix("^(").removesuffix(")$").split("|"))
        self.assertLessEqual({"systemd", "dbus-broker", "gnome-shell", "cryptsetup"}, names)

    def test_dev_hosts_run_earlyoom_with_systemd_oomd_left_on(self) -> None:
        inventory = yaml.safe_load((ANSIBLE / "inventory" / "hosts.yml").read_text())
        groups = inventory["all"]["children"]
        self.assertEqual(sorted(groups["earlyoom_hosts"]["hosts"]), DEV_HOSTS)
        tasks = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
        units = {task["ansible.builtin.systemd_service"]["name"]: task["ansible.builtin.systemd_service"]
                 for task in tasks if "ansible.builtin.systemd_service" in task}
        for unit in ("earlyoom.service", "systemd-oomd.service"):
            self.assertEqual((units[unit]["enabled"], units[unit]["state"]), (True, "started"))

    def test_every_dev_host_playbook_applies_the_role_and_disk_tmp(self) -> None:
        for host in DEV_HOSTS:
            with self.subTest(host=host):
                play = yaml.safe_load((ANSIBLE / "playbooks" / f"{host}.yml").read_text())[0]
                roles = [entry["role"] for entry in play["roles"]]
                self.assertIn("earlyoom", roles)
                self.assertIn("disk_tmp", roles)
        inventory = yaml.safe_load((ANSIBLE / "inventory" / "hosts.yml").read_text())
        self.assertLessEqual(set(DEV_HOSTS), set(inventory["all"]["children"]["disk_tmp_hosts"]["hosts"]))


if __name__ == "__main__":
    unittest.main()
