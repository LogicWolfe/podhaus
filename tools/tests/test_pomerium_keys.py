import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PERSONAL = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJ4Xm1j4aJYhQ0j3K8q6U0d1qjv6H5n2m3o4p5q6r7s8 personal key"
SHARED = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIC5zEJO7pWBiUNL3Sx7VvTUCpIIaZoKVvNeqMKymgDl3"


class PomeriumKeyRenderTests(unittest.TestCase):
    '''Two laptops declaring one machine key while it moves between them.'''

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for directory in ("tools", "pomerium", "ansible/inventory/group_vars", "ansible/inventory/host_vars"):
            (self.root / directory).mkdir(parents=True)
        shutil.copyfile(REPO / "tools/render-pomerium-keys.py", self.root / "tools/render-pomerium-keys.py")
        inventory = self.root / "ansible/inventory"
        (inventory / "hosts.yml").write_text(
            "all:\n  children:\n    remote_dev_machines:\n      hosts:\n        old-laptop:\n        new-laptop:\n"
        )
        (inventory / "group_vars/all.yml").write_text(f"podhaus_personal_key: {PERSONAL}\n")
        (self.root / "pomerium/config.yaml").write_text(
            "ssh_publickey: &registered_ssh_keys\n  - 'stale'\nnext: true\n"
        )
        (self.root / "pomerium/stack.toml").write_text(
            "name = \"POMERIUM_SSH_KEY_OWNERS\"\nvalue = '{}'\n"
        )

    def declare(self, host: str, comment: str) -> None:
        (self.root / f"ansible/inventory/host_vars/{host}.yml").write_text(
            f"podhaus_machine_key: >-\n  {SHARED}\n  {comment}\n"
        )

    def render(self):
        return subprocess.run(
            ["python3", str(self.root / "tools/render-pomerium-keys.py")],
            capture_output=True,
            text=True,
        )

    def test_a_key_two_hosts_share_is_registered_once(self):
        self.declare("old-laptop", "old-laptop machine key")
        self.declare("new-laptop", "old-laptop machine key")
        self.assertEqual(self.render().returncode, 0)
        registered = re.findall(r"- '([^']*)'", (self.root / "pomerium/config.yaml").read_text())
        self.assertEqual(registered, [PERSONAL, f"{SHARED} old-laptop machine key"])
        owners = json.loads(
            re.search(r"value = '(.*)'", (self.root / "pomerium/stack.toml").read_text()).group(1)
        )
        self.assertEqual(
            sorted(owner["machine"] for owner in owners.values()),
            ["old-laptop machine key", "personal key"],
        )

    def test_a_shared_key_under_two_labels_is_refused(self):
        self.declare("old-laptop", "old-laptop machine key")
        self.declare("new-laptop", "new-laptop machine key")
        before = (self.root / "pomerium/config.yaml").read_text()
        result = self.render()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("two comments", result.stderr)
        self.assertEqual((self.root / "pomerium/config.yaml").read_text(), before)


if __name__ == "__main__":
    unittest.main()
