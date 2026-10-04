"""What the watcher's tests drive it with: a clock the test sets, a GPU whose
readings the test scripts, and a stand-in for llama.cpp's router that answers
the management API over real HTTP, so the watcher's own client is exercised.

The stand-in follows the router as measured live on fractal (GET /models,
POST /models/load, POST /models/unload, GET /slots?model=...). Loads and
unloads take time on the test's clock, so no test sleeps for real seconds. A
load lasts as long as the measured one in fixtures/watcher_live_load.csv and
puts that load's GPU activity on the scripted GPU.

The watcher's settings are the llm-watcher service's environment in
llm/compose.yaml, so the two cannot drift; a test overrides only what it needs.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.parse import parse_qs, urlsplit

import yaml

from llm.watcher.clock import Clock
from llm.watcher.gpu import GpuReading
from llm.watcher.guest import Guest
from llm.watcher.model_server import ModelServer
from llm.watcher.settings import Settings
from llm.watcher.state import EventLog, Watcher

# The watcher drops the model file's page cache with os.posix_fadvise, which
# Python provides only on Linux, where the watcher runs. Tests that take it
# through a load or unload cannot run on a Mac.
LINUX_ONLY = unittest.skipUnless(
    sys.platform == "linux", "the watcher drops page cache with os.posix_fadvise, Linux only"
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
COMPOSE = Path(__file__).resolve().parents[1] / "compose.yaml"
# The recording carries times of day only; any fixed day serves.
DAY = datetime(2026, 9, 20, tzinfo=timezone.utc).timestamp()
MEMINFO = """MemTotal:       26214400 kB
MemFree:         4194304 kB
MemAvailable:   12582912 kB
Buffers:          102400 kB
Cached:          8388608 kB
"""
# Long enough for the stand-in's HTTP round trip, short enough that a test
# with unanswered slot reads takes well under a second.
SLOT_READ_TIMEOUT_S = 0.05


def environment(**overrides: str) -> dict[str, str]:
    """The llm-watcher service's environment from llm/compose.yaml, without TZ."""
    service = yaml.safe_load(COMPOSE.read_text())["services"]["llm-watcher"]
    env = {name: str(value) for name, value in service["environment"].items() if name != "TZ"}
    # An override of a name compose does not set would hide a missing setting.
    unknown = overrides.keys() - env.keys()
    if unknown:
        raise KeyError(f"not in llm/compose.yaml: {sorted(unknown)}")
    return {**env, **overrides}


MODEL = environment()["LLM_MODEL_NAME"]


def at(time_of_day: str) -> float:
    hours, minutes, seconds = (int(part) for part in time_of_day.split(":"))
    return DAY + hours * 3600 + minutes * 60 + seconds


def parse_ts(text: str) -> float:
    return datetime.fromisoformat(text).timestamp()


@dataclass(frozen=True)
class RecordedSample:
    t: float
    util: int


def game_session() -> list[RecordedSample]:
    with (FIXTURES / "watcher_game_session.csv").open() as recording:
        return [
            RecordedSample(at(row["time"]), int(row["gpu_util_pct"]))
            for row in csv.DictReader(recording)
        ]


def live_load() -> list[RecordedSample]:
    """A real router-mode load on fractal (mon-b.csv, 23:04:52): GPU
    utilisation from the load request, at second 0, to the model ready."""
    with (FIXTURES / "watcher_live_load.csv").open() as recording:
        return [RecordedSample(float(row["seconds"]), int(row["util"])) for row in csv.DictReader(recording)]


LIVE_LOAD = live_load()
# For tests about timing, where the load's own GPU activity is beside the point.
QUIET_LOAD = [RecordedSample(0.0, 0)]


class ScriptedClock:
    """The test's time. `now` moves both of the watcher's clocks together. The
    monotonic one counts from an origin of its own, as the real one does, so a
    duration taken across the two clocks shows; `wall_correction` moves the
    wall clock alone, as WSL2 does when Windows resumes from sleep."""

    def __init__(self, now: float) -> None:
        self.now = now
        self.wall_correction = 0.0

    def __call__(self) -> float:
        return self.now

    def for_watcher(self) -> Clock:
        return Clock(monotonic=lambda: self.now - DAY, wall=lambda: self.now + self.wall_correction)


class ScriptedGpu:
    """Utilisation is the test's own figure or the load's, whichever is higher.
    Clearing `release` holds the next read, and with it the tick, which is how
    a test makes the sampling loop stick; `reading` is set once a read starts."""

    def __init__(self, load_activity: Callable[[], int]) -> None:
        self.util = 0
        self.memory_used_mib = 4000
        self.load_activity = load_activity
        self.reading = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def read(self) -> GpuReading:
        self.reading.set()
        self.release.wait()
        return GpuReading(max(self.util, self.load_activity()), self.memory_used_mib, 32607, 80.0, 52)


class RecordingGuest(Guest):
    """The real guest reader, recording when it drops the model file's cache."""

    def __init__(self, meminfo: Path, model_file: Path, clock: ScriptedClock) -> None:
        super().__init__(meminfo, model_file)
        self._test_clock = clock
        self.drops: list[float] = []

    def drop_model_file_cache(self) -> None:
        super().drop_model_file_cache()
        self.drops.append(self._test_clock.now)


def idle_slot(slot_id: int) -> dict:
    """A slot that has never run a task, as the router reports one."""
    return {"id": slot_id, "n_ctx": 204800, "speculative": True, "is_processing": False}


def slot(slot_id: int, tokens: int, busy: bool, prompt: str = "") -> dict:
    """A slot that has run a task. `prompt` stands for the text a server
    started with slot debugging would include; the watcher must never pass it on."""
    report = {
        "id": slot_id,
        "id_task": 100 + slot_id,
        "n_ctx": 204800,
        "speculative": True,
        "is_processing": busy,
        "n_prompt_tokens": tokens,
        "n_prompt_tokens_processed": tokens,
        "n_prompt_tokens_cache": 0,
        "params": {"n_predict": -1, "temperature": 0.6},
        "next_token": [{"has_next_token": busy, "has_new_line": False, "n_remain": -1, "n_decoded": 0}],
    }
    if prompt:
        report["prompt"] = prompt
    return report


class StandInRouter:
    """One model that loads and unloads on request in test-clock time, and a
    slot report the test sets. Records when the watcher asked for each load
    and unload. A test can also:
      - make slot reads go unanswered (`silent`), as during a long save;
      - kill the model (`kill`), or have each load's model die a set number of
        seconds after it is ready (`lifetimes`);
      - end the model process inside the next slot read (`dies_in_slot_read`):
        500 is the router's answer before it notices, 400 after, and 503 means
        it has started loading the model again;
      - end it just before the watcher's next unload request arrives
        (`dies_before_unload`), so the router answers that the model is not running;
      - have the router kill the model at the end of every unload, as its stop
        timeout does to a process slow to exit (`forced_stop`);
      - unload or load the model as some other client would (`unload_elsewhere`,
        `load_elsewhere`), or have
        that happen just before the watcher's next load request reaches it
        (`load_elsewhere_first`)."""

    def __init__(self, clock: ScriptedClock, phase: str, load_seconds: float, unload_seconds: float,
                 load_profile: Sequence[RecordedSample]) -> None:
        self.clock = clock
        self.load_seconds = load_seconds
        self.unload_seconds = unload_seconds
        self.load_profile = load_profile
        self.failing_loads = 0
        self.lifetimes: list[float] = []
        self.silent = False
        self.dies_in_slot_read: int | None = None
        self.dies_before_unload = False
        self.forced_stop = False
        self.load_elsewhere_first = False
        self.slots = [idle_slot(i) for i in range(4)]
        self.loads: list[float] = []
        self.unloads: list[float] = []
        self.slot_queries: list[dict[str, list[str]]] = []
        self._phase = phase
        self._load_started = clock()
        self._phase_ends = clock() + load_seconds if phase == "loading" else clock()
        self._dies_at = float("inf")
        self._this_load_fails = False
        self._unsilenced = threading.Event()
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(_RouterHandler, self))
        threading.Thread(target=self._httpd.serve_forever, args=(0.01,), daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._httpd.server_address[1]}"

    def close(self) -> None:
        self._unsilenced.set()
        self._httpd.shutdown()
        self._httpd.server_close()

    def kill(self) -> None:
        """The model process dies on its own."""
        self._phase = "failed"

    def unload_elsewhere(self) -> None:
        """Another client unloads the model, which then exits cleanly."""
        self._phase = "unloading"
        self._phase_ends = self.clock() + self.unload_seconds

    def load_elsewhere(self) -> None:
        """Another client loads the model, as the router's autoload parameter allows."""
        self._begin_load(lifetime=float("inf"), fails=False)

    def load_activity(self) -> int:
        """The GPU utilisation the load in progress causes by itself."""
        if self.phase() != "loading":
            return 0
        elapsed = self.clock() - self._load_started
        return [sample.util for sample in self.load_profile if sample.t <= elapsed][-1]

    def phase(self) -> str:
        now = self.clock()
        if now >= self._phase_ends:
            if self._phase == "loading":
                self._phase = "failed" if self._this_load_fails else "loaded"
            elif self._phase == "unloading":
                self._phase = "failed" if self.forced_stop else "unloaded"
        if self._phase == "loaded" and now >= self._dies_at:
            self._phase = "failed"
        return self._phase

    def status(self) -> dict:
        phase = self.phase()
        if phase == "failed":
            return {"value": "unloaded", "args": ["llama-server"], "failed": True, "exit_code": 1}
        value = {"unloaded": "unloaded", "loading": "loading", "loaded": "loaded", "unloading": "loaded"}[phase]
        return {"value": value, "args": ["llama-server"]}

    def load(self) -> tuple[int, dict]:
        if self.load_elsewhere_first:
            self.load_elsewhere_first = False
            self.load_elsewhere()
        if self.phase() in ("loading", "loaded", "unloading"):
            return 400, error_body(400, "model is already running")
        self.loads.append(self.clock())
        fails = self.failing_loads > 0
        self.failing_loads = max(0, self.failing_loads - 1)
        self._begin_load(lifetime=self.lifetimes.pop(0) if self.lifetimes else float("inf"), fails=fails)
        return 200, {"success": True}

    def _begin_load(self, lifetime: float, fails: bool) -> None:
        self._phase = "loading"
        self._this_load_fails = fails
        self._load_started = self.clock()
        self._phase_ends = self.clock() + self.load_seconds
        self._dies_at = self._phase_ends + lifetime

    def unload(self) -> tuple[int, dict]:
        if self.dies_before_unload:
            self.dies_before_unload = False
            self.kill()
        phase = self.phase()
        if phase not in ("loading", "loaded"):
            return 400, error_body(400, "model is not running")
        self.unloads.append(self.clock())
        # The router force-kills a model that is still loading.
        self._phase = "failed" if phase == "loading" else "unloading"
        self._phase_ends = self.clock() + self.unload_seconds
        return 200, {"success": True}

    def slot_report(self, query: dict[str, list[str]]) -> tuple[int, object] | None:
        """None while silent: the request is held until the test ends."""
        self.slot_queries.append(query)
        if query.get("model") != [MODEL] or self.phase() not in ("loaded", "unloading"):
            return 400, error_body(400, "model is not loaded")
        if self.silent:
            self._unsilenced.wait()
            return None
        if self.dies_in_slot_read is not None:
            status, self.dies_in_slot_read = self.dies_in_slot_read, None
            if status == 503:
                self.load_elsewhere()
            else:
                self.kill()
            return status, error_body(status, SLOT_READ_ERRORS[status])
        return 200, self.slots


SLOT_READ_ERRORS = {
    500: "proxy error: Could not establish connection",
    400: "model is not loaded",
    503: "Loading model",
}


def error_body(code: int, message: str) -> dict:
    return {"error": {"code": code, "message": message, "type": "invalid_request_error"}}


class _RouterHandler(BaseHTTPRequestHandler):
    def __init__(self, router: StandInRouter, *args) -> None:
        self.router = router
        super().__init__(*args)

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        if url.path == "/models":
            listing = {"data": [{"id": MODEL, "object": "model", "status": self.router.status()}], "object": "list"}
            self._reply(200, listing)
        elif url.path == "/slots":
            reply = self.router.slot_report(parse_qs(url.query))
            if reply is not None:
                self._reply(*reply)
        else:
            self._reply(404, error_body(404, "not found"))

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if body["model"] != MODEL:
            self._reply(404, error_body(404, "model is not found"))
        elif self.path == "/models/load":
            self._reply(*self.router.load())
        elif self.path == "/models/unload":
            self._reply(*self.router.unload())
        else:
            self._reply(404, error_body(404, "not found"))

    def _reply(self, status: int, body: object) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args) -> None:
        pass


class Harness:
    """A watcher adopted at `start` against a stand-in whose model is `model`
    ("loaded", "unloaded" or "loading"), with the watcher's log captured.
    `env` overrides settings from llm/compose.yaml."""

    def __init__(self, add_cleanup: Callable, *, model: str, start: float,
                 load_seconds: float = LIVE_LOAD[-1].t, unload_seconds: float = 2,
                 load_profile: Sequence[RecordedSample] = LIVE_LOAD, env: Mapping[str, str] | None = None) -> None:
        self.clock = ScriptedClock(start)
        self.server = StandInRouter(self.clock, model, load_seconds, unload_seconds, load_profile)
        add_cleanup(self.server.close)
        self.gpu = ScriptedGpu(self.server.load_activity)
        files = tempfile.TemporaryDirectory()
        add_cleanup(files.cleanup)
        meminfo = Path(files.name) / "meminfo"
        meminfo.write_text(MEMINFO)
        model_file = Path(files.name) / "model.gguf"
        model_file.write_bytes(bytes(4096))
        overrides = {"LLM_SERVER_URL": self.server.url, "LLM_MODEL_FILE": str(model_file), **(env or {})}
        self.settings = Settings.from_environ(environment(**overrides))
        self.log = io.StringIO()
        self.guest = RecordingGuest(meminfo, model_file, self.clock)
        clock = self.clock.for_watcher()
        server = ModelServer(self.server.url, MODEL, SLOT_READ_TIMEOUT_S)
        self.watcher = Watcher.adopt(self.settings, self.gpu, server, self.guest, EventLog(self.log, clock), clock)

    @property
    def state(self) -> str:
        return self.watcher.snapshot().state

    def tick(self, t: float, util: int = 0) -> None:
        self.clock.now = t
        self.gpu.util = util
        self.watcher.tick()

    def quiet(self, first: float, last: float) -> None:
        """One idle sample a second from `first` to `last` inclusive."""
        for second in range(int(last - first) + 1):
            self.tick(first + second)

    def lines(self) -> list[dict]:
        return [json.loads(line) for line in self.log.getvalue().splitlines()]

    def events(self, name: str) -> list[dict]:
        return [line for line in self.lines() if line["event"] == name]
