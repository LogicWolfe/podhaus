"""Contract tests for the WSL guest's own NTP client."""

from pathlib import Path
import unittest

import yaml


ROLE = Path(__file__).resolve().parents[1]


def chrony_directives() -> dict[str, list[str]]:
    directives: dict[str, list[str]] = {}
    for line in (ROLE / "files" / "chrony.conf").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            name, _, arguments = line.partition(" ")
            directives.setdefault(name, []).append(arguments.strip())
    return directives


DROP_IN = "chronyd-after-ptp.conf"


def drop_in_unit_section() -> dict[str, str]:
    section: dict[str, str] = {}
    for line in (ROLE / "files" / DROP_IN).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and line != "[Unit]":
            key, _, value = line.partition("=")
            section[key] = value
    return section


def tasks_using(module: str) -> list[dict]:
    tasks = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
    return [task for task in tasks if module in task]


class ChronyContractTest(unittest.TestCase):
    def test_steps_the_clock_at_any_time_so_a_host_sleep_jump_is_not_slewed(self) -> None:
        self.assertEqual(chrony_directives()["makestep"], ["1.0 -1"])

    def test_pool_is_polled_by_default_and_one_commercial_server_every_64_seconds(self) -> None:
        directives = chrony_directives()
        self.assertEqual(directives["pool"], ["2.fedora.pool.ntp.org iburst"])
        self.assertEqual(directives["server"], ["time.cloudflare.com iburst maxpoll 6"])

    def test_windows_clock_is_visible_but_never_steered_to_and_never_required(self) -> None:
        self.assertEqual(chrony_directives()["refclock"],
                         ["PHC /dev/ptp_hyperv poll 3 dpoll -2 noselect optional"])

    def test_chronyd_starts_after_the_windows_clock_device_exists(self) -> None:
        self.assertEqual(drop_in_unit_section(),
                         {"Wants": "dev-ptp_hyperv.device", "After": "dev-ptp_hyperv.device"})
        drop_in = [task for task in tasks_using("ansible.builtin.copy")
                   if task["ansible.builtin.copy"]["dest"].startswith("/etc/systemd/system/chronyd.service.d/")]
        self.assertEqual([task["ansible.builtin.copy"]["src"] for task in drop_in], [DROP_IN])
        self.assertEqual(drop_in[0]["register"], "wsl_chronyd_drop_in")

    def test_systemd_rereads_units_when_the_drop_in_changes(self) -> None:
        run = [task["ansible.builtin.systemd_service"] for task in tasks_using("ansible.builtin.systemd_service")
               if task["ansible.builtin.systemd_service"]["name"] == "chronyd.service"]
        self.assertEqual([unit["daemon_reload"] for unit in run], ["{{ wsl_chronyd_drop_in is changed }}"])

    def test_role_installs_chrony_and_runs_chronyd(self) -> None:
        packages = [task["ansible.builtin.dnf"] for task in tasks_using("ansible.builtin.dnf")]
        self.assertIn("chrony", [package["name"] for package in packages])
        units = {task["ansible.builtin.systemd_service"]["name"]: task["ansible.builtin.systemd_service"]
                 for task in tasks_using("ansible.builtin.systemd_service")}
        self.assertEqual((units["chronyd.service"]["enabled"], units["chronyd.service"]["state"]),
                         (True, "started"))

    def test_config_change_restarts_chronyd(self) -> None:
        config = [task for task in tasks_using("ansible.builtin.copy")
                  if task["ansible.builtin.copy"]["dest"] == "/etc/chrony.conf"]
        self.assertEqual(len(config), 1)
        self.assertEqual(config[0]["ansible.builtin.copy"]["src"], "chrony.conf")
        handlers = {handler["name"]: handler for handler in
                    yaml.safe_load((ROLE / "handlers" / "main.yml").read_text())}
        restart = handlers[config[0]["notify"]]["ansible.builtin.systemd_service"]
        self.assertEqual((restart["name"], restart["state"]), ("chronyd.service", "restarted"))


if __name__ == "__main__":
    unittest.main()
