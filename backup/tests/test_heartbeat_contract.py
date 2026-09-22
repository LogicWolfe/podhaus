"""Backup producers must address configured Gatus heartbeat endpoints."""

from pathlib import Path
import tomllib
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]


def gatus_endpoint_key(*, group: str, name: str) -> str:
    translation = str.maketrans({character: "-" for character in "/_., #+&"})
    return "_".join(value.lower().strip().translate(translation) for value in (group, name))


class BackupHeartbeatContractTest(unittest.TestCase):
    def test_every_backup_heartbeat_addresses_an_external_endpoint(self) -> None:
        config = yaml.safe_load((ROOT / "gatus/conf/config.yaml").read_text())
        endpoint_keys = {
            gatus_endpoint_key(group=endpoint["group"], name=endpoint["name"])
            for endpoint in config["external-endpoints"]
        }
        stack_paths = list((ROOT / "backup").glob("*/stack.toml"))
        self.assertTrue(stack_paths, "No backup stacks discovered")
        for path in stack_paths:
            for stack in tomllib.loads(path.read_text())["stack"]:
                environment = dict(
                    line.split("=", 1) for line in stack["config"]["environment"].splitlines()
                    if line.strip()
                )
                self.assertIn("GATUS_BACKREST_ENDPOINT_ID", environment)
                for name, endpoint_key in environment.items():
                    if name.startswith("GATUS_BACKREST_") and name.endswith("_ENDPOINT_ID"):
                        with self.subTest(stack=stack["name"], variable=name):
                            self.assertIn(endpoint_key, endpoint_keys, str(path.relative_to(ROOT)))


if __name__ == "__main__":
    unittest.main()
