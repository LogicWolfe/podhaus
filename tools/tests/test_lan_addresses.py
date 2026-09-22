import json
import shutil
import subprocess
import tempfile
import tomllib
import unittest

import yaml
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


class LanAddressDistributionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for directory in ("tools", "config", "komodo/sync", "terraform"):
            (self.root / directory).mkdir(parents=True)
        for path in ("tools/render-lan-addresses.py", "config/lan-addresses.json"):
            shutil.copyfile(REPO / path, self.root / path)
        self.source = self.root / "config/lan-addresses.json"
        self.output = self.root / "komodo/sync/lan-addresses.toml"

    def render(self, *arguments):
        return subprocess.run(
            ["python3", str(self.root / "tools/render-lan-addresses.py"), *arguments],
            cwd="/tmp",
            capture_output=True,
            text=True,
        )

    def test_changed_catalog_updates_komodo_and_verify_rejects_stale_values(self):
        self.assertEqual(self.render().returncode, 0)
        self.assertEqual(self.render("--verify").returncode, 0)
        addresses = json.loads(self.source.read_text())
        addresses["bandicoot_ipv4"] = "192.0.2.42"
        self.source.write_text(json.dumps(addresses))
        self.assertNotEqual(self.render("--verify").returncode, 0)
        self.assertEqual(self.render().returncode, 0)
        variables = tomllib.loads(self.output.read_text())["variable"]
        self.assertEqual(
            {entry["name"]: entry["value"] for entry in variables},
            {f"LAN_{name.upper()}": value for name, value in addresses.items()},
        )
        self.assertEqual(self.render("--verify").returncode, 0)

    def test_invalid_address_fails_without_replacing_published_values(self):
        self.assertEqual(self.render().returncode, 0)
        before = self.output.read_bytes()
        addresses = json.loads(self.source.read_text())
        for invalid in ("not-an-address", "2001:db8::1", 42, None):
            with self.subTest(value=invalid):
                addresses["bilby_ipv4"] = invalid
                self.source.write_text(json.dumps(addresses))
                self.assertNotEqual(self.render().returncode, 0)
                self.assertEqual(self.output.read_bytes(), before)

    def test_missing_required_address_fails_without_publishing(self):
        addresses = json.loads(self.source.read_text())
        del addresses["bilby_ipv4"]
        self.source.write_text(json.dumps(addresses))
        self.assertNotEqual(self.render().returncode, 0)
        self.assertFalse(self.output.exists())

    def test_every_stack_using_shared_addresses_redeploys_on_catalog_changes(self):
        catalog = REPO / "config/lan-addresses.json"
        consumers = [
            path for path in REPO.rglob("stack.toml") if "[[LAN_" in path.read_text()
        ]
        self.assertTrue(consumers)
        for stack in consumers:
            with self.subTest(stack=stack.relative_to(REPO)):
                compose = yaml.safe_load((stack.parent / "compose.yaml").read_text())
                dependencies = compose["x-podhaus-content-paths"]
                self.assertTrue(
                    any(
                        catalog.is_relative_to((stack.parent / path).resolve())
                        for path in dependencies
                    )
                )

    def test_terraform_reads_changed_catalog_without_other_services(self):
        shutil.copyfile(
            REPO / "terraform/lan_addresses.tf",
            self.root / "terraform/lan_addresses.tf",
        )
        addresses = json.loads(self.source.read_text())
        addresses["bilby_ipv4"] = "192.0.2.42"
        self.source.write_text(json.dumps(addresses))
        result = subprocess.run(
            ["terraform", "console", "-no-color"],
            cwd=self.root / "terraform",
            input=(
                "jsonencode({"
                "bilby_ipv4=local.bilby_ip,bandicoot_ipv4=local.bandicoot_ip,"
                "kangaroo_ipv4=local.kangaroo_ip_10g,"
                "kangaroo_1g_ipv4=local.kangaroo_ip_1g,"
                "fractal_windows_ipv4=local.fractal_windows_ip,"
                "turn_touch_burrow_ipv4=local.turn_touch_burrow_ip,"
                "led_strip_grasshopper_ipv4=local.led_strip_grasshopper_ip,"
                "pizero_ipv4=local.pizero_ip,"
                "nb_macbook_air_ipv4=local.nb_macbook_air_ip})\n"
            ),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(json.loads(result.stdout)), addresses)


if __name__ == "__main__":
    unittest.main()
