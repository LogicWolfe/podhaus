"""bilby's front door writes every site's requests, and only the fields chosen.

The mise-installed caddy compiles caddy/Caddyfile and the compiled config is
checked: every host on every listener is written by the `front_door` access
logger, no site skips or renames it, that logger deletes Caddy's request object
whole, Caddy's own logger for a Host no site names writes nowhere, and each
appended field is one of a fixed set read from the request before it is
handled, the identity ones only where a proxy that sets them is the only way
in. Caddy's default logger, which writes the whole request on a proxied
response it had to abort and on a 5xx error line, drops the query and every
credential header named below, including each header a route compares with a
secret. The stock caddy has neither of the Caddyfile's
two plugins, so it compiles a copy with their uses swapped out (the layer4
proxy on :8022 removed, the Cloudflare DNS challenge replaced by Caddy's own
issuer); neither bears on logging. What Caddy prints for these fields is in
logging/tests/test_log_schema.py's caddy_front_door_* lines.

This lives here rather than under caddy/ because every file under caddy/ is in
bilby's Caddy content hash, so an edit there would restart the front door.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
CADDYFILE = ROOT / "caddy" / "Caddyfile"
LOGGER = "front_door"
CLOUDFLARE_CA = "/etc/caddy/pki/cloudflare-origin-pull-ca.pem"
DNS_CHALLENGE = "dns cloudflare {env.CLOUDFLARE_API_TOKEN}"
POMERIUM_LISTENER = ":4443"

EVERY_SITE = {
    "listener": "{http.request.local.port}",
    "remote_ip": "{http.request.remote.host}",
    "host": "{http.request.host}",
    "method": "{http.request.method}",
    "path": "{http.request.orig_uri.path}",
    "user_agent": "{http.request.header.User-Agent}",
}
FORWARDED_FOR = {"forwarded_for": "{http.request.header.X-Forwarded-For}"}
POMERIUM_ONLY = {
    "caller": "{http.request.header.X-Pomerium-Claim-Email}",
    "request_id": "{http.request.header.X-Request-Id}",
}
LOGS_INGEST_ONLY = {"client_cert": "{http.request.tls.client.subject}"}
# Request headers that carry a credential to one of bilby's routes.
CREDENTIAL_HEADERS = (
    "Authorization", "Proxy-Authorization", "Cookie", "X-Pomerium-Jwt-Assertion",
    "X-Podhaus-Gateway-Token", "X-Plex-Token", "X-Api-Key", "X-Api-Secret", "X-Amz-Security-Token",
    "X-Runner-Token", "X-Csrf-Token-Hdf5hft", "X-Hub-Signature", "X-Hub-Signature-256",
)


def stock_caddyfile(text: str) -> str:
    """The Caddyfile with its two plugin uses swapped for stock equivalents."""
    lines = text.split("\n")
    start = lines.index("\tlayer4 {")
    end = lines.index("\t}", start)
    del lines[start:end + 1]
    challenges = [i for i, line in enumerate(lines) if line.strip() == DNS_CHALLENGE]
    assert challenges, "the Caddyfile no longer uses the Cloudflare DNS challenge; update this test"
    for i in challenges:
        lines[i] = lines[i].replace(DNS_CHALLENGE, "issuer internal")
    return "\n".join(lines)


def compile_caddyfile() -> dict:
    caddy = shutil.which("caddy")
    if caddy is None:
        raise RuntimeError("caddy is not on PATH; run mise install")
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "Caddyfile"
        copy.write_text(stock_caddyfile(CADDYFILE.read_text()))
        adapted = subprocess.run(
            [caddy, "adapt", "--config", str(copy), "--adapter", "caddyfile"],
            env={**os.environ, "BANDICOOT_LAN_IPV4": "192.0.2.10", "KANGAROO_LAN_IPV4": "192.0.2.20"},
            capture_output=True, text=True, check=True,
        )
    return json.loads(adapted.stdout)


def handlers(node: object, kind: str) -> list[dict]:
    """Every handler of one kind anywhere under `node`."""
    if isinstance(node, list):
        return [h for item in node for h in handlers(item, kind)]
    if not isinstance(node, dict):
        return []
    found = [node] if node.get("handler") == kind else []
    return found + [h for value in node.values() for h in handlers(value, kind)]


def appended(node: object) -> dict[str, str]:
    """Every field a log_append handler anywhere under `node` adds."""
    return {h["key"]: h["value"] for h in handlers(node, "log_append")}


def secret_headers(node: object) -> set[str]:
    """Every request header a matcher compares with a secret from the environment."""
    if isinstance(node, list):
        return {h for item in node for h in secret_headers(item)}
    if not isinstance(node, dict):
        return set()
    matcher = node.get("header")
    found = {name for name, values in matcher.items()
             if any("{env." in value for value in values)} if isinstance(matcher, dict) else set()
    return found | {h for value in node.values() for h in secret_headers(value)}


def hosts(route: dict) -> list[str]:
    return [h for m in route.get("match", []) for h in m.get("host", [])]


def cloudflare_only(server: dict) -> set[str]:
    """The names this listener serves only to Cloudflare's origin-pull certificate."""
    return {
        host
        for policy in server.get("tls_connection_policies", [])
        if CLOUDFLARE_CA in policy.get("client_authentication", {}).get("ca", {}).get("pem_files", [])
        for host in policy["match"]["sni"]
    }


class FrontDoorAccessLog(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = compile_caddyfile()
        cls.servers = cls.config["apps"]["http"]["servers"].values()
        cls.loggers = cls.config["logging"]["logs"]

    def sites(self) -> list[tuple[dict, dict]]:
        """Each listener's top-level routes, one per site block."""
        return [(server, route) for server in self.servers for route in server["routes"]]

    def test_every_host_on_every_listener_is_written_by_front_door(self) -> None:
        for server in self.servers:
            with self.subTest(listener=server["listen"]):
                logs = server["logs"]
                self.assertNotIn("skip_hosts", logs)
                named = [h for route in server["routes"] for h in hosts(route)]
                if not named:
                    self.assertEqual(logs, {"default_logger_name": LOGGER})
                    continue
                self.assertEqual(logs["logger_names"], {h: [LOGGER] for h in named})

    def test_the_logger_deletes_the_request_object_whole(self) -> None:
        self.assertEqual(self.loggers[LOGGER], {
            "writer": {"output": "stdout"},
            "encoder": {
                "format": "filter",
                "wrap": {"format": "json"},
                "fields": {name: {"filter": "delete"}
                           for name in ("request", "resp_headers", "bytes_read", "size", "user_id")},
            },
            "include": [f"http.log.access.{LOGGER}"],
        })

    def test_a_request_for_a_host_no_site_names_is_not_written(self) -> None:
        # Caddy's base access logger would write such a request whole,
        # headers and query included.
        self.assertIn("http.log.access", self.loggers["default"]["exclude"])

    def test_caddys_own_lines_lose_the_query_and_every_credential_header(self) -> None:
        # The default logger writes the whole request on a proxied response
        # Caddy had to abort and on a 5xx error line.
        self.assertEqual(self.loggers["default"].get("encoder"), {
            "format": "filter",
            "wrap": {"format": "json"},
            "fields": {
                "request>uri": {"filter": "regexp", "regexp": r"\?.*$"},
                "request>headers>Referer": {"filter": "regexp", "regexp": r"\?.*$"},
                **{f"request>headers>{name}": {"filter": "delete"} for name in CREDENTIAL_HEADERS},
            },
        })

    def test_every_header_a_route_checks_against_a_secret_is_a_credential_header(self) -> None:
        checked = secret_headers(self.config["apps"]["http"])
        self.assertTrue(checked)
        self.assertEqual(checked - set(CREDENTIAL_HEADERS), set())

    def test_no_site_skips_or_renames_its_access_log(self) -> None:
        # A site that did would silently stop being written by front_door.
        for server, route in self.sites():
            with self.subTest(listener=server["listen"], hosts=hosts(route)):
                found = [h for h in handlers(route, "vars") if {"log_skip", "access_logger_names"} & set(h)]
                self.assertEqual(found, [])

    def test_every_field_is_recorded_before_the_request_is_handled(self) -> None:
        # A field added after handling is lost when a proxied response is
        # aborted, which leaves the access line with its status and duration only.
        for server, route in self.sites():
            with self.subTest(listener=server["listen"], hosts=hosts(route)):
                late = [h["key"] for h in handlers(route, "log_append") if h.get("early") is not True]
                self.assertEqual(late, [])

    def test_every_site_appends_who_reached_what(self) -> None:
        for server, route in self.sites():
            with self.subTest(listener=server["listen"], hosts=hosts(route)):
                self.assertEqual(appended(route) | EVERY_SITE, appended(route))

    def test_identity_fields_appear_only_where_a_proxy_sets_them(self) -> None:
        cloudflare_sites = 0
        for server, route in self.sites():
            names = set(hosts(route))
            expected = dict(EVERY_SITE)
            if server["listen"] == [POMERIUM_LISTENER]:
                expected |= FORWARDED_FOR | POMERIUM_ONLY
            elif names and names <= cloudflare_only(server):
                cloudflare_sites += 1
                expected |= FORWARDED_FOR
            elif names == {"logs-ingest.pod.haus"}:
                expected |= LOGS_INGEST_ONLY
            with self.subTest(listener=server["listen"], hosts=sorted(names)):
                self.assertEqual(appended(route), expected)
        self.assertTrue(cloudflare_sites)


if __name__ == "__main__":
    unittest.main()
