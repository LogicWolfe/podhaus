import json
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


class FleetMonitoringTests(unittest.TestCase):
    def setUp(self):
        inventory = yaml.safe_load((REPO / "ansible/inventory/hosts.yml").read_text())
        self.groups = inventory["all"]["children"]
        self.config = yaml.safe_load((REPO / "gatus/conf/config.yaml").read_text())
        self.endpoints = self.config["endpoints"]

    def komodo_checks(self, *, request_type, server):
        return [
            endpoint
            for endpoint in self.endpoints
            if endpoint.get("body", "").startswith("{")
            and json.loads(endpoint["body"])["type"] == request_type
            and json.loads(endpoint["body"])["params"]["server"] == server
        ]

    def test_every_periphery_has_a_health_check(self):
        for host in self.groups["komodo_periphery_hosts"]["hosts"]:
            with self.subTest(host=host):
                server = "podhaus" if host == "bilby" else host
                checks = self.komodo_checks(request_type="GetServerState", server=server)
                self.assertEqual(len(checks), 1)

    def test_every_docs_host_has_a_docs_container_check(self):
        # bilby's docs container shares Gatus's network and is checked directly.
        for host in self.groups["docs_hosts"]["hosts"]:
            if host == "bilby":
                continue
            with self.subTest(host=host):
                checks = self.komodo_checks(request_type="InspectDockerContainer", server=host)
                containers = [json.loads(check["body"])["params"]["container"] for check in checks]
                self.assertEqual(containers.count("docs"), 1)

    def test_every_value_pasted_into_an_alert_is_json_safe(self):
        # The custom alerter pastes each endpoint's name, group and alert
        # description into a JSON body without escaping, so a quote, a
        # backslash or a newline in any of them breaks that alert's delivery.
        alerting = 0
        for endpoint in self.endpoints + self.config["external-endpoints"]:
            alerts = [alert for alert in endpoint.get("alerts", []) if alert["type"] == "custom"]
            if not alerts:
                continue
            alerting += 1
            pasted = [endpoint["name"], endpoint.get("group", "")]
            pasted += [alert.get("description", "") for alert in alerts]
            for value in pasted:
                with self.subTest(endpoint=endpoint["name"], value=value[:60]):
                    for unsafe in ('"', "\\", "\n"):
                        self.assertNotIn(unsafe, value)
        self.assertTrue(alerting)


if __name__ == "__main__":
    unittest.main()
