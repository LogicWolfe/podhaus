"""Contract tests that `base` runs before `wsl` and `earlyoom` in the fractal and fleet playbooks."""

from pathlib import Path
import unittest

import yaml


PLAYBOOKS = Path(__file__).resolve().parents[3] / "playbooks"


def role_order(playbook: str) -> list[str]:
    play = yaml.safe_load((PLAYBOOKS / playbook).read_text())[0]
    return [entry["role"] for entry in play["roles"]]


class BasePrecedesWslAndEarlyoomTest(unittest.TestCase):
    """`base` installs the dnf5 bindings that let package tasks run in --check on a fresh host."""

    def test_fractal_runs_base_before_wsl_and_earlyoom(self) -> None:
        roles = role_order("fractal.yml")
        self.assertLess(roles.index("base"), roles.index("wsl"))
        self.assertLess(roles.index("base"), roles.index("earlyoom"))

    def test_site_runs_base_before_wsl_and_earlyoom(self) -> None:
        roles = role_order("site.yml")
        self.assertLess(roles.index("base"), roles.index("wsl"))
        self.assertLess(roles.index("base"), roles.index("earlyoom"))


if __name__ == "__main__":
    unittest.main()
