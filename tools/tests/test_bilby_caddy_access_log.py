"""bilby's front door writes every site's requests, and only the fields chosen.

The mise-installed caddy compiles caddy/Caddyfile and the compiled config is
checked: every host on every listener is written by one access logger, no
site skips or renames it, that logger deletes Caddy's request and response
headers whole, Caddy's own logger for a Host no site names writes nowhere, and
every site appends the same fields, read from the request before it is
handled, with a field read from a header a proxy sets only where a client
certificate is the only way in. Caddy's default logger, which writes the whole
request on a proxied response it had to abort and on a 5xx error line, drops
the query and every credential header, including each header a route compares
with a secret. The stock caddy has neither of the Caddyfile's two plugins, so
it compiles a copy with their uses swapped out (the layer4 proxy on :8022
removed, the Cloudflare DNS challenge replaced by Caddy's own issuer); neither
bears on logging. What Caddy prints for these fields is in
logging/tests/test_log_schema.py's caddy_front_door_* lines.

This lives here rather than under caddy/ because every file under caddy/ is in
bilby's Caddy content hash, so an edit there would restart the front door.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
CADDYFILE = ROOT / "caddy" / "Caddyfile"
DNS_CHALLENGE = "dns cloudflare {env.CLOUDFLARE_API_TOKEN}"
# A field read from one of these is only as true as the proxy that set it.
PROXY_SET = "{http.request.header.X-"
TLS_CLIENT = "{http.request.tls.client."
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


def requires_client_certificate(server: dict, names: list[str]) -> bool:
    """Whether every name, or the listener's default when the site names
    none, is served only to a client presenting a certificate."""
    policies = server.get("tls_connection_policies", [])
    default = [policy for policy in policies if "match" not in policy]

    def policy(name: str | None) -> dict | None:
        named = [p for p in policies if name in p.get("match", {}).get("sni", [])]
        return (named or default or [None])[0]

    chosen = [policy(name) for name in names or [None]]
    return all(p is not None and "client_authentication" in p for p in chosen)


class FrontDoorAccessLog(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = compile_caddyfile()
        cls.servers = cls.config["apps"]["http"]["servers"].values()
        cls.loggers = cls.config["logging"]["logs"]

    def sites(self) -> list[tuple[dict, dict]]:
        """Each listener's top-level routes, one per site block."""
        return [(server, route) for server in self.servers for route in server["routes"]]

    def access_logger(self) -> str:
        """The one logger every listener writes its requests to."""
        names = set()
        for server in self.servers:
            logs = server["logs"]
            names |= {logs["default_logger_name"]} if "default_logger_name" in logs else set()
            names |= {name for named in logs.get("logger_names", {}).values() for name in named}
        (name,) = names
        return name

    def test_every_host_on_every_listener_is_written_by_the_access_logger(self) -> None:
        logger = self.access_logger()
        for server in self.servers:
            with self.subTest(listener=server["listen"]):
                logs = server["logs"]
                self.assertNotIn("skip_hosts", logs)
                named = [h for route in server["routes"] for h in hosts(route)]
                if not named:
                    self.assertEqual(logs, {"default_logger_name": logger})
                    continue
                self.assertEqual(logs["logger_names"], {h: [logger] for h in named})

    def test_the_logger_deletes_the_request_and_response_headers_whole(self) -> None:
        logger = self.access_logger()
        self.assertEqual(self.loggers[logger]["include"], [f"http.log.access.{logger}"])
        fields = self.loggers[logger]["encoder"]["fields"]
        for name in ("request", "resp_headers"):
            with self.subTest(field=name):
                self.assertEqual(fields[name], {"filter": "delete"})

    def test_a_request_for_a_host_no_site_names_is_not_written(self) -> None:
        # Caddy's base access logger would write such a request whole,
        # headers and query included.
        self.assertIn("http.log.access", self.loggers["default"]["exclude"])

    def test_caddys_own_lines_lose_the_query_and_every_credential_header(self) -> None:
        # The default logger writes the whole request on a proxied response
        # Caddy had to abort and on a 5xx error line.
        fields = self.loggers["default"]["encoder"]["fields"]
        for name in ("request>uri", "request>headers>Referer"):
            with self.subTest(field=name):
                rule = fields[name]
                self.assertEqual(rule["filter"], "regexp")
                self.assertEqual(re.sub(rule["regexp"], rule.get("value", ""), "/path?token=secret"), "/path")
        secret_checked = secret_headers(self.config["apps"]["http"])
        self.assertTrue(secret_checked)
        for header in set(CREDENTIAL_HEADERS) | secret_checked:
            with self.subTest(header=header):
                self.assertEqual(fields[f"request>headers>{header}"], {"filter": "delete"})

    def test_no_site_skips_or_renames_its_access_log(self) -> None:
        # A site that did would silently stop being written by the access logger.
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

    def test_every_site_appends_the_same_request_fields(self) -> None:
        # Apart from what a proxy or a client certificate adds, a site whose
        # lines lack a field the others carry cannot be read beside them.
        def own(route: dict) -> dict[str, str]:
            return {k: v for k, v in appended(route).items() if not v.startswith((PROXY_SET, TLS_CLIENT))}

        (first_server, first), *rest = self.sites()
        self.assertTrue(own(first))
        for server, route in rest:
            with self.subTest(listener=server["listen"], hosts=hosts(route)):
                self.assertEqual(own(route), own(first))

    def test_a_field_a_proxy_sets_is_recorded_only_behind_a_client_certificate(self) -> None:
        # Anyone reaching a site directly could write those headers themselves.
        behind_proxy = 0
        for server, route in self.sites():
            proxy_set = [k for k, v in appended(route).items() if v.startswith(PROXY_SET)]
            if not proxy_set:
                continue
            behind_proxy += 1
            with self.subTest(listener=server["listen"], hosts=hosts(route), fields=proxy_set):
                self.assertTrue(requires_client_certificate(server, hosts(route)))
        self.assertTrue(behind_proxy)


if __name__ == "__main__":
    unittest.main()
