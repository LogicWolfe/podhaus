#!/usr/bin/env python3
import http.server
import importlib.util
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import unittest.mock
import urllib.parse
from importlib.machinery import SourceFileLoader
from pathlib import Path


ROLE_DIR = Path(__file__).resolve().parents[1]
SCRIPT = ROLE_DIR / "files" / "plex-advertise"


def load_script():
    """Import the extensionless launch-daemon script as a module."""
    loader = SourceFileLoader("plex_advertise", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


plex_advertise = load_script()


class PlexHandler(http.server.BaseHTTPRequestHandler):
    published = ""
    received_token: str | None = None
    puts: list[str] = []

    def _respond(self) -> None:
        body = (
            '<?xml version="1.0" encoding="UTF-8"?><MediaContainer>'
            '<Setting id="FriendlyName" value="PineLake" />'
            f'<Setting id="customConnections" value="{type(self).published}" />'
            "</MediaContainer>"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/xml")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        type(self).received_token = self.headers.get("X-Plex-Token")
        self._respond()

    def do_PUT(self) -> None:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        value = query["customConnections"][0]
        type(self).puts.append(value)
        type(self).published = value
        self._respond()

    def log_message(self, format: str, *args: object) -> None:
        return


class PlexAdvertiseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.preferences = Path(self.tempdir.name) / "Preferences.xml"
        self.preferences.write_text(
            '<?xml version="1.0"?><Preferences PlexOnlineToken="test-secret" />',
            encoding="utf-8",
        )
        PlexHandler.published = ""
        PlexHandler.received_token = None
        PlexHandler.puts = []
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), PlexHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tempdir.cleanup()

    def server_client(self) -> "plex_advertise.PlexServer":
        token = plex_advertise.read_token(self.preferences)
        return plex_advertise.PlexServer(self.base_url, token, 5.0)

    def test_lan_address_leads_the_published_list(self) -> None:
        """Every client can use the literal address; Bonjour is the fallback."""
        advertisement = plex_advertise.Advertisement("en0", 32400)
        with unittest.mock.patch.object(
            plex_advertise, "lan_address", return_value="192.168.1.128"
        ), unittest.mock.patch.object(
            plex_advertise, "bonjour_name", return_value="Baxters-Mac-mini"
        ):
            self.assertEqual(
                advertisement.render(),
                "http://192.168.1.128:32400/,"
                "http://Baxters-Mac-mini.local:32400/",
            )

    def test_reads_the_published_list_and_sends_the_token(self) -> None:
        PlexHandler.published = "http://192.168.1.9:32400/"
        self.assertEqual(
            self.server_client().custom_connections(), "http://192.168.1.9:32400/"
        )
        self.assertEqual(PlexHandler.received_token, "test-secret")

    def test_publishes_a_changed_address(self) -> None:
        PlexHandler.published = "http://192.168.1.9:32400/"
        self.server_client().set_custom_connections("http://192.168.1.128:32400/")
        self.assertEqual(PlexHandler.puts, ["http://192.168.1.128:32400/"])

    def test_an_unreachable_plex_is_an_error_not_an_empty_list(self) -> None:
        """A silent empty read would publish nothing and strand every client."""
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            closed_port = probe.getsockname()[1]
        client = plex_advertise.PlexServer(
            f"http://127.0.0.1:{closed_port}", "test-secret", 1.0
        )
        with self.assertRaises(plex_advertise.PlexUnavailable):
            client.custom_connections()

    def test_a_preferences_file_without_a_token_is_an_error(self) -> None:
        empty = Path(self.tempdir.name) / "Empty.xml"
        empty.write_text('<?xml version="1.0"?><Preferences />', encoding="utf-8")
        with self.assertRaises(RuntimeError):
            plex_advertise.read_token(empty)

    def test_a_missing_interface_fails_loudly(self) -> None:
        """Run as a subprocess: no macOS tooling here, so detection must fail."""
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--interface",
                "does-not-exist",
                "--base-url",
                self.base_url,
                "--preferences",
                str(self.preferences),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("plex-advertise:", result.stderr)
        self.assertEqual(PlexHandler.puts, [])


if __name__ == "__main__":
    unittest.main()
