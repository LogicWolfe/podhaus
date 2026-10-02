"""Gatus alerts for the local model service: one check per container, no others."""

from __future__ import annotations

from pathlib import Path
import json
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONTAINERS = ("llm-server", "llm-watcher")


def local_model_checks() -> dict[str, dict]:
    config = yaml.safe_load((ROOT / "gatus/conf/config.yaml").read_text())
    checks = {}
    for endpoint in config["endpoints"]:
        body = endpoint.get("body", "")
        for container in CONTAINERS:
            if f'"container":"{container}"' in body:
                assert container not in checks, f"two checks read {container}"
                checks[container] = endpoint
    return checks


class LocalModelGatusChecksTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.checks = local_model_checks()

    def test_each_container_has_one_check(self) -> None:
        self.assertEqual(set(self.checks), set(CONTAINERS))

    def test_the_checks_read_the_container_on_fractal_through_komodo(self) -> None:
        for container, endpoint in self.checks.items():
            with self.subTest(container=container):
                self.assertEqual(
                    json.loads(endpoint["body"]),
                    {"type": "InspectDockerContainer",
                     "params": {"server": "fractal", "container": container}},
                )
                self.assertEqual(endpoint["method"], "POST")
                self.assertTrue(endpoint["url"].endswith(":9120/read"))
                self.assertIn("X-Api-Key", endpoint["headers"])

    def test_the_checks_require_running_and_healthy(self) -> None:
        for container, endpoint in self.checks.items():
            with self.subTest(container=container):
                self.assertEqual(
                    endpoint["conditions"],
                    ["[STATUS] == 200", "[BODY].State.Status == running",
                     "[BODY].State.Health.Status == healthy"],
                )

    def test_alerts_go_through_the_default_alerter_with_a_description(self) -> None:
        for container, endpoint in self.checks.items():
            with self.subTest(container=container):
                (alert,) = endpoint["alerts"]
                self.assertEqual(alert["type"], "custom")
                self.assertGreater(len(alert["description"]), 100)

    def test_descriptions_are_safe_to_substitute_into_the_alert_json(self) -> None:
        """Gatus pastes [ALERT_DESCRIPTION] into a JSON string without escaping."""
        for container, endpoint in self.checks.items():
            description = endpoint["alerts"][0]["description"]
            with self.subTest(container=container):
                self.assertNotIn('"', description)
                self.assertNotIn("\\", description)
                self.assertNotIn("\n", description)

    def test_the_server_description_says_a_yielded_model_is_not_this_alert(self) -> None:
        description = self.checks["llm-server"]["alerts"][0]["description"].lower()
        self.assertIn("no model loaded", description)
        self.assertIn("every local model request fails", description)

    def test_the_watcher_description_names_each_unhealthy_reason_and_where_to_look(self) -> None:
        description = self.checks["llm-watcher"]["alerts"][0]["description"]
        for needle in (
            "yield_stuck", "vram_at_limit", "load_given_up", "server_unresponsive",
            "30 seconds", "about a fiftieth", "timed out", "died while serving", "five minutes",
            "docker logs llm-watcher", "watcher.unhealthy", "load.failed",
            "restarting", "sample_stale", "router", "unreachable", "llm-server restart",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, description)

    def test_sample_stale_is_described_as_the_watcher_ending_itself_not_as_an_unhealthy_reason(self) -> None:
        description = self.checks["llm-watcher"]["alerts"][0]["description"]
        listed_reasons = description.split("Not running or restarting")[0]
        self.assertNotIn("sample_stale", listed_reasons)

    def test_the_watcher_description_does_not_claim_autoheal_restarts_it(self) -> None:
        """A stalled watcher ends its own process and Docker restarts it; autoheal is not involved."""
        self.assertNotIn("utoheal", self.checks["llm-watcher"]["alerts"][0]["description"])


if __name__ == "__main__":
    unittest.main()
