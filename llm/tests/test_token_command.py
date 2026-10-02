"""The sign-in token command (llm/client/llm_token.py), against a stand-in Pocket ID.

The stand-in serves Pocket ID's discovery, device authorization and token
endpoints over real HTTP on a loopback port, answering token requests from a
script, so the command's own HTTP, JSON and file handling all run for real.
Only the clock is replaced, so a fifteen-minute device sign-in runs in no time.

The stand-in's answers follow Pocket ID v2.9.0's own handlers: the device
authorization reply and its five-second interval, `authorization_pending` and
`slow_down` while waiting, a 400 with Pocket ID's message (first letter
capitalised, as its error handler writes it) for a spent refresh token or an
expired device code, and a new refresh token on every renewal.
"""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import urllib.error
import urllib.parse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "llm" / "client"))

import llm_token  # noqa: E402

DEVICE_PATH = "/api/oidc/device/authorize"
TOKEN_PATH = "/api/oidc/token"
USER_CODE = "ABCD1234"


@dataclass(frozen=True)
class ScriptedReply:
    status: int
    body: dict


@dataclass(frozen=True)
class RecordedRequest:
    path: str
    form: dict


def issued(access: str, refresh: str) -> ScriptedReply:
    return ScriptedReply(200, {
        "access_token": access,
        "token_type": "Bearer",
        "id_token": "id-token",
        "refresh_token": refresh,
        "expires_in": 3600,
    })


PENDING = ScriptedReply(400, {"error": "authorization_pending"})
SLOW_DOWN = ScriptedReply(400, {"error": "slow_down"})


@dataclass
class StandInPocketID:
    """Pocket ID's three endpoints, answering token requests from a script.

    A token request beyond the script gets a 500, which the command treats as
    an outage, so asking Pocket ID more than a test expects fails the test.
    """

    token_replies: list[ScriptedReply]
    device_interval: int = 5
    device_expires_in: int = 900
    token_delay: float = 0.0
    requests: list[RecordedRequest] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._lock = threading.Lock()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler_class())
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    @property
    def link(self) -> str:
        return f"{self.url}/device?code={USER_CODE}"

    def token_requests(self) -> list[RecordedRequest]:
        return [request for request in self.requests if request.path == TOKEN_PATH]

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def answer(self, path: str, form: dict) -> ScriptedReply:
        with self._lock:
            self.requests.append(RecordedRequest(path, form))
        if path == "/.well-known/openid-configuration":
            return ScriptedReply(200, {
                "issuer": self.url,
                "device_authorization_endpoint": self.url + DEVICE_PATH,
                "token_endpoint": self.url + TOKEN_PATH,
            })
        if path == DEVICE_PATH:
            return ScriptedReply(200, {
                "device_code": "device-code-1",
                "user_code": USER_CODE,
                "verification_uri": f"{self.url}/device",
                "verification_uri_complete": self.link,
                "expires_in": self.device_expires_in,
                "interval": self.device_interval,
                "requires_authorization": False,
            })
        if path == TOKEN_PATH:
            time.sleep(self.token_delay)
            with self._lock:
                if self.token_replies:
                    return self.token_replies.pop(0)
            return ScriptedReply(500, {"error": "unscripted token request"})
        return ScriptedReply(404, {"error": "unknown path"})

    def _handler_class(self) -> type[BaseHTTPRequestHandler]:
        stand_in = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: object) -> None:
                pass

            def do_GET(self) -> None:
                self._reply(stand_in.answer(self.path, {}))

            def do_POST(self) -> None:
                length = int(self.headers["Content-Length"])
                form = dict(urllib.parse.parse_qsl(self.rfile.read(length).decode()))
                self._reply(stand_in.answer(self.path, form))

            def _reply(self, reply: ScriptedReply) -> None:
                body = json.dumps(reply.body).encode()
                self.send_response(reply.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return Handler


class FakeClock:
    """Satisfies llm_token.Clock; sleeping moves time on and is recorded."""

    def __init__(self, start: float = 1_800_000_000.0) -> None:
        self.time = start
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.time

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.time += seconds


class TokenCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.state_home = Path(self._directory.name)
        self.cache = llm_token.TokenCache(self.state_home / "llm-token")
        self.clock = FakeClock()
        self.announcements = io.StringIO()

    def stand_in(self, *replies: ScriptedReply, **settings: object) -> StandInPocketID:
        stand_in = StandInPocketID(list(replies), **settings)
        self.addCleanup(stand_in.close)
        return stand_in

    def command(self, stand_in: StandInPocketID, clock: FakeClock | None = None) -> llm_token.TokenCommand:
        clock = clock or self.clock
        return llm_token.TokenCommand(
            cache=llm_token.TokenCache(self.state_home / "llm-token"),
            pocket_id=llm_token.PocketID(stand_in.url, llm_token.CLIENT_ID, clock),
            presenter=llm_token.LinkPresenter(self.announcements, opener=None),
            clock=clock,
        )

    def save_token(self, access: str, refresh: str, seconds_left: float) -> None:
        self.cache.save(llm_token.Token(access, refresh, self.clock.now() + seconds_left))

    def announced_lines(self) -> list[str]:
        return self.announcements.getvalue().splitlines()

    def test_first_run_prints_one_link_waits_for_approval_and_returns_the_token(self) -> None:
        stand_in = self.stand_in(PENDING, PENDING, issued("access-1", "refresh-1"))

        token = self.command(stand_in).token()

        self.assertEqual(token, "access-1")
        self.assertEqual(self.announced_lines(), [stand_in.link])
        device_request = next(r for r in stand_in.requests if r.path == DEVICE_PATH)
        self.assertEqual(device_request.form["client_id"], llm_token.CLIENT_ID)
        self.assertEqual(set(device_request.form["scope"].split()), {"openid", "email", "groups"})
        polls = stand_in.token_requests()
        self.assertEqual(len(polls), 3)
        for poll in polls:
            self.assertEqual(poll.form, {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": "device-code-1",
                "client_id": llm_token.CLIENT_ID,
            })
        self.assertEqual(self.clock.sleeps, [5, 5, 5])
        self.assertEqual(
            self.cache.load(),
            llm_token.Token("access-1", "refresh-1", self.clock.now() + 3600),
        )

    def test_the_token_file_is_readable_by_its_owner_only(self) -> None:
        stand_in = self.stand_in(issued("access-1", "refresh-1"))

        self.command(stand_in).token()

        self.assertEqual(stat.S_IMODE(self.cache.token_file.stat().st_mode), 0o600)

    def test_a_later_run_returns_the_cached_token_without_asking_pocket_id(self) -> None:
        self.save_token("access-1", "refresh-1", seconds_left=3000)
        stand_in = self.stand_in()

        token = self.command(stand_in).token()

        self.assertEqual(token, "access-1")
        self.assertEqual(stand_in.requests, [])
        self.assertEqual(self.announced_lines(), [])

    def test_a_token_near_expiry_is_renewed_silently_and_the_new_refresh_token_kept(self) -> None:
        self.save_token("access-1", "refresh-1", seconds_left=60)
        stand_in = self.stand_in(issued("access-2", "refresh-2"))

        token = self.command(stand_in).token()

        self.assertEqual(token, "access-2")
        self.assertEqual([r.form for r in stand_in.token_requests()], [{
            "grant_type": "refresh_token",
            "refresh_token": "refresh-1",
            "client_id": llm_token.CLIENT_ID,
        }])
        self.assertEqual(self.announced_lines(), [])
        self.assertEqual(self.cache.load().refresh_token, "refresh-2")

    def test_a_refused_renewal_prints_a_fresh_link(self) -> None:
        self.save_token("access-1", "refresh-1", seconds_left=-60)
        stand_in = self.stand_in(
            ScriptedReply(400, {"error": "Refresh token is invalid or expired"}),
            PENDING,
            issued("access-2", "refresh-2"),
        )

        token = self.command(stand_in).token()

        self.assertEqual(token, "access-2")
        self.assertEqual(self.announced_lines(), [stand_in.link])
        self.assertEqual(self.cache.load().refresh_token, "refresh-2")

    def test_pocket_id_failing_is_an_error_not_a_new_sign_in(self) -> None:
        self.save_token("access-1", "refresh-1", seconds_left=60)
        stand_in = self.stand_in(ScriptedReply(502, {"error": "bad gateway"}))

        with self.assertRaises(urllib.error.HTTPError):
            self.command(stand_in).token()

        self.assertEqual(self.announced_lines(), [])
        self.assertEqual(self.cache.load().refresh_token, "refresh-1")

    def test_slow_down_lengthens_the_wait_between_polls(self) -> None:
        stand_in = self.stand_in(SLOW_DOWN, PENDING, issued("access-1", "refresh-1"))

        self.command(stand_in).token()

        self.assertEqual(self.clock.sleeps, [5, 10, 10])

    def test_a_sign_in_not_approved_in_time_fails_and_saves_nothing(self) -> None:
        stand_in = self.stand_in(PENDING, PENDING, device_expires_in=12)

        with self.assertRaisesRegex(llm_token.TokenUnavailable, "^expired$"):
            self.command(stand_in).token()

        self.assertEqual(len(stand_in.token_requests()), 2)
        self.assertIsNone(self.cache.load())

    def test_pocket_id_refusing_the_device_code_fails_with_its_reason(self) -> None:
        stand_in = self.stand_in(ScriptedReply(400, {"error": "Device code has expired"}))

        with self.assertRaisesRegex(llm_token.TokenUnavailable, "^Device code has expired$"):
            self.command(stand_in).token()

        self.assertIsNone(self.cache.load())

    def test_a_damaged_token_file_fails_without_asking_pocket_id(self) -> None:
        self.cache.token_file.parent.mkdir(parents=True)
        self.cache.token_file.write_text("{not json")
        stand_in = self.stand_in()

        with self.assertRaisesRegex(llm_token.TokenUnavailable, "damaged"):
            self.command(stand_in).token()

        self.assertEqual(stand_in.requests, [])

    def test_runs_at_the_same_moment_renew_once(self) -> None:
        """Pocket ID spends a refresh token when it renews it, so a second run
        renewing with the same one would be refused and ask for a sign-in."""
        self.save_token("access-1", "refresh-1", seconds_left=60)
        stand_in = self.stand_in(issued("access-2", "refresh-2"), token_delay=0.3)
        results: list[str] = []
        failures: list[BaseException] = []

        def run() -> None:
            try:
                results.append(self.command(stand_in, FakeClock(self.clock.now())).token())
            except BaseException as failure:  # reported by the assertion below
                failures.append(failure)

        runs = [threading.Thread(target=run) for _ in range(2)]
        for each in runs:
            each.start()
        for each in runs:
            each.join(timeout=10)

        self.assertEqual(failures, [])
        self.assertEqual(results, ["access-2", "access-2"])
        self.assertEqual(len(stand_in.token_requests()), 1)


class CommandLineTest(unittest.TestCase):
    """main() as pi and Claude Code run it: the token alone on stdout."""

    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)

    def run_main(self, stand_in: StandInPocketID) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        environment = {"XDG_STATE_HOME": self._directory.name, "SSH_CONNECTION": "test"}
        with mock.patch.object(llm_token, "ISSUER", stand_in.url), \
                mock.patch.dict(os.environ, environment), \
                redirect_stdout(out), redirect_stderr(err):
            status = llm_token.main()
        return status, out.getvalue(), err.getvalue()

    def stand_in(self, *replies: ScriptedReply) -> StandInPocketID:
        stand_in = StandInPocketID(list(replies), device_interval=0)
        self.addCleanup(stand_in.close)
        return stand_in

    def test_the_token_is_the_only_output_on_stdout(self) -> None:
        stand_in = self.stand_in(issued("access-1", "refresh-1"))

        status, out, err = self.run_main(stand_in)

        self.assertEqual((status, out, err), (0, "access-1\n", stand_in.link + "\n"))

    def test_a_failed_sign_in_exits_non_zero_with_nothing_on_stdout(self) -> None:
        stand_in = self.stand_in(ScriptedReply(400, {"error": "Device code has expired"}))

        status, out, err = self.run_main(stand_in)

        self.assertEqual((status, out), (1, ""))
        self.assertEqual(err.splitlines(), [stand_in.link, "Device code has expired"])

    def test_the_token_is_kept_under_the_state_directory(self) -> None:
        self.assertEqual(
            llm_token.state_directory({"XDG_STATE_HOME": "/state"}),
            Path("/state/llm-token"),
        )
        self.assertEqual(
            llm_token.state_directory({"XDG_STATE_HOME": ""}),
            Path.home() / ".local" / "state" / "llm-token",
        )


class BrowserTest(unittest.TestCase):
    def opener(self, platform: str, environ: dict, xdg_open: str | None = "/usr/bin/xdg-open") -> list[str] | None:
        return llm_token.browser_opener(platform, environ, lambda name: xdg_open if name == "xdg-open" else None)

    def test_a_mac_opens_links_itself(self) -> None:
        self.assertEqual(self.opener("darwin", {}), ["open"])

    def test_a_linux_desktop_opens_links_with_xdg_open(self) -> None:
        self.assertEqual(self.opener("linux", {"DISPLAY": ":0"}), ["/usr/bin/xdg-open"])
        self.assertEqual(self.opener("linux", {"WAYLAND_DISPLAY": "wayland-0"}), ["/usr/bin/xdg-open"])

    def test_no_browser_without_a_screen_or_an_opener(self) -> None:
        self.assertIsNone(self.opener("linux", {}))
        self.assertIsNone(self.opener("linux", {"DISPLAY": ":0"}, xdg_open=None))

    def test_no_browser_over_ssh(self) -> None:
        self.assertIsNone(self.opener("darwin", {"SSH_CONNECTION": "10.0.0.2 50000 10.0.0.3 22"}))
        self.assertIsNone(self.opener("linux", {"DISPLAY": ":0", "SSH_CONNECTION": "x"}))

    def test_the_link_is_printed_and_handed_to_the_opener(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            received = Path(directory) / "opened"
            opener = [sys.executable, "-c",
                      "import pathlib, sys; pathlib.Path(sys.argv[1]).write_text(sys.argv[2])",
                      str(received)]
            stream = io.StringIO()
            presenter = llm_token.LinkPresenter(stream, opener)

            presenter.show("https://id.example/device?code=X")

            self.assertEqual(presenter.opened.wait(timeout=10), 0)
            self.assertEqual(received.read_text(), "https://id.example/device?code=X")
            self.assertEqual(stream.getvalue(), "https://id.example/device?code=X\n")

    def test_without_an_opener_nothing_is_started(self) -> None:
        presenter = llm_token.LinkPresenter(io.StringIO(), opener=None)

        presenter.show("https://id.example/device?code=X")

        self.assertIsNone(presenter.opened)


if __name__ == "__main__":
    unittest.main()
