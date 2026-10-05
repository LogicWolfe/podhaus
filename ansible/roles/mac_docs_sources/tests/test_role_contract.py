"""Contract tests for the MacBook's repository source list."""

from pathlib import Path
import unittest

import yaml


ROLE = Path(__file__).resolve().parents[1]
ANSIBLE = ROLE.parents[1]
RECORD_KEYS = {"name", "type", "source", "required_path"}


def host_vars(host: str) -> dict:
    return yaml.safe_load((ANSIBLE / "inventory" / "host_vars" / f"{host}.yml").read_text())


class RoleContractTest(unittest.TestCase):
    def test_writes_where_the_linux_role_writes(self) -> None:
        mac = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())
        linux = yaml.safe_load((ANSIBLE / "roles" / "docs_sources" / "defaults" / "main.yml").read_text())
        self.assertEqual(mac["mac_docs_sources_config"], linux["docs_sources_config"])

    def test_the_mac_lists_its_repos_and_chezmoi_like_the_linux_hosts(self) -> None:
        mac = host_vars("nb-macbook-air")["podhaus_docs_sources"]
        linux = host_vars("fractal")["podhaus_docs_sources"]
        for record in mac:
            self.assertEqual(set(record), RECORD_KEYS)
        self.assertEqual(
            [(r["name"], r["type"], r["required_path"]) for r in mac],
            [(r["name"], r["type"], r["required_path"]) for r in linux],
        )
        self.assertEqual(
            {r["name"]: r["source"] for r in mac},
            {"home": "/Users/nathan/repos", "chezmoi": "/Users/nathan/.local/share/chezmoi"},
        )

    def test_the_mac_playbook_applies_the_role(self) -> None:
        play = yaml.safe_load((ANSIBLE / "playbooks" / "nb-macbook-air.yml").read_text())[0]
        self.assertIn("mac_docs_sources", [entry["role"] for entry in play["roles"]])

    def test_the_mac_playbook_runs_on_the_mac_and_nowhere_else(self) -> None:
        play = yaml.safe_load((ANSIBLE / "playbooks" / "nb-macbook-air.yml").read_text())[0]
        self.assertEqual(play["connection"], "local")
        guard = play["pre_tasks"][0]["ansible.builtin.assert"]
        self.assertEqual(guard["that"], 'ansible_facts.system == "Darwin"')
        self.assertNotIn("ansible_host", host_vars("nb-macbook-air"))


if __name__ == "__main__":
    unittest.main()
