"""fractal's plain-HTTP Caddy listeners, run from the real Caddyfile.

Caddy compiles caddy/fractal/Caddyfile and runs the result with only its
addresses changed: each listener on a free loopback port, each upstream on a
stand-in that records what reached it, and the setup page's files read from
this repository. Requests come from the loopback address, so a test admits
that address as bandicoot's to be let in, or another one to be refused. The
signed-in :4443 listener needs Pomerium's certificates and is left out; it
imports the same routes as the loopback listener.
"""

from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[3]
CADDYFILE = ROOT / "caddy" / "fractal" / "Caddyfile"
SETUP = ROOT / "caddy" / "fractal" / "llm-setup"
LOOPBACK = "127.0.0.1"
# bandicoot's real address, which these requests never come from.
ELSEWHERE = "10.0.0.90"
LAN = ":8086"
LOCAL = ":8085"
MANAGEMENT_PATHS = ("/health", "/slots", "/metrics", "/healthz", "/props")


@dataclass(frozen=True)
class Received:
    path: str
    headers: dict[str, str]


class StandIn:
    """An upstream that answers 200 and records each request it gets."""

    def __init__(self) -> None:
        self.received: list[Received] = []
        received = self.received

        class Handler(BaseHTTPRequestHandler):
            def answer(self) -> None:
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                headers = {k.lower(): v for k, v in self.headers.items()}
                received.append(Received(self.path, headers))
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()

            do_GET = do_POST = answer

            def log_message(self, format: str, *args: object) -> None:
                pass

        self._server = ThreadingHTTPServer((LOOPBACK, 0), Handler)
        self.address = f"{LOOPBACK}:{self._server.server_address[1]}"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def paths(self) -> list[str]:
        return [r.path for r in self.received]

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


def free_port() -> int:
    with socket.socket() as s:
        s.bind((LOOPBACK, 0))
        return s.getsockname()[1]


def matchers(node: object) -> list[dict]:
    """Every request matcher set anywhere in a compiled config."""
    if isinstance(node, list):
        return [m for item in node for m in matchers(item)]
    if not isinstance(node, dict):
        return []
    found: list[dict] = []
    for key, value in node.items():
        if key in ("match", "not"):
            found.extend(value)
        found.extend(matchers(value))
    return found


def relocated(node: object, moves: dict[str, str]) -> object:
    """The config with every string equal to a key replaced by its value."""
    if isinstance(node, dict):
        return {k: relocated(v, moves) for k, v in node.items()}
    if isinstance(node, list):
        return [relocated(v, moves) for v in node]
    if isinstance(node, str):
        return moves.get(node, node)
    return node


class FractalCaddy:
    """fractal-caddy's plain-HTTP listeners, with `admitted` as bandicoot's
    address and `model` and `watcher` in place of the two containers."""

    def __init__(self, admitted: str, model: StandIn, watcher: StandIn) -> None:
        caddy = shutil.which("caddy")
        if caddy is None:
            raise RuntimeError("caddy is not on PATH; run mise install")
        self.ports = {LOCAL: free_port(), LAN: free_port()}
        self.compiled = self._compile(caddy, admitted)
        self._dir = tempfile.TemporaryDirectory()
        path = Path(self._dir.name) / "caddy.json"
        path.write_text(json.dumps(self._relocate(self.compiled, model, watcher)))
        self._log = Path(self._dir.name) / "caddy.log"
        # Caddy's own state goes in the test's directory, not the home.
        state = {"XDG_CONFIG_HOME": self._dir.name, "XDG_DATA_HOME": self._dir.name}
        with self._log.open("w") as log:
            self._process = subprocess.Popen(
                [caddy, "run", "--config", str(path)],
                env={**os.environ, **state},
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        self._await_listeners()
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @staticmethod
    def _compile(caddy: str, admitted: str) -> dict:
        adapted = subprocess.run(
            [caddy, "adapt", "--config", str(CADDYFILE), "--adapter", "caddyfile"],
            env={**os.environ, "BANDICOOT_LAN_IPV4": admitted},
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(adapted.stdout)

    def server(self, listener: str) -> dict:
        """The compiled config of one listener, before it was relocated."""
        servers = self.compiled["apps"]["http"]["servers"].values()
        return next(s for s in servers if s["listen"] == [listener])

    def _relocate(self, compiled: dict, model: StandIn, watcher: StandIn) -> dict:
        config = json.loads(json.dumps(compiled))
        servers = config["apps"]["http"]["servers"]
        names = {tuple(server["listen"]): name for name, server in servers.items()}
        del servers[names[(":4443",)]]
        del config["apps"]["tls"]
        for listen, port in self.ports.items():
            servers[names[(listen,)]]["listen"] = [f"{LOOPBACK}:{port}"]
        config["admin"] = {"disabled": True, "config": {"persist": False}}
        return relocated(config, {
            "llm-server:8080": model.address,
            "llm-watcher:8081": watcher.address,
            "/etc/caddy/llm-setup": str(SETUP),
        })

    def _await_listeners(self) -> None:
        deadline = time.monotonic() + 10
        for port in self.ports.values():
            while True:
                if self._process.poll() is not None:
                    raise RuntimeError(f"caddy exited:\n{self._log.read_text()}")
                try:
                    socket.create_connection((LOOPBACK, port), timeout=1).close()
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise
                    time.sleep(0.05)

    def status(self, listener: str, path: str, *, method: str = "GET",
               headers: dict[str, str] | None = None, body: bytes | None = None) -> int:
        url = f"http://{LOOPBACK}:{self.ports[listener]}{path}"
        request = urllib.request.Request(url, data=body, method=method, headers=headers or {})
        try:
            with self._opener.open(request, timeout=10) as response:
                return response.status
        except urllib.error.HTTPError as error:
            with error:
                return error.code

    def close(self) -> None:
        self._process.terminate()
        self._process.wait(timeout=10)
        self._dir.cleanup()


class RunningCaddy(unittest.TestCase):
    """One Caddy per test class, admitting `admitted` as bandicoot."""

    admitted = LOOPBACK

    @classmethod
    def setUpClass(cls) -> None:
        cls.model, cls.watcher = StandIn(), StandIn()
        cls.caddy = FractalCaddy(cls.admitted, cls.model, cls.watcher)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.caddy.close()
        cls.model.close()
        cls.watcher.close()

    def setUp(self) -> None:
        self.model.received.clear()
        self.watcher.received.clear()


class LanListenerAdmitsBandicoot(RunningCaddy):
    def test_bandicoot_reaches_the_model_with_no_sign_in(self) -> None:
        self.assertEqual(self.caddy.status(LAN, "/v1/models"), 200)
        self.assertEqual(self.model.paths(), ["/v1/models"])

    def test_the_model_route_keeps_its_protections(self) -> None:
        status = self.caddy.status(
            LAN, "/v1/messages?autoload=true", method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Conversation-Id": "c1",
            },
            body=b"autoload=true",
        )
        self.assertEqual(status, 200)
        [received] = self.model.received
        self.assertEqual(received.path, "/v1/messages")
        self.assertEqual(received.headers["content-type"], "application/json")
        self.assertNotIn("x-conversation-id", received.headers)

    def test_only_the_model_paths_are_served(self) -> None:
        for path in ("/control", "/control/resume", "/setup/", "/setup/index.html", *MANAGEMENT_PATHS):
            with self.subTest(path=path):
                self.assertEqual(self.caddy.status(LAN, path), 404)
        self.assertEqual(self.model.received, [])
        self.assertEqual(self.watcher.received, [])


class LanListenerRefusesOthers(RunningCaddy):
    admitted = ELSEWHERE

    def test_any_other_address_is_refused_on_every_path(self) -> None:
        for path in ("/v1/models", "/v1/messages", "/control", "/setup/"):
            with self.subTest(path=path):
                self.assertEqual(self.caddy.status(LAN, path), 403)
        self.assertEqual(self.model.received, [])

    def test_the_address_check_names_bandicoot_alone(self) -> None:
        # Requests can only come from loopback, so a check widened to admit
        # more of the LAN would pass every request above.
        checks = [m for m in matchers(self.caddy.server(LAN)) if "remote_ip" in m]
        self.assertEqual(checks, [{"remote_ip": {"ranges": [ELSEWHERE]}}])

    def test_a_forwarded_for_header_does_not_change_the_caller(self) -> None:
        status = self.caddy.status(LAN, "/v1/models", headers={"X-Forwarded-For": ELSEWHERE})
        self.assertEqual(status, 403)
        self.assertEqual(self.model.received, [])


class LanListenerWithNoAddress(RunningCaddy):
    admitted = ""

    def test_an_empty_bandicoot_address_refuses_everyone(self) -> None:
        self.assertEqual(self.caddy.status(LAN, "/v1/models"), 403)
        self.assertEqual(self.model.received, [])


class LoopbackListener(RunningCaddy):
    def test_the_model_control_page_and_setup_page_are_served(self) -> None:
        self.assertEqual(self.caddy.status(LOCAL, "/v1/models"), 200)
        self.assertEqual(self.caddy.status(LOCAL, "/control"), 200)
        self.assertEqual(self.caddy.status(LOCAL, "/setup/"), 200)
        self.assertEqual(self.model.paths(), ["/v1/models"])
        self.assertEqual(self.watcher.paths(), ["/control"])

    def test_management_paths_are_refused(self) -> None:
        for path in MANAGEMENT_PATHS:
            with self.subTest(path=path):
                self.assertEqual(self.caddy.status(LOCAL, path), 404)
        self.assertEqual(self.model.received, [])
        self.assertEqual(self.watcher.received, [])


if __name__ == "__main__":
    unittest.main()
