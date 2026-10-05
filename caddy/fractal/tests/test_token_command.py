"""The sign-in token command (caddy/fractal/llm-setup/llm-token), run as a
whole against a stand-in curl.

The stand-in curl records every call and answers each from a prepared reply,
so the tests see the exact requests the command sends Pocket ID and drive it
through every answer Pocket ID gives. sleep is a stand-in too, so polling
takes no time; it records the intervals asked for. So are open and xdg-open:
the command opens its sign-in link in a browser, and a test run must never
reach the real one. Everything else on PATH is real.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[3]
SETUP = ROOT / "caddy" / "fractal" / "llm-setup"
COMMAND = SETUP / "llm-token"
SH = "/bin/sh"

ISSUER = "https://id.pod.haus"
DEVICE_URL = f"{ISSUER}/api/oidc/device/authorize"
TOKEN_URL = f"{ISSUER}/api/oidc/token"
LINK = "https://id.pod.haus/device?code=ABCD-1234"

# Records its arguments, then answers from the next numbered reply file: the
# body, then the -w text with the status filled in, as curl writes them. With
# no reply prepared it fails the way curl does when it cannot connect.
STAND_IN_CURL = f"""#!{sys.executable}
import json, os, sys
args = sys.argv[1:]
with open(os.environ["CURL_CALLS"], "a") as calls:
    calls.write(json.dumps(args) + "\\n")
with open(os.environ["CURL_CALLS"]) as calls:
    number = sum(1 for _ in calls)
reply = os.path.join(os.environ["CURL_REPLIES"], str(number))
if not os.path.exists(reply):
    sys.stderr.write("curl: (7) Failed to connect\\n")
    sys.exit(7)
with open(reply) as prepared:
    status, body = prepared.read().split("\\n", 1)
sys.stdout.write(body + args[args.index("-w") + 1].replace("%{{http_code}}", status))
"""
# Records the seconds asked for and returns at once. SLEEP_HOOK, when set, is
# a shell command run in place of the wait: what another process does meanwhile.
STAND_IN_SLEEP = f"""#!{sys.executable}
import os, subprocess, sys
with open(os.environ["SLEEPS"], "a") as sleeps:
    sleeps.write(sys.argv[1] + "\\n")
if os.environ.get("SLEEP_HOOK"):
    subprocess.run(os.environ["SLEEP_HOOK"], shell=True, check=True)
"""
# Records the link it is given, then stays open as a browser does.
STAND_IN_OPENER = '#!/bin/sh\nprintf \'%s\\n\' "$1" >> "$OPENED"\nexec /bin/sleep 30\n'


@dataclass(frozen=True)
class Reply:
    status: int
    body: dict

    def text(self) -> str:
        # Pocket ID's objects come on one line; the newline after is what Go's
        # JSON encoder adds, the harder case for a shell to split.
        return f"{self.status}\n{json.dumps(self.body, separators=(',', ':'))}\n"


def token_reply(access: str, refresh: str, expires_in: int = 3600) -> Reply:
    return Reply(200, {
        "access_token": access, "token_type": "Bearer", "expires_in": expires_in,
        "refresh_token": refresh, "id_token": "id." + access, "scope": "openid email groups",
    })


def device_reply(interval: int = 5, expires_in: int = 600) -> Reply:
    return Reply(200, {
        "device_code": "device-code-1", "user_code": "ABCD-1234", "verification_uri": f"{ISSUER}/device",
        "verification_uri_complete": LINK, "expires_in": expires_in, "interval": interval,
    })


def refusal(error: str, status: int = 400) -> Reply:
    return Reply(status, {"error": error, "error_description": f"The {error} description."})


class TokenCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.stubs = self.root / "stubs"
        self.replies = self.root / "replies"
        self.replies.mkdir()
        self.calls_file = self.root / "calls"
        self.sleeps_file = self.root / "sleeps"
        self.opened_file = self.root / "opened"
        self.stub("curl", STAND_IN_CURL)
        self.stub("sleep", STAND_IN_SLEEP)
        self.stub("open", STAND_IN_OPENER)
        self.stub("xdg-open", STAND_IN_OPENER)
        self.cache_file = self.home / ".local" / "state" / "llm-token" / "token.json"

    def stub(self, name: str, script: str) -> None:
        self.stubs.mkdir(exist_ok=True)
        path = self.stubs / name
        path.write_text(script)
        path.chmod(0o755)

    def run_command(self, *replies: Reply, **environment: str) -> subprocess.CompletedProcess[str]:
        """One run; what earlier runs recorded is cleared first."""
        for stale in (self.calls_file, self.sleeps_file, self.opened_file, *self.replies.iterdir()):
            stale.unlink(missing_ok=True)
        for number, reply in enumerate(replies, start=1):
            (self.replies / str(number)).write_text(reply.text())
        env = {
            "HOME": str(self.home),
            "PATH": os.pathsep.join([str(self.stubs), os.environ["PATH"]]),
            "CURL_CALLS": str(self.calls_file),
            "CURL_REPLIES": str(self.replies),
            "SLEEPS": str(self.sleeps_file),
            "OPENED": str(self.opened_file),
            **environment,
        }
        return subprocess.run(
            [SH, str(COMMAND)], env=env, capture_output=True, text=True, timeout=20,
        )

    def calls(self) -> list[list[str]]:
        if not self.calls_file.exists():
            return []
        return [json.loads(line) for line in self.calls_file.read_text().splitlines()]

    def sleeps(self) -> list[int]:
        if not self.sleeps_file.exists():
            return []
        return [int(line) for line in self.sleeps_file.read_text().splitlines()]

    def form(self, call: list[str]) -> dict[str, str]:
        fields = [call[i + 1] for i, arg in enumerate(call) if arg == "--data-urlencode"]
        return dict(field.split("=", 1) for field in fields)

    def write_cache(self, access: str, refresh: str, seconds_left: int) -> None:
        self.cache_file.parent.mkdir(parents=True)
        self.cache_file.write_text(json.dumps({
            "access_token": access, "refresh_token": refresh,
            "expires_at": int(time.time()) + seconds_left,
        }))

    def cache(self) -> dict:
        return json.loads(self.cache_file.read_text())

    def mode(self, path: Path) -> int:
        return stat.S_IMODE(path.stat().st_mode)


class FirstRunTest(TokenCommandTest):
    def test_signs_in_through_the_device_grant(self) -> None:
        result = self.run_command(
            device_reply(), refusal("authorization_pending"), refusal("slow_down"),
            token_reply("access-1", "refresh-1"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "access-1\n")
        self.assertEqual(result.stderr, f"{LINK}\n")
        start, *polls = self.calls()
        self.assertEqual(start[-1], DEVICE_URL)
        self.assertEqual(self.form(start), {"client_id": "llm-token", "scope": "openid email groups"})
        self.assertEqual(len(polls), 3)
        for poll in polls:
            self.assertEqual(poll[-1], TOKEN_URL)
            self.assertEqual(self.form(poll), {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": "device-code-1",
                "client_id": "llm-token",
            })
        # Pocket ID's interval, then five seconds more after each slow_down.
        self.assertEqual(self.sleeps(), [5, 5, 10])

    def test_every_request_is_a_json_form_post_with_a_time_limit(self) -> None:
        self.run_command(device_reply(), token_reply("access-1", "refresh-1"))
        for call in self.calls():
            self.assertEqual(call[:2], ["-sS", "--max-time"])
            self.assertTrue(call[2].isdigit())
            self.assertIn("Accept: application/json", call)
            self.assertIn("-w", call)

    def test_keeps_the_token_in_a_private_file(self) -> None:
        before = int(time.time())
        self.run_command(device_reply(), token_reply("access-1", "refresh-1", expires_in=3600))
        self.assertEqual(self.mode(self.cache_file), 0o600)
        self.assertEqual(self.mode(self.cache_file.parent), 0o700)
        cached = self.cache()
        self.assertEqual(cached["access_token"], "access-1")
        self.assertEqual(cached["refresh_token"], "refresh-1")
        self.assertGreaterEqual(cached["expires_at"], before + 3600)
        self.assertLessEqual(cached["expires_at"], int(time.time()) + 3600)
        self.assertEqual(sorted(self.cache_file.parent.iterdir()), [self.cache_file])

    def test_follows_xdg_state_home_unless_empty(self) -> None:
        state = self.root / "state"
        self.run_command(device_reply(), token_reply("a", "r"), XDG_STATE_HOME=str(state))
        self.assertTrue((state / "llm-token" / "token.json").is_file())
        self.assertFalse(self.cache_file.exists())
        self.run_command(device_reply(), token_reply("a", "r"), XDG_STATE_HOME="")
        self.assertTrue(self.cache_file.is_file())

    def test_a_refused_sign_in_fails_with_pocket_ids_reason(self) -> None:
        result = self.run_command(device_reply(), refusal("access_denied"))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, f"{LINK}\naccess_denied\n")
        self.assertFalse(self.cache_file.exists())

    def test_a_link_that_ran_out_fails_as_expired(self) -> None:
        result = self.run_command(device_reply(expires_in=0), refusal("expired_token"))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, f"{LINK}\nexpired\n")
        # The command gives up by the clock, before asking again.
        self.assertEqual(len(self.calls()), 1)

    def test_a_refused_start_fails_with_the_reason(self) -> None:
        result = self.run_command(refusal("invalid_client", status=401))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "invalid_client\n")

    def test_an_unreachable_pocket_id_fails_without_a_link(self) -> None:
        result = self.run_command()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("Failed to connect", result.stderr)
        self.assertNotIn(LINK, result.stderr)


class CachedTokenTest(TokenCommandTest):
    def test_a_fresh_token_is_printed_without_a_request(self) -> None:
        # Well clear of the 600 s renewal margin: the command reads the clock
        # after this test does, and a second can tick over in between.
        self.write_cache("access-1", "refresh-1", seconds_left=660)
        result = self.run_command()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "access-1\n")
        self.assertEqual(result.stderr, "")
        self.assertEqual(self.calls(), [])

    def test_a_token_near_its_end_is_renewed_silently(self) -> None:
        self.write_cache("access-1", "refresh-1", seconds_left=600)
        result = self.run_command(token_reply("access-2", "refresh-2"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "access-2\n")
        self.assertEqual(result.stderr, "")
        (call,) = self.calls()
        self.assertEqual(call[-1], TOKEN_URL)
        self.assertEqual(self.form(call), {
            "grant_type": "refresh_token", "refresh_token": "refresh-1", "client_id": "llm-token",
        })
        self.assertEqual(self.cache()["refresh_token"], "refresh-2")

    def test_a_refused_renewal_starts_a_new_sign_in(self) -> None:
        self.write_cache("access-1", "refresh-1", seconds_left=0)
        result = self.run_command(
            refusal("invalid_grant"), device_reply(), token_reply("access-2", "refresh-2"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "access-2\n")
        self.assertEqual(result.stderr, f"{LINK}\n")
        self.assertEqual([call[-1] for call in self.calls()], [TOKEN_URL, DEVICE_URL, TOKEN_URL])

    def test_a_renewal_another_run_won_is_used_instead_of_a_sign_in(self) -> None:
        self.write_cache("access-1", "refresh-1", seconds_left=0)
        other_run = json.dumps({
            "access_token": "access-2", "refresh_token": "refresh-2",
            "expires_at": int(time.time()) + 3600,
        })
        result = self.run_command(
            refusal("invalid_grant"),
            SLEEP_HOOK=f"printf '%s' '{other_run}' > '{self.cache_file}'",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "access-2\n")
        self.assertEqual(result.stderr, "")
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual(self.sleeps(), [1])

    def test_a_pocket_id_failure_is_not_a_reason_to_sign_in_again(self) -> None:
        self.write_cache("access-1", "refresh-1", seconds_left=0)
        result = self.run_command(refusal("server_error", status=500))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "Pocket ID: HTTP 500\n")
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual(self.cache()["refresh_token"], "refresh-1")

    def test_a_damaged_file_fails_rather_than_signing_in(self) -> None:
        self.cache_file.parent.mkdir(parents=True)
        self.cache_file.write_text("{not json")
        result = self.run_command()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "access_token missing\n")
        self.assertEqual(self.calls(), [])


class LinkOpenerTest(TokenCommandTest):
    """The link is opened on this machine's own screen, and only there."""

    def sign_in(self, **environment: str) -> subprocess.CompletedProcess[str]:
        return self.run_command(device_reply(), token_reply("a", "r"), **environment)

    def opened(self) -> list[str]:
        return self.opened_file.read_text().splitlines() if self.opened_file.exists() else []

    def test_opens_the_link_on_a_linux_desktop_without_waiting_for_the_browser(self) -> None:
        self.stub("uname", "#!/bin/sh\necho Linux\n")
        started = time.monotonic()
        result = self.sign_in(DISPLAY=":0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual(self.opened(), [LINK])
        self.assertEqual(result.stderr, f"{LINK}\n")

    def test_opens_the_link_on_a_mac(self) -> None:
        self.stub("uname", "#!/bin/sh\necho Darwin\n")
        self.assertEqual(self.sign_in().returncode, 0)
        self.assertEqual(self.opened(), [LINK])

    def test_only_prints_the_link_over_ssh_or_without_a_screen(self) -> None:
        for environment in (
            {"DISPLAY": ":0", "SSH_CONNECTION": "10.0.0.5 1 10.0.0.9 22"},
            {},
        ):
            self.stub("uname", "#!/bin/sh\necho Linux\n")
            self.assertEqual(self.sign_in(**environment).returncode, 0)
            self.assertEqual(self.opened(), [])
        self.stub("uname", "#!/bin/sh\necho Darwin\n")
        self.assertEqual(self.sign_in(SSH_CONNECTION="10.0.0.5 1 10.0.0.9 22").returncode, 0)
        self.assertEqual(self.opened(), [])


class SharedConstantsTest(unittest.TestCase):
    """The command, the page and the installer agree on the client and addresses."""

    command = COMMAND.read_text()
    page = (SETUP / "index.html").read_text()

    def test_signs_in_with_the_pages_client_at_the_pages_token_endpoint(self) -> None:
        self.assertEqual(re.search(r"^CLIENT_ID=(\S+)$", self.command, re.M).group(1), "llm-token")
        self.assertIn('const CLIENT_ID = "llm-token";', self.page)
        self.assertIn(f'const TOKEN_URL = "{TOKEN_URL}";', self.page)
        self.assertEqual(re.search(r"^ISSUER=(\S+)$", self.command, re.M).group(1), ISSUER)
        self.assertEqual(re.search(r"^TOKEN_URL=(\S+)$", self.command, re.M).group(1), "$ISSUER/api/oidc/token")

    def test_is_installed_by_name_from_the_setup_page(self) -> None:
        self.assertIn('fetch "$setup/llm-token" "$bin/llm-token" 755', (SETUP / "claude.sh").read_text())
        self.assertTrue(COMMAND.stat().st_mode & stat.S_IXUSR)


if __name__ == "__main__":
    unittest.main()
