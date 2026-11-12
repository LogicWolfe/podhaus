import json
import os
import subprocess
import sys
import threading
import unittest
from dataclasses import dataclass, field
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "gatus/scripts/ship-watering.py"
PASSWORD = "controller-password"
TOKEN = "session-token"
INGESTION_KEY = "ingestion-key"
STARTED = 1794600000


def zone_run(zone, *, intended, delivered, started=STARTED):
    return {
        "uid": zone,
        "cycles": [
            {"startTimestamp": started, "machineDuration": intended, "realDuration": delivered}
        ],
    }


def logged_day(day, *, program, zones):
    return {"date": day, "programs": [{"id": program, "zones": zones}]}


@dataclass
class Controller:
    """What the fake RainMachine answers with, and what the collector was sent."""

    today: str = "2026-11-15"
    uptime: int = 4242
    log: list = field(default_factory=list)
    shipped: list = field(default_factory=list)


class Handler(BaseHTTPRequestHandler):
    controller: Controller

    def log_message(self, *_):
        pass

    def reply(self, status, body):
        self.send_response(status)
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/4/auth/login":
            signed_in = body["pwd"] == PASSWORD
            self.reply(200, {"access_token": TOKEN}) if signed_in else self.reply(401, {})
        elif self.path == "/v1/metrics":
            if self.headers["Authorization"] != INGESTION_KEY:
                return self.reply(401, {})
            self.controller.shipped.append(body)
            self.reply(200, {})
        else:
            self.reply(404, {})

    def do_GET(self):
        url = urlsplit(self.path)
        path = url.path.removeprefix("/api/4/")
        if path == "diag":
            return self.reply(200, {"uptimeSeconds": self.controller.uptime})
        if parse_qs(url.query).get("access_token") != [TOKEN]:
            return self.reply(401, {})
        if path == "machine/time":
            self.reply(200, {"appDate": f"{self.controller.today} 10:00:00"})
        elif path == "zone":
            zones = [{"uid": 4, "name": "Front Lawn"}, {"uid": 5, "name": "Back Fence"}]
            self.reply(200, {"zones": zones})
        elif path.startswith("watering/log/details/"):
            first = date.fromisoformat(path.split("/")[3])
            last = first + timedelta(days=int(path.split("/")[4]) - 1)
            days = [
                entry
                for entry in self.controller.log
                if first <= date.fromisoformat(entry["date"]) <= last
            ]
            self.reply(200, {"waterLog": {"days": days}})
        else:
            self.reply(404, {})


class WateringMonitorTests(unittest.TestCase):
    def serve(self, controller):
        handler = type("BoundHandler", (Handler,), {"controller": controller})
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_port}"

    def ship(self, controller, *, password=PASSWORD, controller_url=None):
        address = self.serve(controller)
        return subprocess.run(
            [sys.executable, str(SCRIPT)],
            env=os.environ
            | {
                "RAINMACHINE_URL": controller_url or address,
                "RAINMACHINE_PASSWORD": password,
                "OTEL_EXPORTER_OTLP_ENDPOINT": address,
                "CLICKSTACK_INGESTION_KEY": INGESTION_KEY,
            },
            capture_output=True,
            text=True,
        )

    def points(self, controller, metric):
        return sorted(
            (
                {a["key"]: a["value"]["stringValue"] for a in point["attributes"]}
                | {"value": point["asDouble"], "at": point["timeUnixNano"]}
                for body in controller.shipped
                for resource in body["resourceMetrics"]
                for scope in resource["scopeMetrics"]
                for shipped in scope["metrics"]
                if shipped["name"] == metric
                for point in shipped["gauge"]["dataPoints"]
            ),
            key=lambda point: (point.get("day", ""), point.get("zone", ""), point["at"]),
        )

    def test_each_cycle_of_the_week_is_shipped_at_its_own_start(self):
        controller = Controller(
            log=[
                logged_day("2026-11-08", program=1, zones=[zone_run(4, intended=3600, delivered=3600)]),
                logged_day(
                    "2026-11-14",
                    program=1,
                    zones=[
                        zone_run(4, intended=1200, delivered=1200),
                        zone_run(4, intended=1200, delivered=600, started=STARTED + 3600),
                        zone_run(5, intended=1200, delivered=1200),
                    ],
                ),
                logged_day("2026-11-15", program=0, zones=[zone_run(5, intended=60, delivered=60)]),
            ],
        )
        result = self.ship(controller)
        self.assertEqual(result.returncode, 0, result.stderr)
        first, second = str(STARTED * 1_000_000_000), str((STARTED + 3600) * 1_000_000_000)
        self.assertEqual(
            self.points(controller, "rainmachine.cycle.watered"),
            [
                {"day": "2026-11-14", "zone": "Back Fence", "run": "program", "value": 1200, "at": first},
                {"day": "2026-11-14", "zone": "Front Lawn", "run": "program", "value": 1200, "at": first},
                {"day": "2026-11-14", "zone": "Front Lawn", "run": "program", "value": 600, "at": second},
                {"day": "2026-11-15", "zone": "Back Fence", "run": "manual", "value": 60, "at": first},
            ],
        )
        self.assertEqual(
            [point["value"] for point in self.points(controller, "rainmachine.cycle.intended")],
            [1200, 1200, 1200, 60],
        )

    def test_an_answering_controller_ships_its_uptime(self):
        controller = Controller(uptime=4242)
        result = self.ship(controller)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            [point["value"] for point in self.points(controller, "rainmachine.uptime")], [4242]
        )

    def test_a_week_without_watering_ships_no_amounts(self):
        controller = Controller()
        self.ship(controller)
        self.assertEqual(self.points(controller, "rainmachine.cycle.watered"), [])

    def test_an_unreachable_controller_ships_nothing(self):
        controller = Controller()
        result = self.ship(controller, controller_url="http://127.0.0.1:9")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(controller.shipped, [])

    def test_a_refused_sign_in_still_ships_the_uptime(self):
        controller = Controller(
            log=[logged_day("2026-11-14", program=1, zones=[zone_run(4, intended=60, delivered=60)])]
        )
        result = self.ship(controller, password="wrong")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.points(controller, "rainmachine.uptime")), 1)
        self.assertEqual(self.points(controller, "rainmachine.cycle.watered"), [])


if __name__ == "__main__":
    unittest.main()
