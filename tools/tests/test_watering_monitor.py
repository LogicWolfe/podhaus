import json
import os
import subprocess
import sys
import threading
import unittest
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "gatus/scripts/check-watering.py"
PASSWORD = "controller-password"
TOKEN = "session-token"


def zone_run(zone, *, intended, delivered):
    return {
        "uid": zone,
        "cycles": [{"machineDuration": intended, "realDuration": delivered}],
    }


def logged_day(day, *, program, zones):
    return {"date": day, "programs": [{"id": program, "zones": zones}]}


@dataclass
class Controller:
    """What the fake RainMachine answers with, and what Gatus was told."""

    clock: str
    programs: list = field(
        default_factory=lambda: [{"active": True, "startDate": "2026-01-01"}]
    )
    log: list = field(default_factory=list)
    reports: list = field(default_factory=list)


class Handler(BaseHTTPRequestHandler):
    controller: Controller

    def log_message(self, *_):
        pass

    def reply(self, status, body):
        self.send_response(status)
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def do_POST(self):
        url = urlsplit(self.path)
        length = int(self.headers.get("Content-Length", 0))
        if url.path == "/api/4/auth/login":
            signed_in = json.loads(self.rfile.read(length))["pwd"] == PASSWORD
            self.reply(200, {"access_token": TOKEN}) if signed_in else self.reply(401, {})
        elif url.path == "/api/v1/endpoints/irrigation_watering/external":
            self.controller.reports.append(
                {k: v[0] for k, v in parse_qs(url.query, keep_blank_values=True).items()}
                | {"authorization": self.headers["Authorization"]}
            )
            self.reply(200, {})
        else:
            self.reply(404, {})

    def do_GET(self):
        url = urlsplit(self.path)
        if parse_qs(url.query).get("access_token") != [TOKEN]:
            return self.reply(401, {})
        path = url.path.removeprefix("/api/4/")
        if path == "machine/time":
            self.reply(200, {"appDate": self.controller.clock})
        elif path == "program":
            self.reply(200, {"programs": self.controller.programs})
        elif path == "zone":
            self.reply(200, {"zones": [{"uid": 4, "name": "Front Lawn"}]})
        elif path.startswith("watering/log/details/"):
            day = path.split("/")[3]
            days = [entry for entry in self.controller.log if entry["date"] == day]
            self.reply(200, {"waterLog": {"days": days}})
        else:
            self.reply(404, {})


class WateringMonitorTests(unittest.TestCase):
    def check(self, controller, *, password=PASSWORD):
        handler = type("BoundHandler", (Handler,), {"controller": controller})
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        address = f"http://127.0.0.1:{server.server_port}"
        return subprocess.run(
            [sys.executable, str(SCRIPT)],
            env=os.environ
            | {
                "RAINMACHINE_URL": address,
                "RAINMACHINE_PASSWORD": password,
                "WATERING_DAYS": "tue,sat",
                "NO_WATERING_MONTHS": "jun,jul,aug",
                "WATERING_DONE_BY": "08:00",
                "GATUS_BASE_URL": address,
                "GATUS_HEARTBEAT_PUSH_TOKEN": "push-token",
            },
            capture_output=True,
            text=True,
        )

    def test_a_full_run_on_the_latest_watering_day_reports_success(self):
        # 2026-11-14 is a Saturday.
        controller = Controller(
            clock="2026-11-15 10:00:00",
            log=[logged_day("2026-11-14", program=1, zones=[zone_run(4, intended=3600, delivered=3600)])],
        )
        result = self.check(controller)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            controller.reports,
            [{"success": "true", "error": "", "authorization": "Bearer push-token"}],
        )

    def test_a_watering_day_with_no_program_run_is_reported_as_missed(self):
        controller = Controller(clock="2026-11-15 10:00:00")
        result = self.check(controller)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(controller.reports[0]["success"], "false")
        self.assertIn("Saturday 14 November", controller.reports[0]["error"])

    def test_a_manual_run_does_not_count_as_the_days_watering(self):
        controller = Controller(
            clock="2026-11-15 10:00:00",
            log=[logged_day("2026-11-14", program=0, zones=[zone_run(4, intended=60, delivered=60)])],
        )
        self.check(controller)
        self.assertEqual(controller.reports[0]["success"], "false")

    def test_a_zone_cut_short_is_reported_by_name(self):
        controller = Controller(
            clock="2026-11-15 10:00:00",
            log=[logged_day("2026-11-14", program=1, zones=[zone_run(4, intended=3600, delivered=720)])],
        )
        self.check(controller)
        self.assertEqual(controller.reports[0]["success"], "false")
        self.assertIn("Front Lawn ran 12 of 60 minutes", controller.reports[0]["error"])

    def test_a_run_still_in_progress_is_not_judged_yet(self):
        # Saturday morning before the done-by time: Tuesday is the day on trial.
        controller = Controller(
            clock="2026-11-14 05:00:00",
            log=[logged_day("2026-11-10", program=1, zones=[zone_run(4, intended=3600, delivered=3600)])],
        )
        self.check(controller)
        self.assertEqual(controller.reports[0]["success"], "true")

    def test_no_run_is_expected_in_the_months_without_watering(self):
        # 2026-07-14 is a Tuesday.
        controller = Controller(clock="2026-07-15 10:00:00")
        self.check(controller)
        self.assertEqual(controller.reports[0]["success"], "true")

    def test_no_run_is_expected_before_the_program_starts(self):
        controller = Controller(
            clock="2026-11-12 10:00:00",
            programs=[{"active": True, "startDate": "2026-11-12"}],
        )
        self.check(controller)
        self.assertEqual(controller.reports[0]["success"], "true")

    def test_a_switched_off_program_is_reported(self):
        controller = Controller(
            clock="2026-11-15 10:00:00",
            programs=[{"active": False, "startDate": "2026-01-01"}],
            log=[logged_day("2026-11-14", program=1, zones=[zone_run(4, intended=3600, delivered=3600)])],
        )
        self.check(controller)
        self.assertEqual(controller.reports[0]["success"], "false")
        self.assertIn("switched on", controller.reports[0]["error"])

    def test_a_refused_sign_in_reports_nothing(self):
        controller = Controller(clock="2026-11-15 10:00:00")
        result = self.check(controller, password="wrong")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(controller.reports, [])


if __name__ == "__main__":
    unittest.main()
