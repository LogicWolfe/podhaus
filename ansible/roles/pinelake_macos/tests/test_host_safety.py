from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROLE_DIR = Path(__file__).resolve().parents[1]


class HostSafetyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.defaults = yaml.safe_load((ROLE_DIR / "defaults/main.yml").read_text())
        self.tasks = yaml.safe_load((ROLE_DIR / "tasks/main.yml").read_text())

    def task(self, name: str) -> dict[str, object]:
        pending = list(self.tasks)
        while pending:
            task = pending.pop(0)
            if task.get("name") == name:
                return task
            pending.extend(task.get("block", []))
        raise AssertionError(f"missing task: {name}")

    def test_orbstack_uses_global_default_docker_socket(self) -> None:
        settings = self.task("Read OrbStack settings")["ansible.builtin.command"]["argv"]
        self.assertEqual(settings, ["/opt/homebrew/bin/orb", "config", "get", "{{ item.key }}"])
        setting_values = {
            item["key"]: item["value"]
            for item in self.task("Read OrbStack settings")["loop"]
        }
        self.assertEqual(setting_values["app.start_at_login"], "true")
        self.assertEqual(setting_values["setup.use_admin"], "true")
        self.assertEqual(setting_values["docker.set_context"], "false")
        task_names = {task["name"] for task in self.tasks}
        self.assertIn("Prove the default Docker socket", task_names)
        self.assertIn("Select the default Docker context", task_names)
        self.assertIn("Remove the OrbStack-specific Docker context", task_names)
        self.assertIn("Prove default is the sole Docker context", task_names)

    def test_orbstack_owns_its_login_and_privileged_integration(self) -> None:
        role_text = "\n".join(
            path.read_text()
            for path in (ROLE_DIR / "tasks/main.yml", ROLE_DIR / "defaults/main.yml")
        )
        self.assertNotIn("LaunchAgent", role_text)
        self.assertNotIn("LaunchDaemon", role_text)
        self.assertNotIn("PrivilegedHelperTools", role_text)
        self.assertNotIn("privileged helper", role_text.lower())
        self.assertNotIn("pinelake-orbstack-start", role_text)
        self.assertFalse((ROLE_DIR / "handlers/main.yml").exists())
        self.assertEqual(list((ROLE_DIR / "templates").glob("*")), [])

    def test_ansible_never_restarts_orbstack_in_band(self) -> None:
        role_text = "\n".join(
            path.read_text() for path in (ROLE_DIR / "tasks/main.yml",)
        )
        self.assertNotIn("orb stop", role_text)
        self.assertNotIn("orb start", role_text)
        self.assertNotIn("Restart OrbStack", role_text)

    def test_mount_contract_uses_required_media_roots(self) -> None:
        self.assertEqual(
            self.defaults["podhaus_terramaster_required_paths"],
            ["Movies", "TV", "Kids", "Sports", "Torrents"],
        )

    def test_full_macos_updates_are_not_installed_automatically(self) -> None:
        task = self.task("Disable unattended macOS upgrades")
        self.assertEqual(
            task["community.general.osx_defaults"]["key"],
            "AutomaticallyInstallMacOSUpdates",
        )
        self.assertFalse(task["community.general.osx_defaults"]["value"])


if __name__ == "__main__":
    unittest.main()
