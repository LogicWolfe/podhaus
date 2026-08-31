"""Contract tests for docs-source host provisioning."""

from pathlib import Path
import unittest

import yaml


ROLE = Path(__file__).resolve().parents[1]
ANSIBLE = ROLE.parents[1]
HOST_VARS = ANSIBLE / "inventory" / "host_vars"


class RoleContractTest(unittest.TestCase):
    def test_timer_recurs_and_root_precedes_docker(self) -> None:
        timer = (ROLE / "files" / "podhaus-docs-source-reconcile.timer").read_text()
        root = (ROLE / "files" / "podhaus-docs-source-root.service").read_text()
        dropin = (ROLE / "files" / "20-docs-source-root.conf").read_text()
        self.assertIn("OnUnitInactiveSec=60s", timer)
        self.assertIn("Before=docker.service", root)
        self.assertIn("Requires=podhaus-docs-source-root.service", dropin)

    def test_docs_hosts_declare_home_and_chezmoi_sources(self) -> None:
        inventory = yaml.safe_load((ANSIBLE / "inventory" / "hosts.yml").read_text())
        docs_hosts = inventory["all"]["children"]["docs_hosts"]["hosts"]
        self.assertEqual(sorted(docs_hosts), ["bilby", "fractal", "voltaire"])
        for host in docs_hosts:
            with self.subTest(host=host):
                variables = yaml.safe_load((HOST_VARS / f"{host}.yml").read_text())
                sources = {item["name"]: item for item in variables["podhaus_docs_sources"]}
                self.assertEqual(set(sources), {"home", "chezmoi"})
                self.assertEqual(sources["home"]["source"], "/home/nathan/repos")
                self.assertEqual(
                    sources["chezmoi"]["source"], "/home/nathan/.local/share/chezmoi"
                )
                self.assertEqual(sources["chezmoi"]["required_path"], ".git")


if __name__ == "__main__":
    unittest.main()
