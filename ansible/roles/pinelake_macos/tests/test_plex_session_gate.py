#!/usr/bin/env python3
import http.server
import plistlib
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path


ROLE_DIR = Path(__file__).resolve().parents[1]
SCRIPT = ROLE_DIR / "files" / "plex-session-gate"
IDENTITY = {
    "MachineIdentifier": "c9d75740-0fd3-4bba-9874-be61f5dc8d38",
    "ProcessedMachineIdentifier": "92311858cdd55fb33583fda2e6fc037e3655da85",
    "AnonymousMachineIdentifier": "166ee17f-2122-4dcf-9d5e-38961c51ff25",
    "CertificateUUID": "5801df40ceea4deaaefd8bd027fc22ff",
}


class PlexHandler(http.server.BaseHTTPRequestHandler):
    status = 200
    body = b'<MediaContainer size="0"></MediaContainer>'
    received_token: str | None = None

    def do_GET(self) -> None:
        type(self).received_token = self.headers.get("X-Plex-Token")
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/xml")
        self.end_headers()
        self.wfile.write(type(self).body)

    def log_message(self, format: str, *args: object) -> None:
        return


class PlexSessionGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.plist = Path(self.tempdir.name) / "plex.plist"
        with self.plist.open("wb") as stream:
            plistlib.dump({**IDENTITY, "PlexOnlineToken": "test-secret"}, stream)

        PlexHandler.status = 200
        PlexHandler.body = b'<MediaContainer size="0"></MediaContainer>'
        PlexHandler.received_token = None
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), PlexHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tempdir.cleanup()

    def _run(self, url: str | None = None) -> subprocess.CompletedProcess[str]:
        endpoint = url or (
            f"http://127.0.0.1:{self.server.server_port}/status/sessions"
        )
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--url",
                endpoint,
                "--preferences-plist",
                str(self.plist),
                "--timeout",
                "1",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_allows_zero_sessions_and_sends_token_as_header(self) -> None:
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "Plex sessions: 0")
        self.assertEqual(PlexHandler.received_token, "test-secret")
        self.assertNotIn("test-secret", result.stdout + result.stderr)

    def test_reads_container_preferences_xml(self) -> None:
        preferences = Path(self.tempdir.name) / "Preferences.xml"
        preferences.write_text(
            '<?xml version="1.0"?>'
            '<Preferences PlexOnlineToken="test-secret" '
            + " ".join(f'{key}="{value}"' for key, value in IDENTITY.items())
            + " />",
            encoding="utf-8",
        )
        endpoint = f"http://127.0.0.1:{self.server.server_port}/status/sessions"
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--url",
                endpoint,
                "--preferences-xml",
                str(preferences),
                "--timeout",
                "1",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(PlexHandler.received_token, "test-secret")
        self.assertNotIn("test-secret", result.stdout + result.stderr)

    def test_blocks_an_active_session(self) -> None:
        PlexHandler.body = b'<MediaContainer size="1"><Video title="Movie"/></MediaContainer>'
        result = self._run()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.strip(), "Plex sessions: 1")

    def test_fails_closed_on_malformed_xml(self) -> None:
        PlexHandler.body = b"<not-xml"
        result = self._run()
        self.assertEqual(result.returncode, 2)
        self.assertIn("could not prove zero sessions", result.stderr)

    def test_fails_closed_on_http_error(self) -> None:
        PlexHandler.status = 500
        result = self._run()
        self.assertEqual(result.returncode, 2)
        self.assertIn("could not prove zero sessions", result.stderr)

    def test_fails_closed_when_server_is_unreachable(self) -> None:
        result = self._run("http://127.0.0.1:1/status/sessions")
        self.assertEqual(result.returncode, 2)
        self.assertIn("could not prove zero sessions", result.stderr)

    def test_fails_closed_when_token_is_missing(self) -> None:
        with self.plist.open("wb") as stream:
            plistlib.dump(IDENTITY, stream)
        result = self._run()
        self.assertEqual(result.returncode, 2)
        self.assertIn("could not prove zero sessions", result.stderr)

    def test_fails_closed_when_processed_identity_differs(self) -> None:
        preferences = {**IDENTITY, "PlexOnlineToken": "test-secret"}
        preferences["ProcessedMachineIdentifier"] = "wrong"
        with self.plist.open("wb") as stream:
            plistlib.dump(preferences, stream)
        result = self._run()
        self.assertEqual(result.returncode, 2)
        self.assertIn("ProcessedMachineIdentifier", result.stderr)

    def test_validation_only_does_not_require_a_live_endpoint(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--url",
                "http://127.0.0.1:1/status/sessions",
                "--preferences-plist",
                str(self.plist),
                "--validate-only",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "Plex identity: verified")


if __name__ == "__main__":
    unittest.main()
