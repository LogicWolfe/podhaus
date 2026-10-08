import json
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


class FleetMonitoringTests(unittest.TestCase):
    def setUp(self):
        inventory = yaml.safe_load((REPO / "ansible/inventory/hosts.yml").read_text())
        self.groups = inventory["all"]["children"]
        config = yaml.safe_load((REPO / "gatus/conf/config.yaml").read_text())
        self.endpoints = config["endpoints"]

    def komodo_check(self, *, request_type, server, group):
        matches = []
        for endpoint in self.endpoints:
            if endpoint["group"] != group or "body" not in endpoint:
                continue
            if not endpoint["body"].startswith("{"):
                continue
            request = json.loads(endpoint["body"])
            if (
                request["type"] == request_type
                and request["params"]["server"] == server
            ):
                matches.append(endpoint)
        self.assertEqual(len(matches), 1, f"{request_type} on {server}")
        return matches[0]

    def test_every_periphery_has_a_health_check(self):
        for host in self.groups["komodo_periphery_hosts"]["hosts"]:
            with self.subTest(host=host):
                server = "podhaus" if host == "bilby" else host
                check = self.komodo_check(
                    request_type="GetServerState", server=server, group="Komodo"
                )
                self.assertEqual(check["method"], "POST")
                self.assertIn("[STATUS] == 200", check["conditions"])
                self.assertIn("[BODY].status == Ok", check["conditions"])

    def test_every_docs_host_has_source_aware_health_coverage(self):
        for host in self.groups["docs_hosts"]["hosts"]:
            with self.subTest(host=host):
                if host == "bilby":
                    checks = [
                        e
                        for e in self.endpoints
                        if e["url"] == "http://docs:8000/health"
                    ]
                    self.assertEqual(len(checks), 1)
                    self.assertIn("[STATUS] == 200", checks[0]["conditions"])
                    continue
                check = self.komodo_check(
                    request_type="InspectDockerContainer", server=host, group="Docs"
                )
                request = json.loads(check["body"])
                self.assertEqual(request["params"]["container"], "docs")
                self.assertIn("[BODY].State.Status == running", check["conditions"])
                self.assertIn(
                    "[BODY].State.Health.Status == healthy", check["conditions"]
                )
