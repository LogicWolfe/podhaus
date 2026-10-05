"""Contract tests that the WSL guest runs no NTP daemon of its own.

Windows owns the clock and WSL keeps the guest on it, so the role removes
chrony wherever it is installed rather than run a second daemon steering
the same clock.
"""

from pathlib import Path
import unittest

import yaml


ROLE = Path(__file__).resolve().parents[1]
DROP_IN_DIR = "/etc/systemd/system/chronyd.service.d"


def tasks() -> list[dict]:
    return yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())


def handlers() -> list[dict]:
    return yaml.safe_load((ROLE / "handlers" / "main.yml").read_text())


def position(module: str, matches) -> int:
    found = [index for index, task in enumerate(tasks()) if module in task and matches(task[module])]
    if len(found) != 1:
        raise AssertionError(f"expected exactly one matching {module} task, found {len(found)}")
    return found[0]


def chrony_package() -> int:
    return position("ansible.builtin.dnf", lambda args: args.get("name") == "chrony")


def chronyd_unit() -> int:
    return position("ansible.builtin.systemd_service", lambda args: args.get("name") == "chronyd.service")


class NoGuestNtpDaemonTest(unittest.TestCase):
    def test_chrony_package_is_removed(self) -> None:
        self.assertEqual(tasks()[chrony_package()]["ansible.builtin.dnf"]["state"], "absent")

    def test_chronyd_is_stopped_and_disabled_only_where_it_exists(self) -> None:
        task = tasks()[chronyd_unit()]
        unit = task["ansible.builtin.systemd_service"]
        self.assertEqual((unit["state"], unit["enabled"]), ("stopped", False))
        self.assertEqual(task["when"], "'chrony' in ansible_facts.packages")
        facts = [index for index, entry in enumerate(tasks()) if "ansible.builtin.package_facts" in entry]
        self.assertTrue(facts and facts[0] < chronyd_unit())

    def test_chronyd_stops_while_its_unit_file_still_exists(self) -> None:
        self.assertLess(chronyd_unit(), chrony_package())

    def test_the_chronyd_drop_in_is_removed_and_systemd_rereads_units(self) -> None:
        removal = tasks()[position("ansible.builtin.file", lambda args: args.get("path") == DROP_IN_DIR)]
        self.assertEqual(removal["ansible.builtin.file"]["state"], "absent")
        reload = tasks()[position("ansible.builtin.systemd_service", lambda args: "name" not in args)]
        self.assertIs(reload["ansible.builtin.systemd_service"]["daemon_reload"], True)
        self.assertEqual(reload["when"], f"{removal['register']} is changed")

    def test_nothing_installs_configures_or_runs_chrony(self) -> None:
        mentions = [yaml.safe_dump(entry) for entry in tasks() + handlers()
                    if "chrony" in yaml.safe_dump(entry)]
        for text in mentions:
            for forbidden in ("state: present", "state: started", "state: restarted",
                              "enabled: true", "/etc/chrony.conf"):
                self.assertNotIn(forbidden, text)
        self.assertEqual(list((ROLE / "files").glob("chrony*")), [])


if __name__ == "__main__":
    unittest.main()
