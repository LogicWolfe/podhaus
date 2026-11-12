#!/usr/bin/env python3
"""Ship the RainMachine irrigation controller's readings to ClickStack.

Gauges under service.name `rainmachine`, read by the Gatus Irrigation checks
and the dash watering page:

  rainmachine.uptime          The controller's uptime in seconds, stamped now.
                              Sent first and only when the controller answered,
                              so a gap means the controller or this job is down.
  rainmachine.cycle.watered   Seconds a zone ran in one unbroken stretch.
  rainmachine.cycle.intended  Seconds the controller set that stretch to run.

The two cycle gauges are stamped at the moment the stretch started and carry
`day` (the controller's local date), `zone` (its name) and `run` (`program` or
`manual`). Every run sends the trailing week again, so an outage shorter than
that loses nothing; a reader takes the largest value for each timestamp, zone
and run, then adds those up.
"""

import json
import os
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

# The controller's log files manual runs under program 0.
MANUAL_RUN = 0
SHIPPED_DAYS = 7


@dataclass(frozen=True)
class Point:
    metric: str
    epoch: int
    value: float
    labels: dict[str, str]

    def otlp(self) -> dict:
        return {
            "timeUnixNano": str(self.epoch * 1_000_000_000),
            "asDouble": self.value,
            "attributes": [
                {"key": key, "value": {"stringValue": value}}
                for key, value in self.labels.items()
            ],
        }


@dataclass(frozen=True)
class Cycle:
    """One unbroken stretch a zone ran, in a program or manual run."""

    day: date
    zone_name: str
    manual: bool
    started_epoch: int
    intended_seconds: int
    delivered_seconds: int

    def points(self) -> list[Point]:
        labels = {
            "day": self.day.isoformat(),
            "zone": self.zone_name,
            "run": "manual" if self.manual else "program",
        }
        return [
            Point("rainmachine.cycle.watered", self.started_epoch, self.delivered_seconds, labels),
            Point("rainmachine.cycle.intended", self.started_epoch, self.intended_seconds, labels),
        ]


class Session:
    """A signed-in session with the controller's local API."""

    def __init__(self, api: str, token: str) -> None:
        self._api = api
        self._token = token

    def _get(self, path: str) -> dict:
        query = urllib.parse.urlencode({"access_token": self._token})
        with urllib.request.urlopen(f"{self._api}/{path}?{query}", timeout=20) as response:
            return json.load(response)

    def today(self) -> date:
        return datetime.fromisoformat(self._get("machine/time")["appDate"]).date()

    def cycles(self, first_day: date, days: int) -> list[Cycle]:
        """Every cycle the log holds for the days from first_day on."""
        zones = self._get("zone")["zones"]
        names = {entry["uid"]: entry["name"] for entry in zones}
        log = self._get(f"watering/log/details/{first_day.isoformat()}/{days}")["waterLog"]
        return [
            Cycle(
                day=date.fromisoformat(logged["date"]),
                zone_name=names[zone["uid"]],
                manual=program["id"] == MANUAL_RUN,
                started_epoch=cycle["startTimestamp"],
                intended_seconds=cycle["machineDuration"],
                delivered_seconds=cycle["realDuration"],
            )
            for logged in log["days"]
            for program in logged["programs"]
            for zone in program["zones"]
            for cycle in zone["cycles"]
        ]


class RainMachine:
    def __init__(self, base_url: str) -> None:
        self._api = f"{base_url}/api/4"

    def uptime_seconds(self) -> int:
        """Read from the one page that needs no sign-in."""
        with urllib.request.urlopen(f"{self._api}/diag", timeout=20) as response:
            return json.load(response)["uptimeSeconds"]

    def sign_in(self, password: str) -> Session:
        request = urllib.request.Request(
            f"{self._api}/auth/login",
            data=json.dumps({"pwd": password, "remember": 0}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            return Session(self._api, json.load(response)["access_token"])


def ship(points: list[Point]) -> None:
    """Send the points to ClickStack's collector as OTLP gauges."""
    by_metric: dict[str, list[dict]] = defaultdict(list)
    for point in points:
        by_metric[point.metric].append(point.otlp())
    metrics = [
        {"name": name, "unit": "s", "gauge": {"dataPoints": data_points}}
        for name, data_points in by_metric.items()
    ]
    service = {"key": "service.name", "value": {"stringValue": "rainmachine"}}
    resource = {
        "resource": {"attributes": [service]},
        "scopeMetrics": [{"scope": {"name": "watering-monitor"}, "metrics": metrics}],
    }
    request = urllib.request.Request(
        f"{os.environ['OTEL_EXPORTER_OTLP_ENDPOINT']}/v1/metrics",
        data=json.dumps({"resourceMetrics": [resource]}).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": os.environ["CLICKSTACK_INGESTION_KEY"],
        },
    )
    urllib.request.urlopen(request, timeout=20).close()


def main() -> None:
    controller = RainMachine(os.environ["RAINMACHINE_URL"])
    ship([Point("rainmachine.uptime", int(time.time()), controller.uptime_seconds(), {})])
    session = controller.sign_in(os.environ["RAINMACHINE_PASSWORD"])
    first_day = session.today() - timedelta(days=SHIPPED_DAYS - 1)
    cycles = session.cycles(first_day, SHIPPED_DAYS)
    if cycles:
        ship([point for cycle in cycles for point in cycle.points()])


if __name__ == "__main__":
    main()
