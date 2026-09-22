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

    def test_schema_updates_quiesce_existing_reconciliation_before_both_writes(self) -> None:
        tasks = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
        timer = next(task for task in tasks if task["name"].startswith("Stop the source timer"))
        service = next(task for task in tasks if task["name"].startswith("Quiesce"))
        self.assertIn("docs_sources_timer_unit.stat.exists", timer["when"])
        self.assertIn(
            "'podhaus-docs-source-reconcile.service' in ansible_facts.services", service["when"]
        )
        for task in (timer, service):
            self.assertEqual(task["ansible.builtin.systemd_service"]["state"], "stopped")
            self.assertIn(
                "docs_sources_manifest_update.changed or docs_sources_reconciler_update.changed",
                task["when"],
            )
        self.assertLess(tasks.index(timer), tasks.index(service))
        gather = next(task for task in tasks if "ansible.builtin.service_facts" in task)
        self.assertLess(tasks.index(gather), tasks.index(service))
        for task in tasks:
            if "register" in task and task["register"] in {
                "docs_sources_manifest_update", "docs_sources_reconciler_update"
            }:
                self.assertTrue(task["check_mode"])
                self.assertLess(tasks.index(task), tasks.index(timer))
            if task["name"] in {
                "Declare host repository source locations", "Install the docs-source reconciler"
            }:
                self.assertGreater(tasks.index(task), tasks.index(service))
        self.assertEqual(tasks[-1]["ansible.builtin.systemd_service"]["state"], "started")

    def test_docs_hosts_declare_home_and_chezmoi_sources(self) -> None:
        inventory = yaml.safe_load((ANSIBLE / "inventory" / "hosts.yml").read_text())
        docs_hosts = inventory["all"]["children"]["docs_hosts"]["hosts"]
        self.assertEqual(sorted(docs_hosts), ["bandicoot", "bilby", "fractal", "voltaire"])
        for host in docs_hosts:
            with self.subTest(host=host):
                variables = yaml.safe_load((HOST_VARS / f"{host}.yml").read_text())
                sources = {item["name"]: item for item in variables["podhaus_docs_sources"]}
                self.assertEqual(set(sources), {"home", "chezmoi"})
                for source in sources.values():
                    self.assertEqual(set(source), {"name", "type", "source", "required_path"})
                self.assertEqual(sources["home"]["type"], "directory")
                self.assertEqual(sources["home"]["required_path"], ".")
                self.assertEqual(sources["chezmoi"]["type"], "repository")
                self.assertEqual(sources["home"]["source"], "/home/nathan/repos")
                self.assertEqual(
                    sources["chezmoi"]["source"], "/home/nathan/.local/share/chezmoi"
                )
                self.assertEqual(sources["chezmoi"]["required_path"], ".git")


if __name__ == "__main__":
    unittest.main()
