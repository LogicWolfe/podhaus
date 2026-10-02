"""Who holds the GPU, and every move between the model and a game.

Serving -> Yielding -> Yielded -> Resuming -> Serving, from "GPU handoff
between the model and a game" in docs/plans/local-llm-service.html. A load is
blind, like a busy slot: its own GPU activity cannot be told from a game's, so
only the Yield button ends one early. On every tick the router's state is
checked against what the phase expects, because something other than the
watcher can load the model or end it.

Every time held here is on the monotonic clock; the event log turns the ones
it reports into wall times.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import json
import math
import threading
from typing import ClassVar, Literal, TextIO

from .clock import Clock
from .gpu import GpuReader, GpuReading
from .guest import Guest, GuestMemory
from .model_server import ModelServer, ModelServerError, ModelState, ModelStatus, Slot
from .settings import Settings

# Raw samples attached to each yield, so the thresholds can be corrected from real sessions.
RECORD_SECONDS = 30.0
LOAD_ATTEMPTS = 5
# Doubles after each failed load. A failed load's own GPU activity restarts the
# quiet period, so in practice the first retries wait out that, not this.
FIRST_RETRY_SECONDS = 15.0
STABLE_SECONDS = 600.0  # a model loaded this long has stopped failing, and its failures are forgotten
STATE_NAMES = ("serving", "yielding", "yielded", "resuming")

Level = Literal["info", "warning", "error"]
Unhealthy = Literal["yield_stuck", "vram_at_limit", "load_given_up", "server_unresponsive"]
# The watchdog's own reason, logged as it ends the process; never a health answer.
Stalled = Literal["sample_stale"]


def rfc3339(wall: float) -> str:
    return datetime.fromtimestamp(wall, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class EventLog:
    """One JSON object per line on stdout. Never carries conversation text: the
    watcher sees only counts and flags."""

    def __init__(self, stream: TextIO, clock: Clock) -> None:
        self._stream = stream
        self._clock = clock

    def write(self, level: Level, event: str, msg: str, fields: Mapping[str, object]) -> None:
        line = {"ts": rfc3339(self._clock.wall()), "level": level, "event": event, "msg": msg, **fields}
        self._stream.write(json.dumps(line) + "\n")
        self._stream.flush()

    def date(self, t: float) -> str:
        """Monotonic instant `t` as a wall time for an event's fields, so the
        gaps between an event's times are true durations."""
        return rfc3339(self._clock.wall_at(t))

    def date_or_none(self, t: float | None) -> str | None:
        return None if t is None else self.date(t)


class Trigger(Enum):
    AUTOMATIC = "automatic"
    BUTTON = "button"
    EXTERNAL_LOAD = "external_load"  # something other than the watcher loaded the model


@dataclass(frozen=True)
class Sample:
    t: float
    util: int
    busy: bool  # a slot was busy, or there was no slot report
    # Taken while Serving, with the model doing no work of its own at this
    # sample or the one before: while it loads, reads or generates, its own
    # work hides everything else on the GPU.
    counted: bool


@dataclass(frozen=True)
class Handoff:
    """A yield's record, written once the router reports the model gone."""

    trigger: Trigger
    decided: float
    first_activity: float | None
    requests_cut: int
    busy_before_s: float
    guest_mem_used_before_mib: int
    samples: tuple[Sample, ...]


ANY_STATE = frozenset(ModelState)


@dataclass(frozen=True)
class Serving:
    name: ClassVar[str] = "serving"
    expects: ClassVar[frozenset[ModelState]] = frozenset({ModelState.LOADED})
    since: float


@dataclass(frozen=True)
class Yielding:
    name: ClassVar[str] = "yielding"
    expects: ClassVar[frozenset[ModelState]] = ANY_STATE  # until the router reports the unload done
    since: float
    handoff: Handoff | None  # None when the unload ends a load that timed out
    resume_pressed: bool  # Resume was pressed since: load once the unload is done


@dataclass(frozen=True)
class Yielded:
    name: ClassVar[str] = "yielded"
    expects: ClassVar[frozenset[ModelState]] = frozenset({ModelState.UNLOADED})


@dataclass(frozen=True)
class Resuming:
    name: ClassVar[str] = "resuming"
    expects: ClassVar[frozenset[ModelState]] = ANY_STATE  # loading, then loaded or failed
    trigger: Trigger
    quiet_since: float | None  # None for a load the watcher found rather than started
    load_started: float


Phase = Serving | Yielding | Yielded | Resuming


def exited(status: ModelStatus) -> str:
    """How the model process ended. The router gives an exit code only for a failure."""
    code = "" if status.exit_code is None else f" with code {status.exit_code}"
    return f"model process exited{code}"


def found(state: ModelState, now: float, trigger: Trigger) -> Phase:
    """The phase for a router state the watcher did not bring about: at start,
    or when something else loaded or ended the model."""
    match state:
        case ModelState.LOADED:
            return Serving(since=now)
        case ModelState.UNLOADED:
            return Yielded()
        case ModelState.LOADING:
            return Resuming(trigger, None, now)


@dataclass(frozen=True)
class Snapshot:
    state: str
    held: bool
    sample_age_s: float
    gpu: GpuReading
    guest: GuestMemory
    pool_tokens: int
    pool_limit: int


class Watcher:
    """Owns who holds the GPU. tick() runs once a second and the buttons call
    in from the HTTP threads; both take the lock. The page, metrics and health
    check read without it, so a slow or stuck tick never holds them up: every
    attribute they read is replaced whole, never changed in place."""

    def __init__(self, settings: Settings, gpu: GpuReader, server: ModelServer, guest: Guest,
                 log: EventLog, clock: Clock, phase: Phase, reading: GpuReading) -> None:
        now = clock.monotonic()
        self._settings = settings
        self._gpu = gpu
        self._server = server
        self._guest = guest
        self._log = log
        self._clock = clock
        self._lock = threading.Lock()
        self._phase: Phase = phase
        # None until the first tick, which then drops the cache of a model found loaded or unloaded.
        self._router_state: ModelState | None = None
        self._reading, self._sampled_at = reading, now
        self._samples: deque[Sample] = deque()
        self._slots: tuple[Slot, ...] = ()
        self._started_at = now  # the quiet period counts from here until activity is seen
        self._last_active_at = -math.inf
        self._busy_since = self._busy_until = -math.inf  # the latest busy stretch
        self._silent_since: float | None = None  # the first of an unbroken run of reads with no slot report
        self._hold_until = self._retry_at = now
        self._failures = 0
        self._reported: Unhealthy | Stalled | None = None

    @classmethod
    def adopt(cls, settings: Settings, gpu: GpuReader, server: ModelServer, guest: Guest,
              log: EventLog, clock: Clock) -> Watcher:
        """Starts in whichever state the model server is really in."""
        state = server.status().state
        phase = found(state, clock.monotonic(), Trigger.AUTOMATIC)
        log.write("info", "state.adopted", f"adopted {phase.name}",
                  {"state": phase.name, "previous_state": None, "router_state": state.value})
        return cls(settings, gpu, server, guest, log, clock, phase, gpu.read())

    def tick(self) -> None:
        with self._lock:
            now = self._clock.monotonic()
            reading = self._gpu.read()
            status = self._server.status()
            self._observe(now, reading, self._read_slots(now, status))
            self._note_router_state(status.state)
            if status.state in self._phase.expects:
                self._advance(now, status)
            else:
                self._unexpected(now, status)
            self._report(self._unhealthy_reason(now))

    def yield_now(self) -> None:
        """The Yield button: yields at once, cancelling a load in progress, and
        holds the model away for the hold."""
        with self._lock:
            now = self._clock.monotonic()
            self._hold_until = max(self._hold_until, now + self._settings.button_hold_s)
            match self._phase:
                case Serving():
                    self._begin_yield(now, Trigger.BUTTON)
                case Resuming() as resuming:
                    if self._begin_yield(now, Trigger.BUTTON):
                        self._log.write("warning", "handoff.resume_abandoned", "load cancelled", {
                            "load_started_ts": self._log.date(resuming.load_started),
                            "abandoned_ts": self._log.date(now),
                        })
                case Yielding() as yielding:
                    self._phase = replace(yielding, resume_pressed=False)
                case Yielded():
                    pass  # already away; the hold is the button's whole effect

    def resume_now(self) -> None:
        """The Resume button: ends any hold or wait between retries and loads
        now, or as soon as an unload in progress is done."""
        with self._lock:
            now = self._clock.monotonic()
            self._hold_until = self._retry_at = now
            self._failures = 0
            match self._phase:
                case Yielded():
                    self._start_load(now, Trigger.BUTTON)
                case Yielding() as yielding:
                    self._phase = replace(yielding, resume_pressed=True)
                case Serving() | Resuming():
                    pass

    def health(self) -> Unhealthy | None:
        return self._unhealthy_reason(self._clock.monotonic())

    def end_if_stalled(self, exit: Callable[[int], object]) -> None:
        """The watchdog's check, run apart from the sampling loop: once the last
        sample is stale, ends the process so Docker restarts it and it adopts the
        real state. Takes no lock, because the stuck loop may be holding it."""
        if self._clock.monotonic() - self._sampled_at > self._settings.sample_stale_s:
            self._report("sample_stale")
            exit(1)

    def snapshot(self) -> Snapshot:
        now = self._clock.monotonic()
        return Snapshot(
            state=self._phase.name,
            held=now < self._hold_until,
            sample_age_s=now - self._sampled_at,
            gpu=self._reading,
            guest=self._guest.memory(),
            pool_tokens=sum(slot.tokens for slot in self._slots),
            pool_limit=self._settings.pool_tokens,
        )

    def _read_slots(self, now: float, status: ModelStatus) -> tuple[Slot, ...] | None:
        """The slot report, () while the model is not serving, None when there was none."""
        if not (isinstance(self._phase, Serving) and status.state is ModelState.LOADED):
            self._silent_since = None
            return ()
        slots = self._server.slots()
        if slots is not None:
            self._silent_since = None
        elif self._silent_since is None:
            self._silent_since = now
        return slots

    def _observe(self, now: float, reading: GpuReading, slots: tuple[Slot, ...] | None) -> None:
        # No report means the model is inside one long step, or has just ended
        # or begun loading; its last report stands until the status says which.
        busy = slots is None or any(slot.busy for slot in slots)
        previous_busy = bool(self._samples) and self._samples[-1].busy
        counted = isinstance(self._phase, Serving) and not (busy or previous_busy)
        self._samples.append(Sample(now, reading.util_percent, busy, counted))
        while self._samples[0].t <= now - RECORD_SECONDS:
            self._samples.popleft()
        self._reading, self._sampled_at = reading, now
        if reading.util_percent >= self._settings.activity_threshold_percent:
            self._last_active_at = now
        if busy:
            if not previous_busy:
                self._busy_since = now
            self._busy_until = now
        if slots is not None and slots != self._slots:
            self._slots = slots
            self._log_slots()

    def _note_router_state(self, state: ModelState) -> None:
        """Drops the model file's cache whenever the model becomes loaded or
        unloaded, whoever loaded or ended it. Loaded, the model process keeps
        only the pages it maps, at no cost to generation; unloaded, nothing
        reads the file until the next load, which reads it from disk anyway."""
        if state is not self._router_state and state is not ModelState.LOADING:
            self._guest.drop_model_file_cache()
        self._router_state = state

    def _advance(self, now: float, status: ModelStatus) -> None:
        match self._phase:
            case Serving() as serving:
                self._while_serving(now, serving)
            case Yielding() as yielding:
                self._while_yielding(now, status, yielding)
            case Yielded():
                self._while_yielded(now)
            case Resuming() as resuming:
                self._while_resuming(now, status, resuming)

    def _unexpected(self, now: float, status: ModelStatus) -> None:
        """The router is in a state this phase does not expect: something other
        than the watcher loaded the model, or the model process ended."""
        if isinstance(self._phase, Yielded) and self._keeping_away(now):
            self._begin_yield(now, Trigger.EXTERNAL_LOAD)
            return
        previous = self._phase
        self._phase = found(status.state, now, Trigger.EXTERNAL_LOAD)
        self._log.write("warning", "state.adopted", f"found the model {status.state.value}", {
            "state": self._phase.name, "previous_state": previous.name, "router_state": status.state.value})
        if isinstance(previous, Serving) and status.state is ModelState.UNLOADED:
            self._load_failed(now, f"{exited(status)} while serving")

    def _keeping_away(self, now: float) -> bool:
        """A button hold is active, or the GPU has not been quiet for the quiet period."""
        return now < self._hold_until or self._quiet_for(now) < self._settings.quiet_s

    def _while_serving(self, now: float, serving: Serving) -> None:
        if self._failures and now - serving.since >= STABLE_SECONDS:
            self._failures = 0
        if len(self._activity(self._samples)) >= self._settings.activity_samples:
            self._begin_yield(now, Trigger.AUTOMATIC)

    def _begin_yield(self, now: float, trigger: Trigger) -> bool:
        """Transition 1. Unloading cuts any request in flight and frees the VRAM.
        False when the model process had already ended on its own."""
        active = self._activity(self._samples)
        handoff = Handoff(
            trigger=trigger,
            decided=now,
            first_activity=active[0].t if active else None,
            requests_cut=sum(slot.busy for slot in self._slots),
            busy_before_s=self._busy_before(now),
            guest_mem_used_before_mib=self._guest.memory().used_mib,
            samples=tuple(self._samples),
        )
        return self._unload(now, handoff)

    def _unload(self, now: float, handoff: Handoff | None) -> bool:
        """False when the model process had already ended on its own: the phase
        stands, and the next tick's status read handles the end as any other."""
        if not self._server.unload():
            return False
        self._phase = Yielding(since=now, handoff=handoff, resume_pressed=False)
        return True

    def _busy_before(self, now: float) -> float:
        """How long the model was busy just before now: the longest the watcher
        can have been blind to a game."""
        return self._busy_until - self._busy_since if self._busy_until > now - RECORD_SECONDS else 0.0

    def _while_yielding(self, now: float, status: ModelStatus, yielding: Yielding) -> None:
        """Transition 2, once the router reports the model process gone."""
        if status.state is not ModelState.UNLOADED:
            return
        if yielding.handoff is not None:
            self._log_handoff(now, yielding.handoff)
        self._phase = Yielded()
        if yielding.resume_pressed:
            self._start_load(now, Trigger.BUTTON)

    def _log_handoff(self, now: float, handoff: Handoff) -> None:
        date = self._log.date
        self._log.write("info", "handoff.yield", "yielded the GPU", {
            "trigger": handoff.trigger.value,
            "first_activity_ts": self._log.date_or_none(handoff.first_activity),
            "decided_ts": date(handoff.decided),
            "released_ts": date(now),
            "requests_cut": handoff.requests_cut,
            "busy_before_s": handoff.busy_before_s,
            "guest_mem_used_before_mib": handoff.guest_mem_used_before_mib,
            "guest_mem_used_after_mib": self._guest.memory().used_mib,
            "samples": [{"t": date(s.t), "util": s.util, "busy": s.busy} for s in handoff.samples],
        })

    def _quiet_since(self) -> float:
        """The last GPU activity seen, or the watcher's start before any."""
        return max(self._started_at, self._last_active_at)

    def _quiet_for(self, now: float) -> float:
        return now - self._quiet_since()

    def _while_yielded(self, now: float) -> None:
        """Transition 3: the GPU quiet for the quiet period, no hold, no retry pending."""
        quiet = self._quiet_for(now) >= self._settings.quiet_s
        if quiet and self._failures < LOAD_ATTEMPTS and now >= max(self._hold_until, self._retry_at):
            self._start_load(now, Trigger.AUTOMATIC)

    def _start_load(self, now: float, trigger: Trigger) -> None:
        try:
            self._server.load()
        except ModelServerError as error:
            # Refused because something else loaded the model first is not a failed load.
            status = self._server.status()
            if status.state is ModelState.UNLOADED:
                self._load_failed(now, str(error))
            else:
                self._unexpected(now, status)
            return
        self._phase = Resuming(trigger, self._quiet_since(), now)

    def _while_resuming(self, now: float, status: ModelStatus, resuming: Resuming) -> None:
        match status.state:
            case ModelState.LOADED:
                self._resumed(now, resuming)
            case ModelState.UNLOADED:
                self._load_failed(now, exited(status))
                self._phase = Yielded()
            case ModelState.LOADING if now - resuming.load_started > self._settings.load_timeout_s:
                # Not accepted means the load ended meanwhile; the next tick counts how.
                if self._unload(now, None):
                    self._load_failed(now, f"load timed out after {self._settings.load_timeout_s:g} s")
            case ModelState.LOADING:
                pass  # blind, like a busy slot

    def _resumed(self, now: float, resuming: Resuming) -> None:
        """Transition 4."""
        self._log.write("info", "handoff.resume", "model ready", {
            "trigger": resuming.trigger.value,
            "quiet_since_ts": self._log.date_or_none(resuming.quiet_since),
            "load_started_ts": self._log.date(resuming.load_started),
            "ready_ts": self._log.date(now),
        })
        self._phase = Serving(since=now)

    def _load_failed(self, now: float, error: str) -> None:
        self._failures += 1
        self._log.write("error", "load.failed", "model load failed", {"attempt": self._failures, "error": error})
        self._retry_at = now + FIRST_RETRY_SECONDS * 2 ** (self._failures - 1)

    def _activity(self, samples: Sequence[Sample]) -> list[Sample]:
        """Samples that count as Windows wanting the GPU, inside the activity
        window that ends at the newest of `samples`."""
        if not samples:
            return []
        settings = self._settings
        start = samples[-1].t - settings.activity_window_s
        return [s for s in samples if s.t > start and s.counted and s.util >= settings.activity_threshold_percent]

    def _log_slots(self) -> None:
        self._log.write("info", "slots.changed", "slot report changed", {
            "slots": [{"id": slot.id, "tokens": slot.tokens, "busy": slot.busy} for slot in self._slots],
            "pool_tokens": sum(slot.tokens for slot in self._slots),
            "pool_limit": self._settings.pool_tokens,
        })

    def _report(self, reason: Unhealthy | Stalled | None) -> None:
        """Logs each reason once, when it starts."""
        if reason is not None and reason != self._reported:
            self._log.write("error", "watcher.unhealthy", f"unhealthy: {reason}", {"reason": reason})
        self._reported = reason

    def _unhealthy_reason(self, now: float) -> Unhealthy | None:
        settings = self._settings
        silent_since = self._silent_since  # read once: the tick may clear it meanwhile
        match self._phase:
            case Yielding(since=since) if now - since > settings.yield_stuck_s:
                return "yield_stuck"
            case Serving() if self._reading.memory_used_mib >= settings.vram_limit_mib:
                return "vram_at_limit"
            case Yielded() if self._failures >= LOAD_ATTEMPTS:
                return "load_given_up"
        if silent_since is not None and now - silent_since > settings.server_silent_s:
            return "server_unresponsive"
        return None
