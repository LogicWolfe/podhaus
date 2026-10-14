"""The runner stack's deploy contract.

Two lifecycles meet in this stack and neither checks the other: Docker
decides when to kill the runner and when to recreate it, while the runner's
own configuration decides how long it drains running jobs and which
registration it uses.
"""

import re
import tomllib
import unittest
from pathlib import Path

import yaml

STACK = Path(__file__).resolve().parent.parent
DURATION_PART = re.compile(r"(\d+)(h|m|s)")
SECONDS = {"h": 3600, "m": 60, "s": 1}


def seconds(duration: str) -> int:
    parts = DURATION_PART.findall(duration)
    if "".join(n + u for n, u in parts) != duration:
        raise ValueError(f"not an h/m/s duration: {duration!r}")
    return sum(int(n) * SECONDS[u] for n, u in parts)


class RunnerStackTests(unittest.TestCase):
    def setUp(self):
        self.compose = yaml.safe_load((STACK / "compose.yaml").read_text())
        stack = tomllib.loads((STACK / "stack.toml").read_text())
        (self.stack_config,) = [s["config"] for s in stack["stack"]]
        self.config_text = self.compose["configs"]["runner-config"]["content"]

    def test_docker_waits_for_the_runner_to_drain_running_jobs(self):
        runner = yaml.safe_load(self.config_text)["runner"]
        grace = self.compose["services"]["runner"]["stop_grace_period"]
        self.assertGreater(seconds(grace), seconds(runner["shutdown_timeout"]))

    def test_the_runner_never_inherits_an_earlier_registration_file(self):
        # The image declares /data a volume; left undeclared here, a recreate
        # carries the previous container's /data, and its .runner, across.
        mounts = dict(
            reversed(volume.split(":")[:2]) for volume in self.compose["services"]["runner"]["volumes"]
        )
        self.assertIn(mounts["/data"], self.compose["volumes"])

    def test_a_changed_registration_recreates_the_runner(self):
        # Compose recreates nothing when only a config's text changes, so a
        # config that substitutes the stack's environment needs a forced
        # recreate for a rotated value to reach the runner.
        substituted = [line.split("=", 1)[0] for line in self.stack_config["environment"].split()
                       if "${" + line.split("=", 1)[0] + "}" in self.config_text]
        self.assertTrue(substituted)
        self.assertIn("--force-recreate", self.stack_config["extra_args"])


if __name__ == "__main__":
    unittest.main()
