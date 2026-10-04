"""The setup page at llm.pod.haus/setup/ and the files it hands out
(caddy/fractal/llm-setup/).

The two install scripts run the way the page tells people to run them, piped
into sh, under a temporary home directory and a PATH holding only the commands
a test grants. A stand-in for llm.pod.haus serves their downloads over real
HTTP on a loopback port, with a stub in place of the token command, and
LLM_POD_HAUS_URL points the scripts at it. claude-podhaus runs against a stub claude
that records the environment and arguments it was started with, from an
ordinary home directory and from one whose path needs quoting. The page's own
script is tested under node, in setup-page.test.ts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[3]
SETUP = ROOT / "caddy" / "fractal" / "llm-setup"
SH = "/bin/sh"
# What the scripts use besides shell builtins.
BASE_COMMANDS = ("chmod", "mkdir", "mv", "rm")

MODEL = yaml.safe_load((ROOT / "llm" / "compose.yaml").read_text())[
    "services"]["llm-watcher"]["environment"]["LLM_MODEL_NAME"]
# Where and which model, and the measured behaviour settings, as
# docs/plans/local-llm-service.html records them.
CLAUDE_RECIPE = {
    "ANTHROPIC_BASE_URL": "https://llm.pod.haus",
    "ANTHROPIC_API_KEY": "",
    "ANTHROPIC_MODEL": MODEL,
    "ANTHROPIC_DEFAULT_OPUS_MODEL": MODEL,
    "ANTHROPIC_DEFAULT_SONNET_MODEL": MODEL,
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": MODEL,
    "ANTHROPIC_DEFAULT_FABLE_MODEL": MODEL,
    "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "150000",
    "CLAUDE_CODE_EXTRA_BODY": '{"chat_template_kwargs":{"reasoning_effort":"medium"}}',
    "CLAUDE_CODE_DISABLE_TERMINAL_TITLE": "1",
    "CLAUDE_CODE_ENABLE_PROMPT_SUGGESTION": "false",
    "CLAUDE_CODE_TOTAL_TOKENS_REMINDER": "off",
}



def pasteable(value: str) -> str:
    """The page quotes a value for the shell only when it has to."""
    return f"'{value}'" if '"' in value else value


SIGN_IN_LINK = "https://id.pod.haus/device?code=STUBCODE"
STUB_TOKEN = "stub-access-token"
# Stands in for llm-token: the link on stderr, the token on stdout.
SIGNING_IN = f"#!/bin/sh\necho {SIGN_IN_LINK} >&2\necho {STUB_TOKEN}\n".encode()
REFUSED = b"#!/bin/sh\necho expired >&2\nexit 1\n"
# Counts its runs in the home directory, so a test can tell whether it ran.
COUNTING = f'#!/bin/sh\necho run >> "$HOME/token-runs"\necho {STUB_TOKEN}\n'
RECORDING_CLAUDE = f"""#!{sys.executable}
import json, os, sys
with open(os.environ["CLAUDE_STUB_RECORD"], "w") as record:
    json.dump({{"argv": sys.argv[1:], "env": dict(os.environ)}}, record)
"""


@dataclass
class StandInSetup:
    """llm.pod.haus's /setup/ downloads, by path; anything else is a 404."""

    files: dict[str, bytes]
    requested: list[str] = field(default_factory=list)

    def __enter__(self) -> StandInSetup:
        stand_in = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                stand_in.requested.append(self.path)
                body = stand_in.files.get(self.path)
                self.send_response(404 if body is None else 200)
                self.end_headers()
                self.wfile.write(body or b"")

            def log_message(self, *args: object) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._server.shutdown()
        self._server.server_close()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}"


def served(token_command: bytes = SIGNING_IN) -> dict[str, bytes]:
    """What the real /setup/ serves, with the token command replaced."""
    files = {f"/setup/{path.name}": path.read_bytes() for path in SETUP.iterdir()}
    files["/setup/llm-token"] = token_command
    return files


class Machine:
    """A temporary home directory and a PATH of only the commands granted."""

    def __init__(self, directory: Path, home_name: str) -> None:
        self.home = directory / home_name
        self.home.mkdir()
        self.bin = directory / "bin"
        self.bin.mkdir()
        self.local_bin = self.home / ".local" / "bin"
        self.grant(*BASE_COMMANDS)

    def grant(self, *names: str) -> None:
        for name in names:
            (self.bin / name).symlink_to(shutil.which(name))

    def stub(self, directory: Path, name: str, script: str) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        path.write_text(script)
        path.chmod(0o755)
        return path

    def environment(self, local_bin_on_path: bool, **extra: str) -> dict[str, str]:
        path = [str(self.bin)] + ([str(self.local_bin)] if local_bin_on_path else [])
        return {"HOME": str(self.home), "PATH": os.pathsep.join(path), **extra}

    def pipe_into_sh(self, script: Path, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
        """Runs the script as `curl ... | sh` does, read from standard input."""
        return subprocess.run(
            [SH], input=script.read_text(), env=environment,
            capture_output=True, text=True, timeout=60,
        )

    def files_under_home(self) -> set[str]:
        return {
            str(path.relative_to(self.home))
            for path in self.home.rglob("*") if path.is_file()
        }


class MachineTest(unittest.TestCase):
    home_name = "home"

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.machine = Machine(Path(directory.name), self.home_name)

    def mode(self, path: Path) -> int:
        return stat.S_IMODE(path.stat().st_mode)


class ClaudeInstallTest(MachineTest):
    def setUp(self) -> None:
        super().setUp()
        self.machine.grant("curl")

    def install(self, files: dict[str, bytes], local_bin_on_path: bool = True) -> subprocess.CompletedProcess[str]:
        with StandInSetup(files) as stand_in:
            self.stand_in = stand_in
            environment = self.machine.environment(local_bin_on_path, LLM_POD_HAUS_URL=stand_in.base_url)
            return self.machine.pipe_into_sh(SETUP / "claude.sh", environment)

    def test_installs_both_commands_executable(self) -> None:
        files = served()
        result = self.install(files)
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ("llm-token", "claude-podhaus"):
            installed = self.machine.local_bin / name
            self.assertEqual(installed.read_bytes(), files[f"/setup/{name}"])
            self.assertEqual(self.mode(installed), 0o755)
        self.assertEqual(self.machine.files_under_home(), {".local/bin/llm-token", ".local/bin/claude-podhaus"})
        self.assertIn("claude-podhaus", result.stdout)

    def test_replaces_existing_copies(self) -> None:
        self.machine.local_bin.mkdir(parents=True)
        for name in ("llm-token", "claude-podhaus"):
            old = self.machine.local_bin / name
            old.write_text("old")
            old.chmod(0o700)
        result = self.install(served())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.machine.local_bin / "llm-token").read_bytes(), SIGNING_IN)
        self.assertEqual(self.mode(self.machine.local_bin / "claude-podhaus"), 0o755)

    def test_signs_in_once_showing_the_link_and_hiding_the_token(self) -> None:
        result = self.install(served())
        self.assertIn(SIGN_IN_LINK, result.stderr)
        self.assertNotIn(STUB_TOKEN, result.stdout + result.stderr)

    def test_a_refused_sign_in_fails_the_install(self) -> None:
        result = self.install(served(token_command=REFUSED))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("expired", result.stderr)
        self.assertNotIn("claude-podhaus", result.stdout)

    def test_warns_when_local_bin_is_not_on_path(self) -> None:
        warning = f"{self.machine.local_bin} not on PATH"
        self.assertIn(warning, self.install(served(), local_bin_on_path=False).stderr)
        self.assertNotIn(warning, self.install(served(), local_bin_on_path=True).stderr)

    def test_names_the_launcher_by_full_path_when_not_on_path(self) -> None:
        on_path = self.install(served(), local_bin_on_path=True)
        self.assertEqual(on_path.stdout.splitlines()[-1], "Start: claude-podhaus")
        off_path = self.install(served(), local_bin_on_path=False)
        self.assertEqual(off_path.stdout.splitlines()[-1], f"Start: {self.machine.local_bin}/claude-podhaus")

    def test_warns_when_claude_is_missing(self) -> None:
        self.assertIn("claude not found", self.install(served()).stderr)
        self.machine.stub(self.machine.bin, "claude", "#!/bin/sh\n")
        self.assertNotIn("claude not found", self.install(served()).stderr)

    def test_a_missing_download_fails_and_leaves_no_partial_file(self) -> None:
        files = served()
        del files["/setup/claude-podhaus"]
        result = self.install(files)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(".local/bin/claude-podhaus.part", self.machine.files_under_home())
        self.assertNotIn(".local/bin/claude-podhaus", self.machine.files_under_home())


class ClaudeInstallWithoutCurlTest(MachineTest):
    def test_stops_before_writing_anything(self) -> None:
        with StandInSetup(served()) as stand_in:
            environment = self.machine.environment(True, LLM_POD_HAUS_URL=stand_in.base_url)
            result = self.machine.pipe_into_sh(SETUP / "claude.sh", environment)
        self.assertEqual(result.returncode, 1)
        self.assertIn("curl not found", result.stderr)
        self.assertEqual(self.machine.files_under_home(), set())


class PiInstallTest(MachineTest):
    EXTENSION = ".pi/agent/extensions/podhaus.ts"

    def setUp(self) -> None:
        super().setUp()
        self.machine.grant("curl")

    def install(self, **extra: str) -> subprocess.CompletedProcess[str]:
        with StandInSetup(served()) as stand_in:
            environment = self.machine.environment(True, LLM_POD_HAUS_URL=stand_in.base_url, **extra)
            return self.machine.pipe_into_sh(SETUP / "pi.sh", environment)

    def test_follows_pis_own_directory_setting(self) -> None:
        agent = self.machine.home / "elsewhere" / "pi-agent"
        result = self.install(PI_CODING_AGENT_DIR=str(agent))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.machine.files_under_home(), {"elsewhere/pi-agent/extensions/podhaus.ts"})

    def test_installs_the_extension(self) -> None:
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        installed = self.machine.home / self.EXTENSION
        self.assertEqual(installed.read_bytes(), (SETUP / "podhaus.ts").read_bytes())
        self.assertEqual(self.mode(installed), 0o644)
        self.assertIn("/login podhaus", result.stdout)
        self.assertIn("/model", result.stdout)

    def test_writes_only_the_extension(self) -> None:
        settings = self.machine.home / ".pi" / "agent" / "settings.json"
        other = self.machine.home / ".pi" / "agent" / "extensions" / "other.ts"
        other.parent.mkdir(parents=True)
        settings.write_text('{"theme": "dark"}')
        other.write_text("// other")
        (self.machine.home / self.EXTENSION).write_text("// old")
        before = self.machine.files_under_home()
        self.assertEqual(self.install().returncode, 0)
        self.assertEqual(self.machine.files_under_home(), before)
        self.assertEqual(settings.read_text(), '{"theme": "dark"}')
        self.assertEqual(other.read_text(), "// other")
        self.assertNotEqual((self.machine.home / self.EXTENSION).read_text(), "// old")

    def test_warns_when_pi_is_missing(self) -> None:
        self.assertIn("pi not found", self.install().stderr)
        self.machine.stub(self.machine.bin, "pi", "#!/bin/sh\n")
        self.assertNotIn("pi not found", self.install().stderr)


class ClaudeLocalTest(MachineTest):
    """claude-podhaus against a stub claude and a stub token command."""

    def setUp(self) -> None:
        super().setUp()
        self.machine.stub(self.machine.bin, "claude", RECORDING_CLAUDE)
        self.helper = self.machine.stub(self.machine.local_bin, "llm-token", COUNTING)
        self.record = self.machine.home / "claude-record.json"

    def start(self, *args: str, **environment: str) -> tuple[subprocess.CompletedProcess[str], dict | None]:
        env = self.machine.environment(
            True, CLAUDE_STUB_RECORD=str(self.record),
            # Already in the environment; neither may reach Claude Code.
            ANTHROPIC_AUTH_TOKEN="inherited", ANTHROPIC_API_KEY="inherited",
            **environment,
        )
        result = subprocess.run(
            [SH, str(SETUP / "claude-podhaus"), *args],
            env=env, capture_output=True, text=True, timeout=60,
        )
        recorded = json.loads(self.record.read_text()) if self.record.exists() else None
        return result, recorded

    def token_runs(self) -> int:
        runs = self.machine.home / "token-runs"
        return len(runs.read_text().splitlines()) if runs.exists() else 0

    def test_sets_the_recipe_and_hands_claude_the_token_command(self) -> None:
        result, recorded = self.start("--resume", "two words")
        self.assertEqual(result.returncode, 0, result.stderr)
        for name, value in CLAUDE_RECIPE.items():
            self.assertEqual(recorded["env"][name], value, name)
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", recorded["env"])
        flag, settings, *passed = recorded["argv"]
        self.assertEqual(flag, "--settings")
        self.assertEqual(json.loads(settings), {"apiKeyHelper": "~/.local/bin/llm-token"})
        self.assertEqual(passed, ["--resume", "two words"])

    def test_claude_code_can_run_the_helper_it_is_given(self) -> None:
        """Claude Code runs apiKeyHelper through sh, which expands the tilde."""
        _, recorded = self.start()
        command = json.loads(recorded["argv"][1])["apiKeyHelper"]
        ran = subprocess.run(
            [SH, "-c", command], env=self.machine.environment(True),
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertEqual(ran.stdout.strip(), STUB_TOKEN)

    def test_runs_the_token_command_first_without_showing_the_token(self) -> None:
        result, _ = self.start()
        self.assertEqual(self.token_runs(), 1)
        self.assertNotIn(STUB_TOKEN, result.stdout + result.stderr)

    def test_a_refused_sign_in_never_starts_claude(self) -> None:
        self.machine.stub(self.machine.local_bin, "llm-token", REFUSED.decode())
        result, recorded = self.start()
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(recorded)

    def test_another_base_url_still_signs_in(self) -> None:
        result, recorded = self.start(LLM_POD_HAUS_URL="https://llm.example")
        self.assertEqual(recorded["env"]["ANTHROPIC_BASE_URL"], "https://llm.example")
        self.assertEqual(recorded["argv"][0], "--settings")
        self.assertEqual(self.token_runs(), 1)

    def test_starts_the_named_command_in_place_of_claude(self) -> None:
        self.machine.stub(self.machine.bin, "claude-wrapper", RECORDING_CLAUDE)
        result, recorded = self.start("-p", "hi", CLAUDE_PODHAUS_COMMAND="claude-wrapper")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(recorded["argv"][-2:], ["-p", "hi"])
        self.assertEqual(recorded["env"]["CLAUDE_PODHAUS_COMMAND"], "claude-wrapper")
        _, recorded = self.start("-p", "hi", CLAUDE_PODHAUS_COMMAND="claude-wrapper", LLM_POD_HAUS_URL="http://127.0.0.1:8085")
        self.assertEqual(recorded["env"]["ANTHROPIC_AUTH_TOKEN"], "local")

    def test_loopback_needs_no_sign_in(self) -> None:
        result, recorded = self.start("-p", "hi", LLM_POD_HAUS_URL="http://127.0.0.1:8085")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(recorded["env"]["ANTHROPIC_BASE_URL"], "http://127.0.0.1:8085")
        self.assertEqual(recorded["env"]["ANTHROPIC_AUTH_TOKEN"], "local")
        self.assertEqual(recorded["env"]["ANTHROPIC_API_KEY"], "")
        self.assertEqual(recorded["argv"], ["-p", "hi"])
        self.assertEqual(self.token_runs(), 0)


class ClaudeLocalAwkwardHomeTest(ClaudeLocalTest):
    """Every claude-podhaus test again, from a home directory whose path holds a
    space, both kinds of quote and a backslash."""

    home_name = "it's a \"home\" \\ dir"


class PomeriumSetupRoutesTest(unittest.TestCase):
    """The installer files are the one llm.pod.haus route with no sign-in; the page is for friends."""

    routes = yaml.safe_load((ROOT / "pomerium" / "config.yaml").read_text())["routes"]
    llm = [(index, route) for index, route in enumerate(routes) if route["from"] == "https://llm.pod.haus"]

    def public(self) -> tuple[int, dict]:
        public = [(index, route) for index, route in self.llm if route.get("allow_public_unauthenticated_access")]
        self.assertEqual(len(public), 1)
        return public[0]

    def page(self) -> tuple[int, dict]:
        return next((index, route) for index, route in self.llm if route.get("prefix") == "/setup")

    def test_public_route_covers_every_installer_file_and_nothing_else(self) -> None:
        _, route = self.public()
        self.assertIsNone(route.get("prefix"))
        for absent in ("path", "policy", "bearer_token_format"):
            self.assertNotIn(absent, route)
        self.assertFalse(route.get("pass_identity_headers", False))
        matches = re.compile(route["regex"]).search
        for file in SETUP.iterdir():
            self.assertEqual(bool(matches(f"/setup/{file.name}")), file.name != "index.html", file.name)
        for other in ("/setup", "/setup/", "/setup/claude.sh/", "/setup/claude.sh?x", "/v1/models", "/control"):
            self.assertIsNone(matches(other), other)

    def test_page_route_admits_friends_and_names_the_caller(self) -> None:
        _, route = self.page()
        friends = next(r for r in self.routes if r["from"] == "https://docs.pod.haus")
        self.assertEqual(route["policy"], friends["policy"])
        self.assertNotIn("allow_public_unauthenticated_access", route)
        self.assertTrue(route["pass_identity_headers"])

    def test_both_come_before_the_control_route_and_reach_its_origin(self) -> None:
        control_index, control = next((i, r) for i, r in self.llm if r.get("regex") == "^/control(/.*)?$")
        for index, route in (self.public(), self.page()):
            self.assertLess(index, control_index)
            for key in ("to", "preserve_host_header", "tls_upstream_server_name",
                        "tls_custom_ca_file", "tls_client_cert_file", "tls_client_key_file"):
                self.assertEqual(route[key], control[key], key)


class SetupPageTest(unittest.TestCase):
    """index.html, read as text: what it signs in with and what it offers."""

    page = (SETUP / "index.html").read_text()

    def constant(self, name: str) -> str:
        return re.search(rf'const {name} = "([^"]*)";', self.page).group(1)

    def test_signs_in_with_the_token_commands_pocket_id_client(self) -> None:
        self.assertEqual(
            set(re.findall(r"https://id\.pod\.haus[^\"'\s<]*", self.page)),
            {"https://id.pod.haus/authorize", "https://id.pod.haus/api/oidc/token"},
        )
        self.assertEqual(self.constant("CLIENT_ID"), "llm-token")
        self.assertEqual(self.constant("REDIRECT_URI"), "https://llm.pod.haus/setup/")
        self.assertEqual(self.constant("SCOPE"), "openid email groups")
        self.assertIn('code_challenge_method: "S256"', self.page)

    def test_the_callback_is_registered_with_pocket_id(self) -> None:
        client = (ROOT / "terraform" / "pocket_id.tf").read_text().split('resource "pocketid_client" "llm_token"')[1]
        callbacks = client.split("callback_urls = [")[1].split("]")[0]
        self.assertIn(f'"{self.constant("REDIRECT_URI")}"', callbacks)

    def test_offers_the_five_downloads_and_each_exists(self) -> None:
        offered = set(re.findall(r"/setup/([\w.-]+)", self.page))
        self.assertEqual(offered, {"claude.sh", "pi.sh", "llm-token", "claude-podhaus", "podhaus.ts"})
        for name in offered:
            self.assertTrue((SETUP / name).is_file(), name)

    def test_loads_nothing_from_elsewhere(self) -> None:
        self.assertEqual(re.findall(r"\bsrc=|<link\b|@import|\burl\(", self.page), [])
        for target in re.findall(r'href="([^"]*)"', self.page):
            self.assertTrue(target.startswith("/setup/"), target)

    def test_manual_recipe_matches_claude_local(self) -> None:
        block = re.search(r'<pre id="claude-env">(.*?)</pre>', self.page, re.S).group(1)
        self.assertEqual(
            set(block.splitlines()),
            {f"export {name}={pasteable(value)}" for name, value in CLAUDE_RECIPE.items()}
            | {'export ANTHROPIC_AUTH_TOKEN=<span class="key"></span>'},
        )


if __name__ == "__main__":
    unittest.main()
