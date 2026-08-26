from pathlib import Path
import unittest

import yaml


REPO_ROOT = Path(__file__).resolve().parents[4]
ROLE = Path(__file__).resolve().parents[1]


class RoleContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text())

    def task(self, name: str) -> dict[str, object]:
        return next(task for task in self.tasks if task.get("name") == name)

    def test_every_compose_path_pulls_current_periphery_image(self) -> None:
        system_task = self.task("Bring Periphery up through system Docker")
        self.assertEqual(
            system_task["community.docker.docker_compose_v2"]["pull"],
            "always",
        )

        user_task = self.task(
            "Bring Periphery up through the globally selected user Docker engine"
        )
        self.assertIn("--pull", user_task["ansible.builtin.command"]["argv"])
        self.assertIn("always", user_task["ansible.builtin.command"]["argv"])

        kangaroo = (REPO_ROOT / "kangaroo_bootstrap").read_text()
        self.assertIn("compose up -d --pull always", kangaroo)


if __name__ == "__main__":
    unittest.main()
