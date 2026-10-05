"""The log schema, proven by running the real Alloy modules on log lines.

Each fixture below is one line as a service prints it. All of them go through
the modules a host runs, inside one `grafana/alloy:latest` container:
docker-logs.alloy's relabel rules (`docker_targets`, on stand-in Docker
targets), journal.alloy's priority mapping (`journal_levels`), the three
file-source modules, chain.alloy with every parser, and enrich.alloy. An OTLP
file exporter writes what would have been shipped. Each fixture's row must
carry exactly the schema's resource attributes, exactly the schema's pipeline
attributes plus the service's own fields (every field of a JSON line, flattened
with dots, credentials removed, plus what a parser promotes), the expected body
and the expected severity. A fixture that a module drops must produce no row.
The schema is docs/logging.md. Expected attributes for lines that carry a
credential are written out literally, never computed with enrich.alloy's own
rule, so a leak cannot pass by copying the bug.

Every tailer's label set, the Docker relabel rule list and the Docker
tailer's arguments are pinned too, read back from the running Alloy through
its HTTP API, and each pin is what is deployed. A tailer keys its saved read
positions on its labels, so a changed label makes every host re-read and
re-ship that source's retained logs. And a host's running Alloy reloads a
changed module before its container is recreated, so a changed rule list or
argument restarts every container tailer, which deletes every saved position:
every running container's log is shipped again. A pin that fails is the point;
see docs/logging.md before changing one.

What stands in for the real sources: a Docker fixture is a file read by
loki.source.file under the labels docker_targets gives a discovered container,
plus the `host` label docker_logs' tailer adds (the stand-in drops the
`filename` label loki.source.file adds, which a Docker source does not have,
and strips ANSI as docker_logs does). A journal fixture is a file read under
the labels loki.source.journal gives an entry. The file-source modules read
real files. docker_logs and journal also run, with no Docker socket or
journal to read, so their tailers' labels can be read back. Every stand-in
Docker target carries the hidden labels of a real container as fractal's
discovery.docker reported them, so the pins see what the relabel rules keep and
drop.

Provenance of the lines. Captured on fractal with `docker logs`: caddy_access,
llm_watcher_resume, llm_watcher_slots, alloy_transfer, rathole_client.
Captured from ClickStack: journal_dockerd_error, pomerium_authorize (email replaced),
pomerium_callback (code and state replaced with stand-ins of the same shape),
pocket_id_authorize (state replaced), flood_request, rustfs_no_message,
komodo_ferretdb and backrest (bodies captured, the parser-stripped time and
level prefix rebuilt from the module's documented shape). llm_server_prompt is
from llm/tests/fixtures, as is caddy_remote_access. Every other line is the example in its module's
header, completed where the header elides it, or written for the case it
names (caddy_admin's credential header, the json_* credential and shape
lines, the severity fallback lines, the journal and file-source lines).

Needs Docker. Without it the whole class is skipped with the reason printed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / "logging" / "alloy-modules"
IMAGE = "grafana/alloy:latest"
HOST = "testhost"
RUN_SECONDS = 120
API_PORT = 12345
# Key words whose value is a credential. A row may carry none of them as any
# dotted part of an attribute name.
DENIED_WORDS = frozenset({
    "authorization", "cookie", "set-cookie", "password", "access_token", "refresh_token", "id_token",
})
# The credential values the fixtures carry; none may reach a row.
SECRET_VALUES = (
    "hunter2", "Bearer stand-in", "stand-in-new-password", "stand-in-cookie", "Bearer stand-in-token",
    "sid=stand-in-session",
)


def denied_parts(key: str) -> list[str]:
    return [part for part in key.split(".") if part.lower() in DENIED_WORDS]


@dataclass(frozen=True)
class Docker:
    """A container as Docker discovery reports it."""

    container: str
    project: str | None = None
    compose_service: str | None = None
    stream: str = "stdout"
    docker_labels: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Journal:
    """A journal entry's fields as loki.source.journal labels them."""

    reader: str
    unit: str | None
    identifier: str
    transport: str
    priority: str


@dataclass(frozen=True)
class File:
    """A line in a file one of the file-source modules tails, and the
    container the host config names for it."""

    path: str
    container: str
    project: str
    compose_service: str


PLEX_FILE = ("plex/Plex Media Server.log", "testhost-plex", "testhost-plex", "testhost-plex")
FLOOD_DB = "flood-db"
RTORRENT = ("rtorrent", "flood", "rtorrent")
CLICKHOUSE_FILE = ("clickhouse/clickhouse-server.err.log", "clickstack-clickhouse", "clickstack",
                   "clickstack-clickhouse")


@dataclass(frozen=True)
class Row:
    service: str
    body: str
    severity: str | None
    fields: dict[str, object] = field(default_factory=dict)
    timestamp: str | None = None


@dataclass(frozen=True)
class Fixture:
    name: str
    source: Docker | Journal | File
    line: str
    row: Row | None


SEVERITY_NUMBER = {"TRACE": 1, "DEBUG": 5, "INFO": 9, "WARN": 13, "ERROR": 17, "FATAL": 21}


def flattened(value: object, prefix: str = "") -> dict[str, object]:
    """A JSON value as OTTL's ParseJSON and flatten leave it.

    Nested keys join with dots and list items take their index; an empty map
    or list leaves no key; every number is a double.
    """
    if isinstance(value, dict):
        items = value.items()
    elif isinstance(value, list):
        items = enumerate(value)
    elif isinstance(value, int) and not isinstance(value, bool):
        return {prefix[:-1]: float(value)}
    else:
        return {prefix[:-1]: value}
    out: dict[str, object] = {}
    for key, child in items:
        out.update(flattened(child, f"{prefix}{key}."))
    return out


def json_fields(text: str) -> dict[str, object]:
    """The attributes a JSON object without credentials becomes: every field, flattened.

    A line with a credential is written out literally in its fixture instead.
    """
    fields = flattened(json.loads(text))
    denied = [key for key in fields if denied_parts(key)]
    assert not denied, f"write the expected fields of this line out literally: {denied}"
    return fields


# --- Lines -----------------------------------------------------------------

CADDY_ACCESS = r'''{"level":"info","ts":1791110320.177741,"logger":"http.log.access.llm_lan","msg":"handled request","duration":0.000058441,"status":403,"path":"/wyvrn/Synapse","agent_id":"","session_id":"","client":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) razerappengine/4.0.827 Chrome/146.0.7680.179 Electron/41.2.0 Safari/537.36","remote_ip":"172.18.0.1"}'''
CADDY_ADMIN = r'''{"level":"info","ts":1788960526.0307655,"logger":"admin.api","msg":"received request","method":"GET","host":"127.0.0.1:2019","uri":"/config/","remote_ip":"127.0.0.1","remote_port":"41234","headers":{"Accept-Encoding":["gzip"],"Authorization":["Bearer stand-in"],"User-Agent":["Go-http-client/1.1"]}}'''
# The model ingress worker's signed-in access line, whose `caller` llm/tests checks the Caddyfile writes.
CADDY_REMOTE_ACCESS = (ROOT / "llm" / "tests" / "fixtures" / "caddy_llm_access_sample.jsonl").read_text().splitlines()[0]
POMERIUM_AUTHORIZE = r'''{"level":"info","server-name":"all","service":"authorize","request-id":"096a6dcf-7fe1-4b1c-9a06-570b94e18b6a","check-request-id":"096a6dcf-7fe1-4b1c-9a06-570b94e18b6a","method":"GET","path":"/api/healthz","host":"git.pod.haus","ip":"144.6.147.203","session-id":"e92e2d46-3192-4efc-b57c-1b529f75417a","user":"2723e667-4325-4bcb-b91b-ed7442641558","email":"someone@example.com","envoy-route-checksum":451964231414847312,"envoy-route-id":"6510f2df38fa60b5","route-checksum":451964231414847312,"route-id":"","allow":true,"allow-why-true":["email-ok"],"deny":false,"deny-why-false":[],"time":"2026-10-04T18:41:02+08:00","message":"authorize check"}'''
POMERIUM_CALLBACK = r'''{"level":"debug","ip":"127.0.0.1","user_agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36","referer":"https://id.pod.haus/","request-id":"43864759-7445-4c8c-8bc1-76342ca6ab60","duration":276.483145,"size":402,"status":302,"method":"GET","host":"authenticate.pod.haus","path":"/oauth2/callback?code=StandInCode0123456789abcdefABCDEF&state=U3RhbmQtaW4gc3RhdGUgYmxvYg-_fOr9zZ1x%3D&iss=https%3A%2F%2Fid.pod.haus","time":"2026-09-09T21:12:14+08:00","message":"http-request"}'''
POCKET_ID_AUTHORIZE = r'''{"time":"2026-10-04T18:24:32.295529839+08:00","level":"INFO","msg":"HTTP request completed","app":"pocket-id","version":"2.17.0","request_id":"e169418e-3099-4ed7-b80b-8922a51649ee","status":302,"method":"GET","path":"/authorize","query":"client_id=pomerium&code_challenge=XwZSwFsHBbJrUZ8ggB1IyeDvYibCRSpZ73nImc7Ms8w&code_challenge_method=S256&redirect_uri=https%3A%2F%2Fauthenticate.pod.haus%2Foauth2%2Fcallback&response_type=code&scope=openid+email+profile+groups+offline_access&state=U3RhbmQtaW4gc3RhdGU%3D","route":"/authorize","ip":"172.18.0.4","latency":13512444,"referer":"","user_agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36","body_size":84}'''
FLOOD_REQUEST = r'''{"level":30,"time":"2026-10-04T10:41:37.738Z","pid":7,"hostname":"0b39d01f9aa3","name":"flood:web-server","reqId":"req-dzp","req":{"method":"GET","url":"/","host":"localhost:3000","remoteAddress":"::1","remotePort":44466},"msg":"incoming request"}'''
RUSTFS_NO_MESSAGE = r'''{"timestamp":"2026-10-04T18:40:17.185551412+08:00","level":"ERROR","duration":"15.670647ms","resp":"Response { status: 501, version: HTTP/1.1, headers: {\"content-type\": \"application/xml\"}, body: Body { once: b\"<?xml version=\\\"1.0\\\" encoding=\\\"UTF-8\\\"?><Error><Code>NotImplemented</Code><Message>Unknown operation</Message></Error>\", remaining_limit: None } }","target":"s3s::service","filename":"/usr/local/cargo/registry/src/index.crates.io-1949cf8c6b5b557f/s3s-0.16.0/src/service.rs","line_number":680,"threadName":"rustfs-worker","threadId":"ThreadId(19)"}'''
JSON_PASSWORD_NO_MESSAGE = r'''{"ok":true,"password":"hunter2","user":"someone"}'''
JSON_PASSWORD_NESTED = r'''{"password":{"new":"stand-in-new-password"}}'''
JSON_COOKIE_ARRAY = r'''{"headers":{"Cookie":[{"name":"sid","value":"stand-in-cookie"}]}}'''
JSON_AUTHORIZATION_OBJECT = r'''{"msg":"request","authorization":{"token":"Bearer stand-in-token"}}'''
JSON_SET_COOKIE = r'''{"msg":"response","Set-Cookie":"sid=stand-in-session; Path=/","status":200}'''
JSON_MALFORMED = r'''{"msg":"half written" "user":}'''
JSON_ARRAY = r'''[{"msg":"first"},{"msg":"second"}]'''
JSON_LEVEL_FIELD = r'''{"msg":"error budget ok","level":"info"}'''
LLM_WATCHER_RESUME = r'''{"ts": "2026-10-04T10:25:04.641Z", "level": "info", "event": "handoff.resume", "msg": "model ready", "trigger": "automatic", "quiet_since_ts": "2026-10-04T10:22:57.629Z", "load_started_ts": "2026-10-04T10:23:57.631Z", "ready_ts": "2026-10-04T10:25:03.631Z"}'''
LLM_WATCHER_SLOTS = r'''{"ts": "2026-10-04T10:25:04.684Z", "level": "info", "event": "slots.changed", "msg": "slot report changed", "slots": [{"id": 0, "tokens": 0, "busy": false}, {"id": 1, "tokens": 12, "busy": true}], "pool_tokens": 12, "pool_limit": 204800}'''
LLM_SERVER_PROMPT = r'''14.15.016.142 I slot   operator(): id  2 | task 5398 | new prompt, n_ctx_slot = 163840, n_keep = 0, task.n_tokens = 103'''
HYPERDX_JSON = r'''{"level":40,"time":1778903804921,"pid":14,"hostname":"3c1f0e2a9b7d","req":{"method":"GET","url":"/health"},"msg":"HTTP GET /health slow"}'''
CLICKSTACK_OTEL = r'''{"level":"info","ts":1778902378.3935137,"logger":"supervisor","caller":"supervisor/supervisor.go:668","msg":"Connected to the OpAMP server"}'''
CLICKSTACK_MONGO = r'''{"t":{"$date":"2026-05-16T11:56:30.664+08:00"},"s":"I","c":"NETWORK","id":22943,"ctx":"listener","msg":"Connection accepted","attr":{"remote":"172.18.0.9:51234","uuid":{"uuid":{"$uuid":"0e3f6c2a-6d4b-4b8e-9a51-2f1d6b7c8e90"}},"connectionId":12,"connectionCount":3}}'''
OP_CONNECT_API = r'''{"log_message":"(I) GET /v1/vaults/abc/items completed (200: OK) in 23ms","timestamp":"2026-05-16T03:43:03.428714669Z","level":3}'''
OP_CONNECT_SYNC = r'''{"log_message":"(W) ### sync took longer than expected ###","timestamp":"2026-05-16T03:43:03.428714669Z","level":2}'''
KOMODO_FERRETDB = "\t".join([
    "2026-05-16T03:57:41.742Z", "INFO", "middleware/dispatcher.go:131", "Command handled",
    '{"command":"find","duration":"833.379µs","handler":"documentdb","name":"middleware","result":"ok"}',
])
BACKREST = "\t".join([
    "2026-10-04T04:20:02.162-0600", "INFO", "running task",
    '{"task": "forget for plan \\"syncthing\\" in repo \\"podhaus-pinelake\\"", "runAt": "2026-10-04T04:20:02-06:00"}',
])
PLEX_LINE = r'''Sep 09, 2026 17:44:40.556 [281472660173024] DEBUG - Transcoder: Cleaning up resources'''
PLEX_IDENTITY = r'''Sep 09, 2026 17:44:41.002 [281472660173024] DEBUG - Request: [172.18.0.12:40112 (Subnet)] GET /identity (4 live) #1c0 Signed-in'''
CLICKHOUSE_ERROR = r'''2026.05.16 12:00:24.261660 [ 747 ] {} <Error> default.otel_logs (b1c2d3e4-0000-4000-8000-000000000000): Code: 252. DB::Exception: Too many parts (300)'''
DOCKERD_ERROR = r'''time="2026-10-04T18:52:30.318099418+08:00" level=error msg="healthcheck failed fatally" error="session healthcheck failed fatally: Unavailable: connection error: desc = \"transport: Error while dialing: only one connection allowed\""'''


# One target of fractal's Caddy container as discovery.docker reported it
# through Alloy's HTTP API, split by what the relabel rules do with it.
# Kept: the container's own hidden labels.
CAPTURED_CONTAINER = {
    "__meta_docker_container_id": "74e77f33768ab8b9576ee79899cdd9f5154b67c45c3d5b1b5130b01281f65269",
    "__meta_docker_container_label_autoheal": "true",
    "__meta_docker_container_label_org_opencontainers_image_description":
        "a powerful, enterprise-ready, open source web server with automatic HTTPS written in Go",
    "__meta_docker_container_label_org_opencontainers_image_documentation": "https://caddyserver.com/docs",
    "__meta_docker_container_label_org_opencontainers_image_licenses": "Apache-2.0",
    "__meta_docker_container_label_org_opencontainers_image_source": "https://github.com/caddyserver/caddy-docker",
    "__meta_docker_container_label_org_opencontainers_image_title": "Caddy",
    "__meta_docker_container_label_org_opencontainers_image_url": "https://caddyserver.com",
    "__meta_docker_container_label_org_opencontainers_image_vendor": "Light Code Labs",
    "__meta_docker_container_label_org_opencontainers_image_version": "v2.11.6",
    "__meta_docker_container_label_podhaus_depends_on_fractal_caddy_secrets_init": "b4178238a2798136",
    "__meta_docker_container_label_podhaus_stack_content_hash": "2675855e09803c92",
    "__meta_docker_container_network_mode": "dockernet",
}
# Kept: the labels Compose adds besides project and service, on a container
# in a compose project only.
CAPTURED_COMPOSE = {
    "__meta_docker_container_label_com_docker_compose_config_hash":
        "09dd94e8bd736562d90b637633cf3f5b50ae5aa37eb79f2f620179e9a5d0f336",
    "__meta_docker_container_label_com_docker_compose_container_number": "1",
    "__meta_docker_container_label_com_docker_compose_depends_on":
        "fractal-caddy-secrets-init:service_completed_successfully:false",
    "__meta_docker_container_label_com_docker_compose_image":
        "sha256:86d4376ad067063d998533bf06e0c78b97cc8d99cd7cc66f84393165a95a65ed",
    "__meta_docker_container_label_com_docker_compose_oneoff": "False",
    "__meta_docker_container_label_com_docker_compose_project_config_files":
        "/etc/komodo/repos/podhaus-fractal/caddy/fractal/compose.yaml",
    "__meta_docker_container_label_com_docker_compose_project_environment_file":
        "/etc/komodo/repos/podhaus-fractal/caddy/fractal/.env",
    "__meta_docker_container_label_com_docker_compose_project_working_dir":
        "/etc/komodo/repos/podhaus-fractal/caddy/fractal",
    "__meta_docker_container_label_com_docker_compose_replace": "fractal-caddy",
    "__meta_docker_container_label_com_docker_compose_version": "5.5.0",
}
# Dropped by the first rule: they change when a container stops.
CAPTURED_NETWORK = {
    "__address__": "172.18.0.5:8085",
    "__meta_docker_network_id": "5e7c0a8a0c169a61f1b2cbdf3eebd46b33ce54b77fa76db703c9904b28a1d4e8",
    "__meta_docker_network_ingress": "false",
    "__meta_docker_network_internal": "false",
    "__meta_docker_network_ip": "172.18.0.5",
    "__meta_docker_network_name": "dockernet",
    "__meta_docker_network_scope": "local",
    "__meta_docker_port_private": "8085",
    "__meta_docker_port_public": "8085",
    "__meta_docker_port_public_ip": "127.0.0.1",
}


def docker(container: str, project: str | None = None, compose_service: str | None = None,
           **kwargs: object) -> Docker:
    return Docker(container, project, compose_service, **kwargs)


def compose(container: str, service: str, project: str | None = None, **kwargs: object) -> Docker:
    return Docker(container, project or container, service, **kwargs)


FIXTURES: tuple[Fixture, ...] = (
    # JSON lines: every field arrives under its own name; the body is the message.
    Fixture("caddy_access", compose("testhost-caddy", "caddy"), CADDY_ACCESS,
            Row("caddy", "handled request", "INFO", json_fields(CADDY_ACCESS))),
    Fixture("caddy_remote_access", compose("testhost-caddy", "caddy"), CADDY_REMOTE_ACCESS,
            Row("caddy", "handled request", "INFO", json_fields(CADDY_REMOTE_ACCESS))),
    Fixture("caddy_admin", compose("caddy", "caddy"), CADDY_ADMIN,
            Row("caddy", "received request", "INFO", {
                "level": "info", "ts": 1788960526.0307655, "logger": "admin.api", "msg": "received request",
                "method": "GET", "host": "127.0.0.1:2019", "uri": "/config/", "remote_ip": "127.0.0.1",
                "remote_port": "41234", "headers.Accept-Encoding.0": "gzip",
                "headers.User-Agent.0": "Go-http-client/1.1"})),
    Fixture("pomerium_authorize", compose("pomerium", "pomerium", "numbat-pomerium"), POMERIUM_AUTHORIZE,
            Row("pomerium", "authorize check", "INFO", json_fields(POMERIUM_AUTHORIZE))),
    Fixture("pomerium_callback", compose("pomerium", "pomerium", "numbat-pomerium"), POMERIUM_CALLBACK,
            Row("pomerium", "http-request", "DEBUG", json_fields(POMERIUM_CALLBACK.replace(
                "&state=U3RhbmQtaW4gc3RhdGUgYmxvYg-_fOr9zZ1x%3D", "&state=")))),
    Fixture("pocket_id_authorize", compose("pocket-id", "pocket-id"), POCKET_ID_AUTHORIZE,
            Row("pocket-id", "HTTP request completed", "INFO", json_fields(POCKET_ID_AUTHORIZE))),
    Fixture("flood_request", compose("flood", "flood"), FLOOD_REQUEST,
            Row("flood", "incoming request", "INFO", json_fields(FLOOD_REQUEST))),
    Fixture("flood_request_prefixed", compose("testhost-flood", "flood"), FLOOD_REQUEST,
            Row("flood", "incoming request", "INFO", json_fields(FLOOD_REQUEST))),
    Fixture("rustfs_no_message", compose("rustfs", "rustfs"), RUSTFS_NO_MESSAGE,
            Row("rustfs", RUSTFS_NO_MESSAGE, "ERROR", json_fields(RUSTFS_NO_MESSAGE))),
    Fixture("llm_watcher_resume", compose("llm-watcher", "llm-watcher", "fractal-llm"), LLM_WATCHER_RESUME,
            Row("llm-watcher", "model ready", "INFO",
                json_fields(LLM_WATCHER_RESUME) | {"llm_event": "handoff.resume"})),
    Fixture("llm_watcher_slots", compose("llm-watcher", "llm-watcher", "fractal-llm"), LLM_WATCHER_SLOTS,
            Row("llm-watcher", "slot report changed", "INFO",
                json_fields(LLM_WATCHER_SLOTS) | {"llm_event": "slots.changed"})),
    Fixture("hyperdx_api", compose("hyperdx", "hyperdx", "clickstack"), "[API] " + HYPERDX_JSON,
            Row("hyperdx", "HTTP GET /health slow", "WARN", json_fields(HYPERDX_JSON) | {"component": "API"})),
    Fixture("clickstack_otel", compose("clickstack-otel", "otel-collector", "clickstack"), CLICKSTACK_OTEL,
            Row("clickstack-otel", "Connected to the OpAMP server", "INFO", json_fields(CLICKSTACK_OTEL))),
    Fixture("clickstack_mongo", compose("clickstack-mongo", "db", "clickstack"), CLICKSTACK_MONGO,
            Row("clickstack-mongo", "Connection accepted", "INFO", json_fields(CLICKSTACK_MONGO))),
    Fixture("op_connect_api", compose("op-connect-api", "op-connect-api", "onepassword"), OP_CONNECT_API,
            Row("op-connect-api", "(I) GET /v1/vaults/abc/items completed (200: OK) in 23ms", "INFO",
                json_fields(OP_CONNECT_API))),
    Fixture("op_connect_sync", compose("op-connect-sync", "op-connect-sync", "onepassword"), OP_CONNECT_SYNC,
            Row("op-connect-sync", "(W) ### sync took longer than expected ###", "WARN",
                json_fields(OP_CONNECT_SYNC))),

    # Credentials: removed wherever the word is a dotted part of a key, in any
    # case, and a body rewritten without them when there is no message.
    Fixture("json_password_no_message", docker("probe_password"), JSON_PASSWORD_NO_MESSAGE,
            Row("unmanaged", '{"ok":true,"user":"someone"}', None, {"ok": True, "user": "someone"})),
    Fixture("json_password_nested", docker("probe_password"), JSON_PASSWORD_NESTED,
            Row("unmanaged", "{}", None, {})),
    Fixture("json_cookie_array", docker("probe_cookie"), JSON_COOKIE_ARRAY,
            Row("unmanaged", "{}", None, {})),
    Fixture("json_authorization_object", docker("probe_authorization"), JSON_AUTHORIZATION_OBJECT,
            Row("unmanaged", "request", None, {"msg": "request"})),
    Fixture("json_set_cookie_mixed_case", docker("probe_cookie"), JSON_SET_COOKIE,
            Row("unmanaged", "response", None, {"msg": "response", "status": 200.0})),
    Fixture("json_leading_whitespace", docker("probe_cookie"), "   " + JSON_SET_COOKIE,
            Row("unmanaged", "response", None, {"msg": "response", "status": 200.0})),
    # Lines that only look like one JSON object are left as written.
    Fixture("json_malformed", docker("probe_shape"), JSON_MALFORMED,
            Row("unmanaged", JSON_MALFORMED, None, {})),
    Fixture("json_top_level_array", docker("probe_shape"), JSON_ARRAY,
            Row("unmanaged", JSON_ARRAY, None, {})),
    # A key that appears twice keeps its last value.
    Fixture("json_duplicate_key", docker("probe_shape"), '{"msg":"first","user":"someone","msg":"second"}',
            Row("unmanaged", "second", None, {"msg": "second", "user": "someone"})),
    # Schema names are reserved: a service field spelled like one is discarded.
    Fixture("json_reserved_names", compose("probe-reserved", "probe"),
            '{"msg":"hello","log":{"source":"mine","iostream":"theirs"},"compose.service":"theirs"}',
            Row("probe-reserved", "hello", None, {"msg": "hello"})),
    # ... and a line with no message keeps its JSON body without them, so the
    # collector's own re-parse of the body cannot bring one back.
    Fixture("json_reserved_no_message", docker("probe_reserved"), '{"log":{"source":"x"},"status":200}',
            Row("unmanaged", '{"status":200}', None, {"status": 200.0})),
    # A JSON level field is the level, whatever level word comes earlier in the line.
    Fixture("json_level_field", docker("probe_level"), JSON_LEVEL_FIELD,
            Row("unmanaged", "error budget ok", "INFO", json_fields(JSON_LEVEL_FIELD))),

    # Text lines: the body is the whole line; only the level (and a logger name) is read.
    # llm-server is the exception: its allow-list module stores a known line
    # without the uptime clock and level letter, and promotes its figures.
    Fixture("llm_server_prompt", compose("llm-server", "llm-server", "fractal-llm"), LLM_SERVER_PROMPT,
            Row("llm-server", LLM_SERVER_PROMPT.removeprefix("14.15.016.142 I "), "INFO", {
                "llm_line": "prompt", "llm_slot": "2", "llm_task": "5398", "llm_prompt_tokens": "103"})),
    Fixture("clickstack_clickhouse",
            compose("clickstack-clickhouse", "ch-server", "clickstack"),
            "2026.05.16 12:00:24.261660 [ 747 ] {ebe9491d-1c2b-4c3d-8e4f-5a6b7c8d9e0f} <Debug> default.otel_logs (b1c2d3e4-0000-4000-8000-000000000000): Create MergeTreeSink, deduplicate=false",
            Row("clickstack-clickhouse",
                "2026.05.16 12:00:24.261660 [ 747 ] {ebe9491d-1c2b-4c3d-8e4f-5a6b7c8d9e0f} <Debug> default.otel_logs (b1c2d3e4-0000-4000-8000-000000000000): Create MergeTreeSink, deduplicate=false",
                "DEBUG")),
    Fixture("komodo_op", compose("komodo-op", "komodo-op"),
            "2026/05/16 03:27:18 [INFO] Syncing Komodo secret 'OP__KOMODO__STAND_IN__CREDENTIAL'",
            Row("komodo-op", "2026/05/16 03:27:18 [INFO] Syncing Komodo secret 'OP__KOMODO__STAND_IN__CREDENTIAL'",
                "INFO")),
    Fixture("komodo_core", compose("komodo-core", "core", "komodo"),
            "2026-05-16T03:27:18.601938Z ERROR WriteRequest{req_id=7f2a}: komodo_core::api::write: failed to update stack",
            Row("komodo-core",
                "2026-05-16T03:27:18.601938Z ERROR WriteRequest{req_id=7f2a}: komodo_core::api::write: failed to update stack",
                "ERROR")),
    Fixture("komodo_periphery", compose("testhost-komodo-periphery", "periphery"),
            "2026-05-16T03:33:14.137997Z  WARN periphery: stack compose file missing",
            Row("komodo-periphery", "2026-05-16T03:33:14.137997Z  WARN periphery: stack compose file missing", "WARN")),
    Fixture("komodo_ferretdb", compose("komodo-ferretdb", "ferretdb", "komodo", stream="stderr"), KOMODO_FERRETDB,
            Row("komodo-ferretdb", KOMODO_FERRETDB, "INFO")),
    Fixture("komodo_postgres", compose("komodo-postgres", "postgres", "komodo", stream="stderr"),
            "2026-05-16 03:32:56.677 UTC [81] LOG:  cron job 2 starting: CALL cleanup()",
            Row("komodo-postgres", "2026-05-16 03:32:56.677 UTC [81] LOG:  cron job 2 starting: CALL cleanup()", "INFO")),
    Fixture("umami_postgres", compose("umami-postgres", "postgres", "umami", stream="stderr"),
            "2026-09-09 10:53:54.159 UTC [27] WARNING:  could not open statistics file",
            Row("umami-postgres", "2026-09-09 10:53:54.159 UTC [27] WARNING:  could not open statistics file", "WARN")),
    Fixture("paperless_postgres", compose("paperless-postgres", "postgres", "paperless", stream="stderr"),
            "2026-05-16 03:32:35.729 UTC [26] ERROR:  duplicate key value violates unique constraint",
            Row("paperless-postgres",
                "2026-05-16 03:32:35.729 UTC [26] ERROR:  duplicate key value violates unique constraint", "ERROR")),
    Fixture("alloy_transfer", compose("alloy", "alloy", "fractal-logging"),
            'ts=2026-10-04T10:41:54.820042813Z level=info msg="finished transferring logs" component_path=/podhaus.docker_logs.run component_id=loki.source.docker.containers component=tailer container=docker/7b9087e3129a written=956',
            Row("alloy",
                'ts=2026-10-04T10:41:54.820042813Z level=info msg="finished transferring logs" component_path=/podhaus.docker_logs.run component_id=loki.source.docker.containers component=tailer container=docker/7b9087e3129a written=956',
                "INFO")),
    Fixture("alloy_empty_poll", compose("alloy", "alloy", "fractal-logging"),
            'ts=2026-10-04T10:41:54.820042813Z level=info msg="finished transferring logs" component_path=/podhaus.docker_logs.run component_id=loki.source.docker.containers component=tailer written=0',
            None),
    Fixture("gatus_failure", compose("gatus", "gatus"),
            "2026/05/16 11:33:32 [watchdog.executeEndpoint] Monitored group=core; endpoint=forgejo; key=core_forgejo; success=false; errors=1; duration=12ms",
            Row("gatus",
                "2026/05/16 11:33:32 [watchdog.executeEndpoint] Monitored group=core; endpoint=forgejo; key=core_forgejo; success=false; errors=1; duration=12ms",
                "WARN")),
    Fixture("paperless", compose("paperless", "webserver"),
            "[2026-05-16 11:40:00,000] [WARNING] [celery.beat] Scheduler: Sending due task train_classifier",
            Row("paperless", "[2026-05-16 11:40:00,000] [WARNING] [celery.beat] Scheduler: Sending due task train_classifier",
                "WARN", {"logger": "celery.beat"})),
    Fixture("home_assistant", compose("home-assistant", "home-assistant"),
            "2026-05-16 11:34:52.126 ERROR (MainThread) [homeassistant.components.twinkly.coordinator] Error fetching twinkly data: timeout",
            Row("home-assistant",
                "2026-05-16 11:34:52.126 ERROR (MainThread) [homeassistant.components.twinkly.coordinator] Error fetching twinkly data: timeout",
                "ERROR", {"logger": "homeassistant.components.twinkly.coordinator"})),
    Fixture("autoheal", compose("autoheal", "autoheal"),
            "16-05-2026 04:00:12 Container /gatus (c12cdd3e3339) found to be unhealthy - Restarting container now with 10s timeout",
            Row("autoheal",
                "16-05-2026 04:00:12 Container /gatus (c12cdd3e3339) found to be unhealthy - Restarting container now with 10s timeout",
                "WARN")),
    Fixture("syncthing", compose("testhost-syncthing", "syncthing"),
            '2026-05-16 10:55:05 WRN Failed to sync (path="WORK FOLDERS", error="permission denied")',
            Row("syncthing", '2026-05-16 10:55:05 WRN Failed to sync (path="WORK FOLDERS", error="permission denied")',
                "WARN")),
    Fixture("backrest", compose("backrest", "backrest", "testhost-backup"), BACKREST,
            Row("backrest", BACKREST, "INFO")),
    Fixture("forgejo", compose("forgejo", "forgejo"),
            "2026/09/09 09:28:39 ...eful/manager_unix.go:142:handleSignals() [W] PID 7. Received SIGTERM. Shutting down...",
            Row("forgejo",
                "2026/09/09 09:28:39 ...eful/manager_unix.go:142:handleSignals() [W] PID 7. Received SIGTERM. Shutting down...",
                "WARN")),
    Fixture("rathole_client", compose("testhost-rathole-client", "rathole-client", "testhost-relay"),
            "2026-10-04T05:02:30.518594Z  INFO handle{service=fractal_http}:run: rathole::client: Control channel established",
            Row("rathole-client",
                "2026-10-04T05:02:30.518594Z  INFO handle{service=fractal_http}:run: rathole::client: Control channel established",
                "INFO")),
    Fixture("ofelia", compose("ofelia", "ofelia"),
            'Sep  9 16:56:03.726 ERR Job stop job=sky-cache-invalidate execution=9f9b9facaa3e error="error non-zero exit code: 6" duration=3.717301811s failed=true skipped=false',
            Row("ofelia",
                'Sep  9 16:56:03.726 ERR Job stop job=sky-cache-invalidate execution=9f9b9facaa3e error="error non-zero exit code: 6" duration=3.717301811s failed=true skipped=false',
                "ERROR")),
    Fixture("flood_morgan", compose("flood", "flood"), "GET / 200 3.186 ms - 873",
            Row("flood", "GET / 200 3.186 ms - 873", None)),
    Fixture("hyperdx_boot", compose("hyperdx", "hyperdx", "clickstack"), "> @hyperdx/api@2.0.0 start",
            Row("hyperdx", "> @hyperdx/api@2.0.0 start", None)),

    # The severity fallback in enrich.alloy, for services with no parser.
    Fixture("fallback_column_one", compose("docs", "docs"), 'INFO:     172.18.0.5:41234 - "GET / HTTP/1.1" 200 OK',
            Row("docs", 'INFO:     172.18.0.5:41234 - "GET / HTTP/1.1" 200 OK', "INFO")),
    Fixture("fallback_logfmt", compose("sonarr", "sonarr"), "time=2026-10-04T10:00:00Z level=WARN msg=slow",
            Row("sonarr", "time=2026-10-04T10:00:00Z level=WARN msg=slow", "WARN")),
    Fixture("fallback_first_word", compose("mumble", "mumble"), "[INFO] retrying after error: boom",
            Row("mumble", "[INFO] retrying after error: boom", "INFO")),

    # Containers named for what they are rather than their own names, and what is dropped.
    Fixture("unmanaged", docker("bookcard-feasibility-test"), "### apt update/install base tools",
            Row("unmanaged", "### apt update/install base tools", None)),
    Fixture("forgejo_actions_task", docker("FORGEJO-ACTIONS-TASK-2641-WORKFLOW-17869985454780608328b51104ea"),
            "Run actions/checkout@v4",
            Row("forgejo-actions-task", "Run actions/checkout@v4", None)),
    # Started with plain `docker run`; the compose labels are the Compose-built image's own.
    Fixture("lumen_warm", docker("lumen-warm-8ba490f389676aa9", "lumen", "lumen-tools", docker_labels=(
        ("podhaus_lumen", "true"), ("podhaus_lumen_worktree", "/home/nathan/repos/fenwick-webui"))),
            "Lumen indexed 412 files in 3.1s",
            Row("lumen-warm", "Lumen indexed 412 files in 3.1s", None)),
    Fixture("lumen_search", docker("brave_booth", "lumen", "lumen-tools", docker_labels=(("podhaus_lumen", "true"),)),
            '{"jsonrpc":"2.0","id":1,"result":{"tools":[]}}', None),
    Fixture("fenwick", compose("fenwick", "fenwick"), '{"level":"info","msg":"turn complete"}', None),
    Fixture("indy_service", compose("indy-service", "indy-service", "indy-board"), "device alive", None),
    Fixture("bookbinder_json", compose("bookbinder", "bookbinder", "books"), '{"level":"info","msg":"decoded"}', None),
    Fixture("bookbinder_text", compose("bookbinder", "bookbinder", "books"),
            "listen tcp 0.0.0.0:8080: bind: address already in use",
            Row("bookbinder", "listen tcp 0.0.0.0:8080: bind: address already in use", None)),
    Fixture("bookcard_json", compose("bookcard", "bookcard", "books"), '{"level":"info","msg":"served"}', None),
    Fixture("bookshelf_json", compose("bookshelf", "bookshelf", "books"),
            '{"level":"error","msg":"lookup failed"}', None),

    # The journal.
    Fixture("journal_ssh_login", Journal("sshd", "sshd.service", "sshd-session", "syslog", "6"),
            "Accepted publickey for nathan from 10.0.0.70 port 51234 ssh2: ED25519 SHA256:stand-in",
            Row("journald", "Accepted publickey for nathan from 10.0.0.70 port 51234 ssh2: ED25519 SHA256:stand-in", "INFO")),
    Fixture("journal_sudo", Journal("sudo", "session-4.scope", "sudo", "syslog", "5"),
            "nathan : TTY=pts/1 ; PWD=/home/nathan ; USER=root ; COMMAND=/usr/bin/systemctl restart docker",
            Row("journald", "nathan : TTY=pts/1 ; PWD=/home/nathan ; USER=root ; COMMAND=/usr/bin/systemctl restart docker",
                "INFO")),
    Fixture("journal_earlyoom_kill", Journal("earlyoom", "earlyoom.service", "earlyoom", "stdout", "6"),
            'sending SIGTERM to process 4242 uid 1000 "cc1plus": badness 912, VmRSS 1211 MiB',
            Row("journald", 'sending SIGTERM to process 4242 uid 1000 "cc1plus": badness 912, VmRSS 1211 MiB', "WARN")),
    Fixture("journal_dockerd_error", Journal("docker", "docker.service", "dockerd", "stdout", "6"),
            DOCKERD_ERROR, Row("journald", DOCKERD_ERROR, "ERROR")),
    Fixture("journal_kernel_error", Journal("this", None, "kernel", "kernel", "3"),
            "ieee80211 phy0: brcmf_cfg80211_escan_handler: invalid event data length",
            Row("journald", "ieee80211 phy0: brcmf_cfg80211_escan_handler: invalid event data length", "ERROR")),

    # The file-source modules. Each kept row carries the line's own time.
    Fixture("plex_server_log", File(*PLEX_FILE), PLEX_LINE,
            Row("plex", PLEX_LINE, "DEBUG", timestamp="2026-09-09T23:44:40.556+00:00")),
    Fixture("plex_identity", File(*PLEX_FILE), PLEX_IDENTITY, None),
    Fixture("flood_publish_warn", File(f"{FLOOD_DB}/flood-publish.log", *RTORRENT),
            "[2026-09-09 09:05:00 UTC] WARN: gatus heartbeat push failed: connection refused",
            Row("rtorrent", "[2026-09-09 09:05:00 UTC] WARN: gatus heartbeat push failed: connection refused", "WARN",
                timestamp="2026-09-09T09:05:00+00:00")),
    Fixture("rtorrent_log", File(f"{FLOOD_DB}/rtorrent.log", *RTORRENT),
            "1757408695 W Could not find tracker for announce",
            Row("rtorrent", "1757408695 W Could not find tracker for announce", "WARN",
                timestamp="2025-09-09T09:04:55+00:00")),
    Fixture("rtorrent_extract", File(f"{FLOOD_DB}/rtorrent-extract.log", *RTORRENT),
            "[rtorrent-extract] no archive found under /data/torrents/stand-in — non-rar torrent, nothing to do",
            Row("rtorrent", "[rtorrent-extract] no archive found under /data/torrents/stand-in — non-rar torrent, nothing to do",
                None)),
    Fixture("stignore_heartbeat", File(f"{FLOOD_DB}/pinelake-stignore.log", *RTORRENT),
            "[2026-09-09 09:05:00 UTC] changed=0", None),
    Fixture("clickhouse_error_log", File(*CLICKHOUSE_FILE),
            CLICKHOUSE_ERROR,
            Row("clickstack-clickhouse", CLICKHOUSE_ERROR, "ERROR", timestamp="2026-05-16T04:00:24.261660+00:00")),
)

# clickhouse_error_log tails from the end of its file, so its line is written
# only once the other modules' rows show every tailer has started.
LATE = frozenset({"clickhouse_error_log"})
FILE_ROOT = "/fixtures/files"


# --- What a row must carry ---------------------------------------------------

def expected_service(fixture: Fixture) -> str:
    return fixture.row.service


def expected_resource(fixture: Fixture) -> dict[str, object]:
    source = fixture.source
    resource: dict[str, object] = {"host.name": HOST, "service.name": expected_service(fixture)}
    if isinstance(source, Journal):
        return resource | {"service.instance.id": f"{HOST}/journald"}
    resource |= {"container.name": source.container, "service.instance.id": f"{HOST}/{source.container}"}
    if source.project:
        resource["service.namespace"] = source.project
    return resource


def pipeline_attributes(source: Docker | Journal | File) -> dict[str, object]:
    if isinstance(source, Docker):
        attributes: dict[str, object] = {"log.source": "docker", "log.iostream": source.stream}
        if source.compose_service:
            attributes["compose.service"] = source.compose_service
        return attributes
    if isinstance(source, Journal):
        attributes = {
            "log.source": "journal",
            "journal.identifier": source.identifier,
            "journal.transport": source.transport,
            "journal.priority": source.priority,
            "journal.reader": f"podhaus.journal.run/loki.source.journal.{source.reader}",
        }
        if source.unit:
            attributes["journal.unit"] = source.unit
        return attributes
    path = f"{FILE_ROOT}/{source.path}"
    return {"log.source": path, "log.file.path": path, "log.file.name": Path(path).name,
            "compose.service": source.compose_service}


# --- The Alloy run -------------------------------------------------------------

def alloy(value: object) -> str:
    """A Python value as Alloy syntax: strings, lists and objects of them."""
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(alloy(v) for v in value) + "]"
    return "{" + ", ".join(f"{json.dumps(k)} = {alloy(v)}" for k, v in value.items()) + "}"


def docker_target(fixture: Fixture) -> dict[str, str]:
    source = fixture.source
    target = CAPTURED_CONTAINER | CAPTURED_NETWORK | (CAPTURED_COMPOSE if source.project else {}) | {
        "__path__": f"/fixtures/docker/{fixture.name}.log",
        "__meta_docker_container_name": f"/{source.container}",
        "__meta_docker_container_log_stream": source.stream,
        "fixture": fixture.name,
    }
    if source.project:
        target["__meta_docker_container_label_com_docker_compose_project"] = source.project
    if source.compose_service:
        target["__meta_docker_container_label_com_docker_compose_service"] = source.compose_service
    for name, value in source.docker_labels:
        target[f"__meta_docker_container_label_{name}"] = value
    return target


# What docker_logs' and journal's tailers add to every entry, as deployed.
DOCKER_LABELS = {"host": HOST}
JOURNAL_LABELS = {"host": HOST, "service_name": "journald", "stream": "journal"}


def journal_target(fixture: Fixture) -> dict[str, str]:
    source = fixture.source
    target = {
        "__path__": f"/fixtures/journal/{fixture.name}.log",
        **JOURNAL_LABELS,
        "identifier": source.identifier,
        "transport": source.transport,
        "priority": source.priority,
        "job": f"podhaus.journal.run/loki.source.journal.{source.reader}",
        "fixture": fixture.name,
    }
    if source.unit:
        target["unit"] = source.unit
    return target


def harness_config(fixtures: tuple[Fixture, ...]) -> str:
    docker_targets = [docker_target(f) for f in fixtures if isinstance(f.source, Docker)]
    journal_targets = [journal_target(f) for f in fixtures if isinstance(f.source, Journal)]
    return f"""
logging {{ level = "warn" }}

import.file "podhaus" {{ filename = "/etc/alloy-modules" }}

podhaus.docker_targets "fixtures" {{
  host    = "{HOST}"
  targets = {alloy(docker_targets)}
}}

loki.source.file "docker" {{
  targets    = podhaus.docker_targets.fixtures.output
  forward_to = [loki.process.as_docker.receiver]
}}

loki.process "as_docker" {{
  forward_to = [podhaus.chain.run.receiver]
  stage.label_drop {{ values = ["filename"] }}
  stage.static_labels {{ values = {alloy(DOCKER_LABELS)} }}
  stage.decolorize {{ }}
}}

// Run with nothing to read, so their tailers' labels can be read back.
podhaus.docker_logs "probe" {{
  host       = "{HOST}"
  forward_to = []
}}

podhaus.journal "probe" {{
  host       = "{HOST}"
  forward_to = []
}}

loki.source.file "journal" {{
  targets    = {alloy(journal_targets)}
  forward_to = [loki.process.as_journal.receiver]
}}

loki.process "as_journal" {{
  forward_to = [podhaus.journal_levels.run.receiver]
  stage.label_drop {{ values = ["filename"] }}
}}

podhaus.journal_levels "run" {{
  forward_to = [podhaus.chain.run.receiver]
}}

podhaus.plex_server_log "run" {{
  host            = "{HOST}"
  container       = "{PLEX_FILE[1]}"
  compose_project = "{PLEX_FILE[2]}"
  compose_service = "{PLEX_FILE[3]}"
  logs_dir        = "{FILE_ROOT}/plex"
  timezone        = "America/Edmonton"
  forward_to      = [podhaus.chain.run.receiver]
}}

podhaus.flood_job_logs "run" {{
  host            = "{HOST}"
  container       = "{RTORRENT[0]}"
  compose_project = "{RTORRENT[1]}"
  compose_service = "{RTORRENT[2]}"
  flood_db        = "{FILE_ROOT}/{FLOOD_DB}"
  forward_to      = [podhaus.chain.run.receiver]
}}

podhaus.clickhouse_error_log "run" {{
  host            = "{HOST}"
  container       = "{CLICKHOUSE_FILE[1]}"
  compose_project = "{CLICKHOUSE_FILE[2]}"
  compose_service = "{CLICKHOUSE_FILE[3]}"
  path            = "{FILE_ROOT}/{CLICKHOUSE_FILE[0]}"
  timezone        = "Australia/Perth"
  forward_to      = [podhaus.chain.run.receiver]
}}

podhaus.chain "run" {{
  forward_to = [otelcol.receiver.loki.out.receiver]
}}

otelcol.receiver.loki "out" {{
  output {{ logs = [podhaus.enrich.run.input] }}
}}

podhaus.enrich "run" {{
  host   = "{HOST}"
  output = [otelcol.exporter.file.out.input]
}}

otelcol.exporter.file "out" {{
  path = "/out/logs.jsonl"
}}
"""


def write_fixture_files(root: Path, fixtures: tuple[Fixture, ...]) -> None:
    for fixture in fixtures:
        source = fixture.source
        if isinstance(source, Docker):
            path = root / "docker" / f"{fixture.name}.log"
        elif isinstance(source, Journal):
            path = root / "journal" / f"{fixture.name}.log"
        else:
            path = root / "files" / source.path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as out:
            if fixture.name not in LATE:
                out.write(fixture.line + "\n")


def append_late(root: Path, fixtures: tuple[Fixture, ...]) -> None:
    for fixture in fixtures:
        if fixture.name in LATE:
            with (root / "files" / fixture.source.path).open("a") as out:
                out.write(fixture.line + "\n")


def otlp_value(value: dict[str, object]) -> object:
    """An OTLP JSON AnyValue as a Python value."""
    if not value:
        return None
    ((kind, inner),) = value.items()
    if kind == "intValue":
        return int(inner)
    if kind == "doubleValue":
        return float(inner)
    if kind in ("stringValue", "boolValue"):
        return inner
    raise AssertionError(f"unexpected nested attribute value {value}")


def otlp_map(pairs: list[dict[str, object]]) -> dict[str, object]:
    return {pair["key"]: otlp_value(pair["value"]) for pair in pairs}


def api_value(value: dict[str, object]) -> object:
    """A value as Alloy's HTTP API encodes it, as a Python value."""
    kind, inner = value["type"], value.get("value")
    if kind == "array":
        return [api_value(item) for item in inner]
    if kind == "object":
        return {pair["key"]: api_value(pair["value"]) for pair in inner}
    return inner


def api_fields(fields: list[dict[str, object]]) -> dict[str, object]:
    """A component's arguments, exports or debug info, by name. A repeated block is a list."""
    out: dict[str, object] = {}
    for item in fields:
        value = api_fields(item["body"]) if item["type"] == "block" else api_value(item["value"])
        if item["type"] == "block":
            out.setdefault(item["name"], []).append(value)
        else:
            out[item["name"]] = value
    return out


@dataclass(frozen=True)
class Component:
    arguments: dict[str, object]
    exports: dict[str, object]
    debug: dict[str, object]


@dataclass(frozen=True)
class Shipped:
    resource: dict[str, object]
    attributes: dict[str, object]
    body: str
    severity_text: str | None
    severity_number: int
    time: datetime


def from_nanoseconds(nanoseconds: int) -> datetime:
    seconds, rest = divmod(nanoseconds, 10**9)
    return datetime.fromtimestamp(seconds, timezone.utc).replace(microsecond=rest // 1000)


def read_rows(path: Path) -> list[Shipped]:
    if not path.exists():
        return []
    rows = []
    # Only whole lines: the exporter may be part-way through writing the last.
    for line in path.read_text().split("\n")[:-1]:
        for resource_logs in json.loads(line)["resourceLogs"]:
            resource = otlp_map(resource_logs["resource"].get("attributes", []))
            for scope in resource_logs["scopeLogs"]:
                for record in scope["logRecords"]:
                    rows.append(Shipped(
                        resource=resource,
                        attributes=otlp_map(record.get("attributes", [])),
                        body=record["body"]["stringValue"],
                        severity_text=record.get("severityText"),
                        severity_number=record.get("severityNumber", 0),
                        time=from_nanoseconds(int(record["timeUnixNano"])),
                    ))
    return rows


class AlloyRun:
    """One bounded `grafana/alloy` container running the harness config."""

    def __init__(self, workdir: Path) -> None:
        self.workdir = workdir
        self.name = f"podhaus-log-schema-{os.getpid()}"
        self.process: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        # No log driver: the host's own Alloy would otherwise ship this
        # container's output. Its output still reaches this process. That
        # Alloy still discovers the container and reports it cannot read its
        # logs while it runs; the podhaus.harness label is for a skip rule
        # once the Docker rule list can change (docker-logs.alloy).
        self.process = subprocess.Popen([
            "docker", "run", "--rm", "--log-driver", "none", "--name", self.name,
            "--label", "podhaus.harness=true", "-p", f"127.0.0.1::{API_PORT}",
            "--user", f"{os.getuid()}:{os.getgid()}",
            "-v", f"{MODULES}:/etc/alloy-modules:ro",
            "-v", f"{self.workdir / 'fixtures'}:/fixtures:ro",
            "-v", f"{self.workdir / 'out'}:/out",
            "-v", f"{self.workdir / 'config.alloy'}:/etc/harness/config.alloy:ro",
            "--entrypoint", "timeout", IMAGE, str(RUN_SECONDS),
            "/bin/alloy", "run", "/etc/harness/config.alloy",
            "--storage.path=/tmp/alloy", "--stability.level=public-preview",
            f"--server.http.listen-addr=0.0.0.0:{API_PORT}",
        ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    def component(self, component_id: str) -> Component:
        """One component's evaluated arguments, exports and debug info, from Alloy's HTTP API."""
        port = subprocess.run(["docker", "port", self.name, f"{API_PORT}/tcp"], capture_output=True,
                              text=True, timeout=30, check=True).stdout.split()[0]
        with urllib.request.urlopen(f"http://{port}/api/v0/web/components/{component_id}", timeout=10) as reply:
            detail = json.load(reply)
        return Component(api_fields(detail["arguments"]), api_fields(detail["exports"]),
                         api_fields(detail["debugInfo"]))

    def wait_for_rows(self, count: int, deadline: float) -> list[Shipped]:
        rows = read_rows(self.workdir / "out" / "logs.jsonl")
        while len(rows) < count and time.monotonic() < deadline and self.process.poll() is None:
            time.sleep(0.5)
            rows = read_rows(self.workdir / "out" / "logs.jsonl")
        return rows

    def stop(self) -> str:
        """Stops the container; a daemon that will not stop it fails the run rather than hanging it."""
        if self.process.poll() is None:
            kill = subprocess.run(["docker", "kill", self.name], capture_output=True, timeout=30)
            if kill.returncode != 0 and self.process.poll() is None:
                raise RuntimeError(f"docker kill {self.name} failed: {kill.stderr.decode(errors='replace')}")
        output, _ = self.process.communicate(timeout=30)
        return output.decode(errors="replace")


def docker_unavailable() -> str | None:
    if shutil.which("docker") is None:
        return "the docker command is not installed"
    probe = subprocess.run(["docker", "info"], capture_output=True, timeout=30)
    if probe.returncode != 0:
        return probe.stderr.decode(errors="replace").strip().splitlines()[-1]
    return None


def fixture_of(row: Shipped, by_file_line: dict[tuple[str, str], str]) -> str | None:
    if "fixture" in row.attributes:
        return row.attributes["fixture"]
    return by_file_line.get((row.attributes.get("log.source"), row.body))


# Each tailer and the component that holds its labels, by what it reads.
TAILERS = {
    "docker_rules": "podhaus.docker_targets.fixtures/discovery.relabel.this",
    "docker_probe_rules": "podhaus.docker_logs.probe/docker_targets.this/discovery.relabel.this",
    "docker": "podhaus.docker_logs.probe/loki.source.docker.containers",
    "plex": "podhaus.plex_server_log.run/loki.source.file.this",
    "flood": "podhaus.flood_job_logs.run/loki.source.file.this",
    "clickhouse": "podhaus.clickhouse_error_log.run/loki.source.file.this",
    **{f"journal_{reader}": f"podhaus.journal.probe/loki.source.journal.{reader}"
       for reader in ("this", "sshd", "sudo", "earlyoom", "docker")},
}


class LogSchemaTest(unittest.TestCase):
    rows: dict[str, list[Shipped]]
    unmatched: list[Shipped]
    alloy_output: str
    tailers: dict[str, Component]
    maxDiff = None  # the label pins are long; a failure shows every differing label

    @classmethod
    def setUpClass(cls) -> None:
        reason = docker_unavailable()
        if reason:
            raise unittest.SkipTest(f"Docker is not available ({reason}); the log schema harness needs it")
        cls._tmp = tempfile.TemporaryDirectory(prefix="podhaus-log-schema-")
        workdir = Path(cls._tmp.name)
        (workdir / "out").mkdir()
        write_fixture_files(workdir / "fixtures", FIXTURES)
        (workdir / "config.alloy").write_text(harness_config(FIXTURES))
        kept = [f for f in FIXTURES if f.row is not None]
        run = AlloyRun(workdir)
        run.start()
        try:
            deadline = time.monotonic() + RUN_SECONDS - 10
            run.wait_for_rows(len([f for f in kept if f.name not in LATE]), deadline)
            append_late(workdir / "fixtures", FIXTURES)
            run.wait_for_rows(len(kept), deadline)
            time.sleep(4)  # a dropped line that was not dropped arrives alongside the rest
            cls.tailers = {name: run.component(component_id) for name, component_id in TAILERS.items()}
        finally:
            cls.alloy_output = run.stop()
        by_file_line = {
            (f"{FILE_ROOT}/{f.source.path}", f.line): f.name for f in FIXTURES if isinstance(f.source, File)
        }
        cls.rows = {}
        cls.unmatched = []
        for row in read_rows(workdir / "out" / "logs.jsonl"):
            name = fixture_of(row, by_file_line)
            if name is None:
                cls.unmatched.append(row)
            else:
                cls.rows.setdefault(name, []).append(row)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def only_row(self, fixture: Fixture) -> Shipped:
        rows = self.rows.get(fixture.name, [])
        self.assertEqual(len(rows), 1, f"{fixture.name}: expected one row, got {len(rows)}. "
                                       f"Alloy said:\n{self.alloy_output}")
        return rows[0]

    def test_every_row_belongs_to_a_fixture(self) -> None:
        self.assertEqual(self.unmatched, [], f"rows no fixture accounts for. Alloy said:\n{self.alloy_output}")

    def test_dropped_lines_ship_nothing(self) -> None:
        for fixture in FIXTURES:
            if fixture.row is None:
                with self.subTest(fixture=fixture.name):
                    self.assertNotIn(fixture.name, self.rows)

    def test_resource_is_the_schema(self) -> None:
        for fixture in FIXTURES:
            if fixture.row is not None:
                with self.subTest(fixture=fixture.name):
                    self.assertEqual(self.only_row(fixture).resource, expected_resource(fixture))

    def test_attributes_are_the_pipeline_names_and_the_services_own_fields(self) -> None:
        for fixture in FIXTURES:
            if fixture.row is not None:
                with self.subTest(fixture=fixture.name):
                    attributes = dict(self.only_row(fixture).attributes)
                    attributes.pop("fixture", None)
                    self.assertEqual(attributes, pipeline_attributes(fixture.source) | fixture.row.fields)

    def test_body_is_the_message_or_the_whole_line(self) -> None:
        for fixture in FIXTURES:
            if fixture.row is not None:
                with self.subTest(fixture=fixture.name):
                    self.assertEqual(self.only_row(fixture).body, fixture.row.body)

    def test_severity_is_the_services_own_level(self) -> None:
        for fixture in FIXTURES:
            if fixture.row is not None:
                with self.subTest(fixture=fixture.name):
                    row = self.only_row(fixture)
                    expected = fixture.row.severity
                    self.assertEqual(
                        (row.severity_text, row.severity_number),
                        (expected, SEVERITY_NUMBER[expected]) if expected else (None, 0),
                    )

    def test_a_file_line_keeps_its_own_time(self) -> None:
        for fixture in FIXTURES:
            if fixture.row is not None and fixture.row.timestamp:
                with self.subTest(fixture=fixture.name):
                    self.assertEqual(self.only_row(fixture).time,
                                     datetime.fromisoformat(fixture.row.timestamp))

    def test_credentials_never_reach_a_row(self) -> None:
        for name, rows in self.rows.items():
            for row in rows:
                with self.subTest(fixture=name):
                    self.assertEqual([k for k in row.attributes if denied_parts(k)], [])
                    shipped = [row.body, *map(str, row.attributes.values())]
                    self.assertEqual([s for s in SECRET_VALUES if any(s in text for text in shipped)], [])

    def test_enrich_warns_only_about_the_line_that_is_not_json(self) -> None:
        """A statement that failed on every row would flood Alloy's own log."""
        warnings = [line for line in self.alloy_output.splitlines()
                    if "component_path=/podhaus.enrich.run" in line and ("level=warn" in line or "level=error" in line)]
        self.assertEqual(len(warnings), 1, "\n".join(warnings))
        self.assertIn("ParseJSON", warnings[0])

    # The pins below are what is deployed. A changed label re-reads and
    # re-ships that source's retained logs; a changed Docker rule or tailer
    # argument, reloaded by a running Alloy, re-ships every running
    # container's log. See docs/logging.md before changing one.
    def test_the_docker_relabel_rules_are_the_deployed_list(self) -> None:
        deployed = [
            {"regex": "__address__|__meta_docker_network_.*|__meta_docker_port_.*", "action": "labeldrop"},
            {"source_labels": ["__meta_docker_container_label_podhaus_lumen",
                               "__meta_docker_container_label_podhaus_lumen_worktree"],
             "regex": "true;", "action": "drop"},
            {"source_labels": ["__meta_docker_container_name"], "regex": "/(.*)", "target_label": "container"},
            {"source_labels": ["__meta_docker_container_name"], "regex": "/(?:testhost-)?(.*)",
             "target_label": "service"},
            {"source_labels": ["__meta_docker_container_label_podhaus_lumen_worktree"], "regex": ".+",
             "target_label": "service", "replacement": "lumen-warm"},
            {"source_labels": ["__meta_docker_container_log_stream"], "regex": "(.*)", "target_label": "stream"},
            {"source_labels": ["__meta_docker_container_label_com_docker_compose_project"], "regex": "(.*)",
             "target_label": "compose_project"},
            {"source_labels": ["__meta_docker_container_label_com_docker_compose_service"], "regex": "(.*)",
             "target_label": "compose_service"},
        ]
        for name in ("docker_rules", "docker_probe_rules"):
            with self.subTest(component=TAILERS[name]):
                self.assertEqual(self.tailers[name].arguments["rule"], deployed)

    def test_the_docker_tailers_arguments_are_the_deployed_set(self) -> None:
        arguments = {k: v for k, v in self.tailers["docker"].arguments.items() if k not in ("targets", "forward_to")}
        self.assertEqual(arguments, {
            "host": "unix:///var/run/docker.sock",
            "labels": {"host": "testhost"},
            "relabel_rules": 'capsule("relabel.Rules")',
            "http_client_config": [{}],
        })
        self.assertEqual(self.tailers["docker"].arguments["forward_to"],
                         ["podhaus.docker_logs.probe/loki.process.decolorize.receiver"])

    def docker_tailer_labels(self, fixture: str) -> dict[str, str]:
        """Everything the relabel rules leave on a stand-in, plus the tailer's own labels."""
        stand_in = next(target for target in self.tailers["docker_rules"].exports["output"]
                        if target.get("fixture") == fixture)
        labels = {k: v for k, v in stand_in.items() if k not in ("__path__", "fixture")}
        return labels | self.tailers["docker"].arguments["labels"]

    def test_a_compose_containers_tailer_labels_are_the_deployed_set(self) -> None:
        self.assertEqual(self.docker_tailer_labels("pomerium_authorize"), CAPTURED_CONTAINER | CAPTURED_COMPOSE | {
            "__meta_docker_container_name": "/pomerium",
            "__meta_docker_container_log_stream": "stdout",
            "__meta_docker_container_label_com_docker_compose_project": "numbat-pomerium",
            "__meta_docker_container_label_com_docker_compose_service": "pomerium",
            "host": "testhost", "container": "pomerium", "service": "pomerium", "stream": "stdout",
            "compose_project": "numbat-pomerium", "compose_service": "pomerium",
        })

    def test_a_container_outside_compose_keeps_its_deployed_labels(self) -> None:
        """Its service name comes from enrich, so the tailer still keys it on its own name."""
        self.assertEqual(self.docker_tailer_labels("unmanaged"), CAPTURED_CONTAINER | {
            "__meta_docker_container_name": "/bookcard-feasibility-test",
            "__meta_docker_container_log_stream": "stdout",
            "host": "testhost", "container": "bookcard-feasibility-test",
            "service": "bookcard-feasibility-test", "stream": "stdout",
        })
        task = "FORGEJO-ACTIONS-TASK-2641-WORKFLOW-17869985454780608328b51104ea"
        self.assertEqual(self.docker_tailer_labels("forgejo_actions_task"), CAPTURED_CONTAINER | {
            "__meta_docker_container_name": f"/{task}",
            "__meta_docker_container_log_stream": "stdout",
            "host": "testhost", "container": task, "service": task, "stream": "stdout",
        })

    def test_the_file_tailers_labels_are_the_deployed_set(self) -> None:
        def labels(name: str) -> dict[str, str]:
            return {info["path"]: info["labels"] for info in self.tailers[name].debug["targets_info"]}

        flood = f"{FILE_ROOT}/{FLOOD_DB}"
        self.assertEqual(labels("plex"), {
            f"{FILE_ROOT}/plex/Plex Media Server.log":
                '{container="testhost-plex", host="testhost", log_file="Plex Media Server.log", '
                'service="plex-server-log", stream="file"}',
        })
        self.assertEqual(labels("flood"), {
            f"{flood}/{name}": f'{{container="rtorrent", host="testhost", log_file="{name}", '
                               f'service="flood-jobs", stream="file"}}'
            for name in ("flood-publish.log", "rtorrent.log", "rtorrent-extract.log", "pinelake-stignore.log")
        })
        self.assertEqual(labels("clickhouse"), {
            f"{FILE_ROOT}/clickhouse/clickhouse-server.err.log":
                '{container="clickstack-clickhouse", host="testhost", log_file="clickhouse-server.err.log", '
                'service="clickstack-clickhouse", stream="file"}',
        })

    def test_the_journal_tailers_labels_are_the_deployed_set(self) -> None:
        for reader in ("this", "sshd", "sudo", "earlyoom", "docker"):
            with self.subTest(reader=reader):
                self.assertEqual(self.tailers[f"journal_{reader}"].arguments["labels"],
                                 {"host": "testhost", "service_name": "journald", "stream": "journal"})

    def test_pomeriums_oauth_state_is_removed_and_the_rest_kept(self) -> None:
        row = self.only_row(next(f for f in FIXTURES if f.name == "pomerium_callback"))
        self.assertEqual(
            row.attributes["path"],
            "/oauth2/callback?code=StandInCode0123456789abcdefABCDEF&state=&iss=https%3A%2F%2Fid.pod.haus",
        )

    def test_a_service_field_named_like_a_pipeline_label_keeps_its_own_value(self) -> None:
        caddy = self.only_row(next(f for f in FIXTURES if f.name == "caddy_admin"))
        self.assertEqual((caddy.attributes["host"], caddy.resource["host.name"]), ("127.0.0.1:2019", HOST))
        pomerium = self.only_row(next(f for f in FIXTURES if f.name == "pomerium_authorize"))
        self.assertEqual((pomerium.attributes["service"], pomerium.resource["service.name"]),
                         ("authorize", "pomerium"))
        rustfs = self.only_row(next(f for f in FIXTURES if f.name == "rustfs_no_message"))
        self.assertTrue(rustfs.attributes["filename"].endswith("/s3s-0.16.0/src/service.rs"))

    def test_one_service_on_two_containers_differs_only_in_instance(self) -> None:
        plain = self.only_row(next(f for f in FIXTURES if f.name == "flood_request"))
        prefixed = self.only_row(next(f for f in FIXTURES if f.name == "flood_request_prefixed"))
        self.assertEqual(plain.resource["service.name"], prefixed.resource["service.name"])
        self.assertNotEqual(plain.resource["service.instance.id"], prefixed.resource["service.instance.id"])


if __name__ == "__main__":
    unittest.main()
