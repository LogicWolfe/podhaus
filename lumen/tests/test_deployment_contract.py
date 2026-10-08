import tomllib
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
LUMEN_HOSTS = ("bandicoot", "bilby", "fractal", "quokka", "voltaire")


class DeploymentContractTests(unittest.TestCase):
    def test_every_linux_development_host_has_a_lumen_stack(self) -> None:
        for host in LUMEN_HOSTS:
            with self.subTest(host=host):
                stack_path = REPO / "lumen" / host / "stack.toml"
                compose_path = REPO / "lumen" / host / "compose.yaml"
                stack = tomllib.loads(stack_path.read_text())["stack"][0]

                self.assertEqual(stack["name"], f"{host}-lumen")
                self.assertEqual(stack["config"]["project_name"], "lumen")
                self.assertEqual(
                    stack["config"]["server"], "podhaus" if host == "bilby" else host
                )
                self.assertEqual(
                    stack["config"]["file_paths"],
                    ["compose.shared.yaml", f"{host}/compose.yaml"],
                )
                if host == "bilby":
                    self.assertTrue(stack["config"]["files_on_host"])
                else:
                    self.assertEqual(stack["config"]["linked_repo"], f"podhaus-{host}")
                self.assertEqual(
                    yaml.safe_load(compose_path.read_text()), {"services": {}}
                )

    def test_every_linux_development_host_schedules_the_shared_sweep(self) -> None:
        schedulers = {
            "bilby": (REPO / "ofelia" / "compose.yaml", "jobs/compose.yaml"),
            "bandicoot": (
                REPO / "ofelia" / "bandicoot" / "compose.yaml",
                "../jobs/compose.yaml",
            ),
            "fractal": (
                REPO / "ofelia" / "fractal" / "compose.yaml",
                "../jobs/compose.yaml",
            ),
            "quokka": (
                REPO / "ofelia" / "quokka" / "compose.yaml",
                "../jobs/compose.yaml",
            ),
            "voltaire": (
                REPO / "ofelia" / "voltaire" / "compose.yaml",
                "../jobs/compose.yaml",
            ),
        }
        for host, (path, shared_jobs) in schedulers.items():
            with self.subTest(host=host):
                service = next(
                    iter(yaml.safe_load(path.read_text())["services"].values())
                )
                self.assertEqual(service["extends"]["service"], "scheduler")
                self.assertEqual(service["extends"]["file"], shared_jobs)


if __name__ == "__main__":
    unittest.main()
