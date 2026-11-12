#!/usr/bin/env python3
"""Ship the RainMachine irrigation controller's readings to ClickStack.

Gauges under service.name `rainmachine`, read by the Gatus Irrigation checks
and the dash watering page:

  rainmachine.uptime         The controller's uptime in seconds, stamped now.
                             Sent first and only when the controller answered,
                             so a gap means the controller or this job is down.
  rainmachine.zone.watered   Seconds one zone ran on one day.
  rainmachine.zone.intended  Seconds the controller set that zone to run.

The two zone gauges carry `day` (the controller's local date), `zone` (its
name) and `run` (`program` or `manual`), stamped at the zone's first start that
day. Every run sends the trailing week again, so an outage shorter than that
loses nothing; a reader takes the largest value for each day, zone and run.
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
class ZoneRun:
    """What one zone was set to run and what it ran, in one program or manual run."""

    day: date
    zone: int
    manual: bool
    started_epoch: int
    intended_seconds: int
    delivered_seconds: int


@dataclass(frozen=True)
class DailyAmount:
    """What one zone ran on one day, by program or by hand."""

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
            Point("rainmachine.zone.watered", self.started_epoch, self.delivered_seconds, labels),
            Point("rainmachine.zone.intended", self.started_epoch, self.intended_seconds, labels),
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

    def zone_names(self) -> dict[int, str]:
        return {entry["uid"]: entry["name"] for entry in self._get("zone")["zones"]}

    def zone_runs(self, first_day: date, days: int) -> list[ZoneRun]:
        """Every zone run the log holds for the days from first_day on."""
        log = self._get(f"watering/log/details/{first_day.isoformat()}/{days}")["waterLog"]
        return [
            ZoneRun(
                day=date.fromisoformat(logged["date"]),
                zone=zone["uid"],
                manual=program["id"] == MANUAL_RUN,
                started_epoch=min(c["startTimestamp"] for c in zone["cycles"]),
                intended_seconds=sum(c["machineDuration"] for c in zone["cycles"]),
                delivered_seconds=sum(c["realDuration"] for c in zone["cycles"]),
            )
            for logged in log["days"]
            for program in logged["programs"]
            for zone in program["zones"]
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


def daily_amounts(runs: list[ZoneRun], zone_names: dict[int, str]) -> list[DailyAmount]:
    grouped: dict[tuple[date, int, bool], list[ZoneRun]] = defaultdict(list)
    for run in runs:
        grouped[(run.day, run.zone, run.manual)].append(run)
    return [
        DailyAmount(
            day=day,
            zone_name=zone_names[zone],
            manual=manual,
            started_epoch=min(run.started_epoch for run in group),
            intended_seconds=sum(run.intended_seconds for run in group),
            delivered_seconds=sum(run.delivered_seconds for run in group),
        )
        for (day, zone, manual), group in grouped.items()
    ]


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
    amounts = daily_amounts(session.zone_runs(first_day, SHIPPED_DAYS), session.zone_names())
    if amounts:
        ship([point for amount in amounts for point in amount.points()])


if __name__ == "__main__":
    main()
