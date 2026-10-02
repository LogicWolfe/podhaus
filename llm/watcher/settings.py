from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    """Every setting is required: a missing variable raises KeyError and a
    malformed number ValueError, so a bad deploy fails at start."""

    server_url: str
    model_name: str
    model_file: Path
    pool_tokens: int
    listen_port: int
    activity_threshold_percent: float
    activity_samples: int
    activity_window_s: float
    quiet_s: float
    button_hold_s: float
    yield_stuck_s: float
    sample_stale_s: float
    vram_limit_mib: int
    load_timeout_s: float
    server_silent_s: float

    @classmethod
    def from_environ(cls, env: Mapping[str, str]) -> Settings:
        return cls(
            server_url=env["LLM_SERVER_URL"],
            model_name=env["LLM_MODEL_NAME"],
            model_file=Path(env["LLM_MODEL_FILE"]),
            pool_tokens=int(env["LLM_POOL_TOKENS"]),
            listen_port=int(env["WATCHER_LISTEN_PORT"]),
            activity_threshold_percent=float(env["WATCHER_ACTIVITY_THRESHOLD_PERCENT"]),
            activity_samples=int(env["WATCHER_ACTIVITY_SAMPLES"]),
            activity_window_s=float(env["WATCHER_ACTIVITY_WINDOW_SECONDS"]),
            quiet_s=float(env["WATCHER_QUIET_SECONDS"]),
            button_hold_s=float(env["WATCHER_BUTTON_HOLD_SECONDS"]),
            yield_stuck_s=float(env["WATCHER_YIELD_STUCK_SECONDS"]),
            sample_stale_s=float(env["WATCHER_SAMPLE_STALE_SECONDS"]),
            vram_limit_mib=int(env["WATCHER_VRAM_LIMIT_MIB"]),
            load_timeout_s=float(env["WATCHER_LOAD_TIMEOUT_SECONDS"]),
            server_silent_s=float(env["WATCHER_SERVER_SILENT_SECONDS"]),
        )
