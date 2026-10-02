from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Clock:
    """Every duration and deadline is measured on `monotonic`; `wall` only dates
    log lines. WSL2 moves the guest's wall clock when Windows sleeps or resumes,
    which on the wall clock would trip the stall watchdog or stretch a hold."""

    monotonic: Callable[[], float]
    wall: Callable[[], float]

    def wall_at(self, t: float) -> float:
        """The wall time of monotonic instant `t`, on the wall clock as it reads now."""
        return self.wall() - (self.monotonic() - t)
