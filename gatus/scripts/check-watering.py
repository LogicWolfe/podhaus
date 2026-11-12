#!/usr/bin/env python3
"""Tell Gatus whether the RainMachine watered on its most recent watering day.

The controller's own watering log is the proof. The days it should water on are
household settings given in the environment, not read from its program, so a
program that was edited, switched off or lost in a reset shows up as a missed
day. All dates and times are the controller's local clock.
"""

import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MONTHS = (
    "jan", "feb", "mar", "apr", "may", "jun",
    "jul", "aug", "sep", "oct", "nov", "dec",
)  # fmt: skip
# A zone that ran this share of what the controller set for it counts as watered.
DELIVERED_SHARE = 0.9
# The controller's log files manual runs under program 0.
MANUAL_RUN = 0


@dataclass(frozen=True)
class Roster:
    """The days watering is expected on."""

    weekdays: frozenset[int]
    dormant_months: frozenset[int]
    done_by: time

    @classmethod
    def from_environment(cls) -> "Roster":
        days = os.environ["WATERING_DAYS"].split(",")
        months = os.environ["NO_WATERING_MONTHS"].split(",")
        return cls(
            weekdays=frozenset(WEEKDAYS.index(day) for day in days),
            dormant_months=frozenset(MONTHS.index(month) + 1 for month in months),
            done_by=time.fromisoformat(os.environ["WATERING_DONE_BY"]),
        )

    def latest_due_day(self, now: datetime) -> date:
        """The newest watering day whose run should already have finished."""
        day = now.date() if now.time() >= self.done_by else now.date() - timedelta(days=1)
        while day.weekday() not in self.weekdays:
            day -= timedelta(days=1)
        return day

    def is_dormant(self, day: date) -> bool:
        return day.month in self.dormant_months


@dataclass(frozen=True)
class ZoneRun:
    """What one zone was set to run and what it ran, in one program run."""

    zone: int
    intended_seconds: int
    delivered_seconds: int

    @property
    def cut_short(self) -> bool:
        return self.delivered_seconds < DELIVERED_SHARE * self.intended_seconds


@dataclass(frozen=True)
class Verdict:
    watered: bool
    detail: str


class RainMachine:
    """A signed-in session with the controller's local API."""

    def __init__(self, api: str, token: str) -> None:
        self._api = api
        self._token = token

    @classmethod
    def sign_in(cls, base_url: str, password: str) -> "RainMachine":
        api = f"{base_url}/api/4"
        request = urllib.request.Request(
            f"{api}/auth/login",
            data=json.dumps({"pwd": password, "remember": 0}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            return cls(api, json.load(response)["access_token"])

    def _get(self, path: str) -> dict:
        query = urllib.parse.urlencode({"access_token": self._token})
        with urllib.request.urlopen(f"{self._api}/{path}?{query}", timeout=20) as response:
            return json.load(response)

    def clock(self) -> datetime:
        return datetime.fromisoformat(self._get("machine/time")["appDate"])

    def active_program_start_dates(self) -> list[date]:
        programs = self._get("program")["programs"]
        return [date.fromisoformat(p["startDate"]) for p in programs if p["active"]]

    def zone_name(self, zone: int) -> str:
        names = {entry["uid"]: entry["name"] for entry in self._get("zone")["zones"]}
        return names[zone]

    def program_runs(self, day: date) -> list[ZoneRun]:
        """Every zone run a program made on a day; manual runs are left out."""
        log = self._get(f"watering/log/details/{day.isoformat()}/1")["waterLog"]
        return [
            ZoneRun(
                zone=zone["uid"],
                intended_seconds=sum(c["machineDuration"] for c in zone["cycles"]),
                delivered_seconds=sum(c["realDuration"] for c in zone["cycles"]),
            )
            for logged in log["days"]
            if logged["date"] == day.isoformat()
            for program in logged["programs"]
            if program["id"] != MANUAL_RUN
            for zone in program["zones"]
        ]


class WateringCheck:
    def __init__(self, roster: Roster, controller: RainMachine) -> None:
        self._roster = roster
        self._controller = controller

    def verdict(self) -> Verdict:
        start_dates = self._controller.active_program_start_dates()
        if not start_dates:
            return Verdict(False, "No watering program is switched on in the RainMachine.")
        day = self._roster.latest_due_day(self._controller.clock())
        if day < min(start_dates):
            return Verdict(True, f"The program starts after {_named(day)}; no run is due yet.")
        if self._roster.is_dormant(day):
            return Verdict(True, f"{_named(day)} is in the months with no watering.")
        return self._judge(day, self._controller.program_runs(day))

    def _judge(self, day: date, runs: list[ZoneRun]) -> Verdict:
        if not runs:
            return Verdict(False, f"No watering program ran on {_named(day)}.")
        short = [run for run in runs if run.cut_short]
        if short:
            zones = ", ".join(self._shortfall(run) for run in short)
            return Verdict(False, f"Watering on {_named(day)} was cut short: {zones}.")
        return Verdict(True, f"Watered in full on {_named(day)}.")

    def _shortfall(self, run: ZoneRun) -> str:
        delivered = round(run.delivered_seconds / 60)
        intended = round(run.intended_seconds / 60)
        return f"{self._controller.zone_name(run.zone)} ran {delivered} of {intended} minutes"


def _named(day: date) -> str:
    return f"{day:%A} {day.day} {day:%B}"


def publish(verdict: Verdict) -> None:
    query = urllib.parse.urlencode(
        {
            "success": "true" if verdict.watered else "false",
            "error": "" if verdict.watered else verdict.detail,
        }
    )
    request = urllib.request.Request(
        f"{os.environ['GATUS_BASE_URL']}/api/v1/endpoints/irrigation_watering/external?{query}",
        method="POST",
        headers={"Authorization": f"Bearer {os.environ['GATUS_HEARTBEAT_PUSH_TOKEN']}"},
    )
    urllib.request.urlopen(request, timeout=20).close()


def main() -> None:
    controller = RainMachine.sign_in(
        os.environ["RAINMACHINE_URL"], os.environ["RAINMACHINE_PASSWORD"]
    )
    verdict = WateringCheck(Roster.from_environment(), controller).verdict()
    print(f"watering monitor: {verdict.detail}")
    publish(verdict)
    if not verdict.watered:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
