"""The watcher's HTTP surface: the control page and its two buttons, reached by
Nathan through Caddy; Prometheus metrics; and the health check."""

from __future__ import annotations

from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from urllib.parse import urlsplit

from .state import STATE_NAMES, Snapshot, Watcher

# Self-contained, icon included: the ingress forwards only /control and below.
PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Model</title>
<link rel="icon" href="data:,">
<style>
body {{ font-family: system-ui, sans-serif; max-width: 24rem; margin: 3rem auto; padding: 0 1rem; }}
button {{ display: block; width: 100%; margin: .75rem 0; padding: 1rem; font-size: 1.25rem; }}
</style>
</head>
<body>
<h1>{state}</h1>
{held}
<form method="post" action="/control/yield"><button>Yield</button></form>
<form method="post" action="/control/resume"><button>Resume</button></form>
</body>
</html>
"""


def control_page(snapshot: Snapshot) -> str:
    return PAGE.format(state=snapshot.state.capitalize(), held="<p>Held</p>" if snapshot.held else "")


def metrics_text(snapshot: Snapshot) -> str:
    gauges = {
        "llm_watcher_last_sample_age_seconds": snapshot.sample_age_s,
        "llm_gpu_utilization_percent": snapshot.gpu.util_percent,
        "llm_gpu_memory_used_mib": snapshot.gpu.memory_used_mib,
        "llm_gpu_memory_total_mib": snapshot.gpu.memory_total_mib,
        "llm_gpu_power_watts": snapshot.gpu.power_watts,
        "llm_gpu_temperature_celsius": snapshot.gpu.temperature_celsius,
        "llm_guest_memory_available_mib": snapshot.guest.available_mib,
        "llm_guest_memory_total_mib": snapshot.guest.total_mib,
        "llm_pool_tokens": snapshot.pool_tokens,
        "llm_pool_limit_tokens": snapshot.pool_limit,
    }
    lines = ["# TYPE llm_watcher_state gauge"]
    lines += [f'llm_watcher_state{{state="{name}"}} {int(name == snapshot.state)}' for name in STATE_NAMES]
    for name, value in gauges.items():
        lines += [f"# TYPE {name} gauge", f"{name} {value}"]
    return "\n".join(lines) + "\n"


class _Handler(BaseHTTPRequestHandler):
    def __init__(self, watcher: Watcher, *args) -> None:
        self._watcher = watcher
        super().__init__(*args)

    def do_GET(self) -> None:
        match self.path:
            case "/control":
                self._send(200, "text/html; charset=utf-8", control_page(self._watcher.snapshot()))
            case "/metrics":
                self._send(200, "text/plain; version=0.0.4", metrics_text(self._watcher.snapshot()))
            case "/healthz":
                reason = self._watcher.health()
                self._send(200 if reason is None else 503, "text/plain", reason or "ok")
            case _:
                self.send_error(404)

    def do_POST(self) -> None:
        match self.path:
            case "/control/yield":
                press = self._watcher.yield_now
            case "/control/resume":
                press = self._watcher.resume_now
            case _:
                self.send_error(404)
                return
        if self._cross_site():
            self.send_error(403)
            return
        press()
        self.send_response(303)
        self.send_header("Location", "/control")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _cross_site(self) -> bool:
        """A post that another site's page had the browser send. Pomerium would
        let it through on the session cookie, and the buttons move the GPU."""
        origin = self.headers["Origin"]
        return self.headers["Sec-Fetch-Site"] == "cross-site" or (
            origin is not None and urlsplit(origin).netloc != self.headers["Host"])

    def _send(self, status: int, content_type: str, body: str) -> None:
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args) -> None:
        # Request lines would break the one-JSON-object-per-line log; Caddy
        # already records every request that reaches the control page.
        pass


class ControlServer:
    def __init__(self, watcher: Watcher, port: int) -> None:
        self._httpd = ThreadingHTTPServer(("", port), partial(_Handler, watcher))

    @property
    def port(self) -> int:
        return self._httpd.server_address[1]

    def start(self) -> None:
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
