"""Runs the watcher: adopts the model server's state, serves the control page,
and ticks once a second. Any unexpected answer from the GPU or the model server
ends the process, and so does a sampling loop that stops ticking; Docker
restarts it and it adopts whatever state it finds."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import threading
import time

from .clock import Clock
from .gpu import NvidiaSmi
from .guest import Guest
from .model_server import SLOT_READ_TIMEOUT_S, ModelServer
from .settings import Settings
from .state import EventLog, Watcher
from .web import ControlServer

TICK_SECONDS = 1.0


def watch_for_stalls(watcher: Watcher) -> None:
    # os._exit, not sys.exit: on this thread sys.exit would end only the
    # watchdog, and the stuck main thread would carry on holding the GPU.
    while True:
        watcher.end_if_stalled(os._exit)
        time.sleep(TICK_SECONDS)


def main() -> None:
    settings = Settings.from_environ(os.environ)
    clock = Clock(monotonic=time.monotonic, wall=time.time)
    watcher = Watcher.adopt(
        settings,
        NvidiaSmi(),
        ModelServer(settings.server_url, settings.model_name, SLOT_READ_TIMEOUT_S),
        Guest(Path("/proc/meminfo"), settings.model_file),
        EventLog(sys.stdout, clock),
        clock,
    )
    ControlServer(watcher, settings.listen_port).start()
    threading.Thread(target=watch_for_stalls, args=(watcher,), daemon=True).start()
    next_tick = time.monotonic()
    while True:
        # A late tick is not made up: a burst of samples would crowd the
        # activity window and look like a game.
        next_tick = max(next_tick + TICK_SECONDS, time.monotonic())
        time.sleep(max(0.0, next_tick - time.monotonic()))
        watcher.tick()


if __name__ == "__main__":
    main()
