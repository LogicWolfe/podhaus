import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class LanAddressConsumerTests(unittest.TestCase):
    def copied_catalog_root(self, addresses: dict[str, str | None]) -> Path:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        shutil.copytree(REPO_ROOT / "ansible", root / "ansible")
        (root / "config").mkdir()
        (root / "config/lan-addresses.json").write_text(json.dumps(addresses))
        return root

    def test_ansible_reads_a_changed_catalog_from_an_unrelated_working_directory(
        self,
    ) -> None:
        catalog = json.loads((REPO_ROOT / "config/lan-addresses.json").read_text())
        catalog.update(
            bilby_ipv4="192.0.2.41",
            bandicoot_ipv4="192.0.2.42",
            kangaroo_ipv4="192.0.2.43",
        )
        root = self.copied_catalog_root(catalog)
        environment = os.environ | {
            "ANSIBLE_CONFIG": str(root / "ansible/ansible.cfg"),
            "PATH": os.defpath,
        }
        environment.pop("OP_SERVICE_ACCOUNT_TOKEN", None)
        with tempfile.TemporaryDirectory() as directory:
            for variable, address in (
                ("podhaus_bilby_ipv4", catalog["bilby_ipv4"]),
                ("podhaus_bandicoot_ipv4", catalog["bandicoot_ipv4"]),
                ("podhaus_kangaroo_ipv4", catalog["kangaroo_ipv4"]),
            ):
                with self.subTest(variable=variable):
                    result = subprocess.run(
                        [
                            str(REPO_ROOT / ".venv/bin/ansible"),
                            "--inventory",
                            str(root / "ansible/inventory/hosts.yml"),
                            "bilby",
                            "--connection",
                            "local",
                            "--module-name",
                            "debug",
                            "--args",
                            f"var={variable}",
                        ],
                        cwd=directory,
                        env=environment,
                        capture_output=True,
                        text=True,
                    )

                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn(f'"{variable}": "{address}"', result.stdout)

    def test_upgrade_exports_a_changed_catalog_value_without_an_address_vault_read(
        self,
    ) -> None:
        catalog = json.loads((REPO_ROOT / "config/lan-addresses.json").read_text())
        catalog["bilby_ipv4"] = "192.0.2.51"
        root = self.copied_catalog_root(catalog)
        shutil.copyfile(REPO_ROOT / "komodo-upgrade", root / "komodo-upgrade")
        (root / "komodo-upgrade").chmod(0o755)
        (root / "komodo").mkdir()
        shutil.copyfile(REPO_ROOT / "komodo/compose.env", root / "komodo/compose.env")
        shim = root / "shim"
        shim.mkdir()
        output = root / "bilby-address"
        (shim / "op").write_text(
            "#!/bin/bash\n"
            "set -e\n"
            '[ "$1" = run ]\n'
            "shift\n"
            '[ "$1" = --env-file ]\n'
            "shift 2\n"
            '[ "$1" = -- ]\n'
            "shift\n"
            'exec "$@"\n'
        )
        (shim / "docker").write_text(
            "#!/bin/bash\n" 'printf \'%s\' "$BILBY_LAN_IPV4" > "$LAN_ADDRESS_RESULT"\n'
        )
        for command in (shim / "op", shim / "docker"):
            command.chmod(0o755)
        result = subprocess.run(
            [str(root / "komodo-upgrade")],
            cwd=tempfile.gettempdir(),
            env=os.environ
            | {
                "OP_SERVICE_ACCOUNT_TOKEN": "test-token",
                "PATH": f"{shim}:{os.environ['PATH']}",
                "LAN_ADDRESS_RESULT": str(output),
            },
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output.read_text(), catalog["bilby_ipv4"])

    def test_bootstrap_derives_kangaroo_ssh_from_a_changed_catalog(self) -> None:
        catalog = json.loads((REPO_ROOT / "config/lan-addresses.json").read_text())
        catalog["kangaroo_ipv4"] = "192.0.2.61"
        root = self.copied_catalog_root(catalog)
        script = (REPO_ROOT / "kangaroo_bootstrap").read_text()
        assignment = 'KANGAROO_SSH="${KANGAROO_SSH:-admin@$KANGAROO_IPV4}"'
        instrumented = script.replace(
            assignment, f"{assignment}\nprintf '%s' \"$KANGAROO_SSH\"\nexit 0"
        )
        self.assertNotEqual(instrumented, script)
        (root / "kangaroo_bootstrap").write_text(instrumented)
        (root / "kangaroo_bootstrap").chmod(0o755)
        result = subprocess.run(
            [str(root / "kangaroo_bootstrap")],
            cwd=tempfile.gettempdir(),
            env=os.environ
            | {
                "OP_SERVICE_ACCOUNT_TOKEN": "test-token",
                "PATH": os.defpath,
            },
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, f"admin@{catalog['kangaroo_ipv4']}")

    def test_upgrade_rejects_missing_or_null_bilby_address(self) -> None:
        original = json.loads((REPO_ROOT / "config/lan-addresses.json").read_text())
        for replacement in ("missing", None):
            with self.subTest(replacement=replacement):
                catalog = original.copy()
                if replacement == "missing":
                    del catalog["bilby_ipv4"]
                else:
                    catalog["bilby_ipv4"] = replacement
                root = self.copied_catalog_root(catalog)
                shutil.copyfile(REPO_ROOT / "komodo-upgrade", root / "komodo-upgrade")
                (root / "komodo-upgrade").chmod(0o755)
                (root / "komodo").mkdir()
                shutil.copyfile(
                    REPO_ROOT / "komodo/compose.env", root / "komodo/compose.env"
                )
                shim = root / "shim"
                shim.mkdir()
                marker = root / "external-action"
                for command in ("op", "docker"):
                    path = shim / command
                    path.write_text(
                        "#!/bin/bash\n"
                        "printf '%s' external > \"$LAN_ADDRESS_ACTION_MARKER\"\n"
                        "exit 99\n"
                    )
                    path.chmod(0o755)
                result = subprocess.run(
                    [str(root / "komodo-upgrade")],
                    cwd=tempfile.gettempdir(),
                    env=os.environ
                    | {
                        "OP_SERVICE_ACCOUNT_TOKEN": "test-token",
                        "PATH": f"{shim}:{os.environ['PATH']}",
                        "LAN_ADDRESS_ACTION_MARKER": str(marker),
                    },
                    capture_output=True,
                    text=True,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(marker.exists())

    def test_bootstrap_rejects_missing_bandicoot_address_before_ssh(self) -> None:
        catalog = json.loads((REPO_ROOT / "config/lan-addresses.json").read_text())
        del catalog["bandicoot_ipv4"]
        root = self.copied_catalog_root(catalog)
        shutil.copyfile(REPO_ROOT / "kangaroo_bootstrap", root / "kangaroo_bootstrap")
        (root / "kangaroo_bootstrap").chmod(0o755)
        shim = root / "shim"
        shim.mkdir()
        marker = root / "ssh-action"
        (shim / "ssh").write_text(
            "#!/bin/bash\n"
            "printf '%s' ssh > \"$LAN_ADDRESS_ACTION_MARKER\"\n"
            "exit 99\n"
        )
        (shim / "ssh").chmod(0o755)
        result = subprocess.run(
            [str(root / "kangaroo_bootstrap")],
            cwd=tempfile.gettempdir(),
            env=os.environ
            | {
                "OP_SERVICE_ACCOUNT_TOKEN": "test-token",
                "PATH": f"{shim}:{os.defpath}",
                "LAN_ADDRESS_ACTION_MARKER": str(marker),
            },
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
