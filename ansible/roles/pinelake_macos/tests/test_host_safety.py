from __future__ import annotations

import plistlib
import unittest
from pathlib import Path

import yaml


ROLE_DIR = Path(__file__).resolve().parents[1]


class HostSafetyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.defaults = yaml.safe_load((ROLE_DIR / "defaults/main.yml").read_text())
        self.tasks = yaml.safe_load((ROLE_DIR / "tasks/main.yml").read_text())
        self.handlers = yaml.safe_load((ROLE_DIR / "handlers/main.yml").read_text())

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
        self.assertEqual(setting_values["setup.use_admin"], "true")
        self.assertEqual(setting_values["docker.set_context"], "false")
        task_names = {task["name"] for task in self.tasks}
        self.assertIn("Prove the default Docker socket", task_names)
        self.assertIn("Select the default Docker context", task_names)
        self.assertIn("Remove the OrbStack-specific Docker context", task_names)
        self.assertIn("Prove default is the sole Docker context", task_names)

    def test_role_installs_orbstacks_signed_privileged_helper(self) -> None:
        task_names = {task["name"] for task in self.tasks}
        self.assertIn("Install the OrbStack privileged helper", task_names)
        self.assertIn("Install the OrbStack privileged helper daemon", task_names)
        template = (
            ROLE_DIR / "templates/dev.orbstack.OrbStack.privhelper.plist"
        ).read_bytes()
        plist = plistlib.loads(template)
        self.assertEqual(plist["Label"], "dev.orbstack.OrbStack.privhelper")
        self.assertEqual(
            plist["ProgramArguments"],
            ["/Library/PrivilegedHelperTools/dev.orbstack.OrbStack.privhelper"],
        )
        self.assertTrue(
            plist["MachServices"]["dev.orbstack.OrbStack.privhelper"]
        )
        self.assertIn("Remove quarantine from the OrbStack privileged helper", task_names)

    def test_ansible_never_restarts_orbstack_in_band(self) -> None:
        role_text = "\n".join(
            path.read_text()
            for path in (ROLE_DIR / "tasks/main.yml", ROLE_DIR / "handlers/main.yml")
        )
        self.assertNotIn("orb stop", role_text)
        self.assertNotIn("Restart OrbStack", role_text)

    def test_safe_start_path_lands_before_runtime_socket_proof(self) -> None:
        task_names = [task["name"] for task in self.tasks]
        self.assertLess(
            task_names.index("Activate the mount-gated startup path"),
            task_names.index("Prove the default Docker socket"),
        )

    def test_login_agent_runs_mount_gated_start_in_aqua_session(self) -> None:
        template = (ROLE_DIR / "templates/haus.podhaus.orbstack.plist.j2").read_text()
        rendered = (
            template.replace("{{ podhaus_operator }}", "baxter")
            .replace("{{ podhaus_orbstack_path }}", "/usr/bin:/bin")
            .replace("{{ podhaus_pinelake_libexec_dir }}", "/usr/local/libexec/podhaus")
        )
        plist = plistlib.loads(rendered.encode())
        self.assertNotIn("UserName", plist)
        self.assertEqual(plist["LimitLoadToSessionType"], "Aqua")
        self.assertEqual(
            plist["ProgramArguments"],
            ["/usr/local/libexec/podhaus/pinelake-orbstack-start"],
        )
        self.assertTrue(
            self.defaults["podhaus_pinelake_launch_agent"].endswith(
                "/Library/LaunchAgents/haus.podhaus.orbstack.plist"
            )
        )

    def test_start_wrapper_checks_mount_before_starting_orbstack(self) -> None:
        wrapper = (ROLE_DIR / "templates/pinelake-orbstack-start.j2").read_text()
        self.assertLess(
            wrapper.index("pinelake-mount-guard"),
            wrapper.index("/usr/bin/open"),
        )
        self.assertIn("--volume-uuid", wrapper)
        self.assertNotIn("--initialize-sentinel", wrapper)
        self.assertNotIn("orb start", wrapper)

    def test_mount_contract_uses_four_share_roots(self) -> None:
        self.assertEqual(
            self.defaults["podhaus_terramaster_required_paths"],
            ["Movies", "TV", "Kids", "Sports", "Torrents"],
        )

    def test_legacy_autostarts_are_disabled_but_not_deleted(self) -> None:
        self.assertEqual(
            set(self.defaults["podhaus_pinelake_legacy_user_jobs"]),
            {"homebrew.mxcl.syncthing", "homebrew.mxcl.colima", "com.flood.ui"},
        )
        self.assertEqual(
            set(self.defaults["podhaus_pinelake_legacy_system_jobs"]),
            {"haus.podhaus.colima", "io.colima.start"},
        )
        task_names = {task["name"] for task in self.tasks}
        self.assertIn("Disable legacy user launch jobs", task_names)
        self.assertIn("Disable legacy system launch jobs", task_names)

    def test_full_macos_updates_are_not_installed_automatically(self) -> None:
        task = self.task("Disable unattended macOS upgrades")
        self.assertEqual(
            task["community.general.osx_defaults"]["key"],
            "AutomaticallyInstallMacOSUpdates",
        )
        self.assertFalse(task["community.general.osx_defaults"]["value"])


if __name__ == "__main__":
    unittest.main()
