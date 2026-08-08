"""Surface Pomerium's pending SSH sign-in codes as fenwick events.

Pomerium delivers the SSH sign-in URL only through the keyboard-interactive
channel, which headless clients never see. The code is also the databroker
record id for session.SessionBindingRequest, so a Sync stream on that type
yields every pending authentication. The target route is not in the record;
it appears in Pomerium's debug log line "ssh keyboard-interactive auth
request", emitted just before the record write, so a docker-log follower
keeps a fingerprint-keyed context map the record handler joins against.

Person-shaped decisions stay in configuration: FENWICK_USER_BY_FINGERPRINT
maps each key fingerprint to the fenwick account that owns the machine
(fenwick routes delivery by the X-Fenwick-User header), with unmapped keys
falling back to FENWICK_DEFAULT_USER. Delivery is at-most-once by design —
fenwick derives event ids server-side, so a retry would mean a duplicate
Signal message.
"""

import base64
import json
import logging
import os
import threading
import time

import docker
import grpc
import jwt
import requests

import databroker_pb2
import databroker_pb2_grpc
import session_pb2

SBR_TYPE = "type.googleapis.com/session.SessionBindingRequest"
FINGERPRINT_PREFIX = "sshkey-SHA256:"
ROUTE_LOG_MESSAGE = "ssh keyboard-interactive auth request"
# The log line strictly precedes the record write, so the join normally hits
# on the first attempt; the retries only cover log-stream scheduling jitter.
ROUTE_JOIN_ATTEMPTS = 20
ROUTE_JOIN_DELAY_S = 0.1
ROUTE_CONTEXT_TTL_S = 600

log = logging.getLogger("ssh-auth-notify")

STATE_NAMES = {
    session_pb2.InFlight: "in_flight",
    session_pb2.Accepted: "accepted",
    session_pb2.Revoked: "revoked",
}


def require_env(name):
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"missing required environment variable {name}")
    return value


def load_config():
    return {
        "databroker_addr": os.environ.get("DATABROKER_ADDR", "127.0.0.1:5443"),
        "authenticate_url": require_env("AUTHENTICATE_URL").rstrip("/"),
        "shared_key": base64.b64decode(require_env("SHARED_SECRET")),
        "fenwick_url": require_env("FENWICK_EVENT_URL"),
        "gateway_token": require_env("FENWICK_GATEWAY_TOKEN"),
        "event_token": require_env("FENWICK_EVENT_TOKEN"),
        "default_user": require_env("FENWICK_DEFAULT_USER"),
        "owners": json.loads(require_env("FENWICK_USER_BY_FINGERPRINT")),
        "pomerium_container": os.environ.get("POMERIUM_CONTAINER", "pomerium"),
    }


class RouteContext:
    """Fingerprint-keyed route/username context from Pomerium's debug logs."""

    def __init__(self):
        self._lock = threading.Lock()
        self._by_fingerprint = {}

    def put(self, fingerprint, username, hostname):
        with self._lock:
            self._by_fingerprint[fingerprint] = {
                "username": username,
                "hostname": hostname,
                "at": time.monotonic(),
            }

    def get(self, fingerprint):
        with self._lock:
            entry = self._by_fingerprint.get(fingerprint)
        if entry and time.monotonic() - entry["at"] < ROUTE_CONTEXT_TTL_S:
            return entry
        return None


def follow_pomerium_logs(container_name, context):
    client = docker.from_env()
    container = client.containers.get(container_name)
    stream = container.logs(stream=True, follow=True, since=int(time.time()))
    for raw_line in stream:
        line = parse_log_line(raw_line)
        if line is None or line.get("message") != ROUTE_LOG_MESSAGE:
            continue
        fingerprint = line.get("publickey-fingerprint")
        if not fingerprint:
            continue
        context.put(fingerprint, line.get("username"), line.get("hostname"))
        log.info(
            "route context: %s -> %s@%s",
            fingerprint,
            line.get("username"),
            line.get("hostname"),
        )


def parse_log_line(raw_line):
    try:
        return json.loads(raw_line)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def log_follower_thread(container_name, context):
    # The follow stream ends whenever the pomerium container is recreated
    # (every deploy); reattach rather than treating that as fatal.
    while True:
        try:
            follow_pomerium_logs(container_name, context)
            log.warning("pomerium log stream ended; reattaching")
        except docker.errors.DockerException as exc:
            log.warning("pomerium log stream error (%s); reattaching", exc)
        time.sleep(2)


def signed_metadata(shared_key):
    token = jwt.encode({"exp": int(time.time()) + 3600}, shared_key, algorithm="HS256")
    return (("jwt", token),)


def sync_latest(stub, shared_key):
    """One SyncLatest pass: returns (records, server_version, record_version)."""
    records = []
    versions = None
    request = databroker_pb2.SyncLatestRequest(type=SBR_TYPE)
    for response in stub.SyncLatest(request, metadata=signed_metadata(shared_key)):
        kind = response.WhichOneof("response")
        if kind == "record":
            records.append(response.record)
        elif kind == "versions":
            versions = response.versions
    if versions is None:
        raise RuntimeError("SyncLatest stream ended without a versions message")
    return records, versions.server_version, versions.latest_record_version


def unpack_binding_request(record):
    binding = session_pb2.SessionBindingRequest()
    if not record.data.Unpack(binding):
        raise RuntimeError(f"record {record.id} data is not a SessionBindingRequest")
    return binding


class EventForwarder:
    """Joins records with route context and posts normalized fenwick events."""

    def __init__(self, config, context):
        self.config = config
        self.context = context
        self._seen_states = {}

    def handle_record(self, record, initial):
        binding = unpack_binding_request(record)
        if binding.protocol != "ssh":
            return
        if record.HasField("deleted_at"):
            self._seen_states.pop(record.id, None)
            return
        state = STATE_NAMES.get(binding.state, str(binding.state))
        if self._seen_states.get(record.id) == state:
            return
        self._seen_states[record.id] = state
        if initial and self.is_stale(binding):
            return
        self.forward(record.id, binding, state)

    def is_stale(self, binding):
        return binding.expires_at.ToDatetime().timestamp() < time.time()

    def forward(self, user_code, binding, state):
        fingerprint = "SHA256:" + binding.key.removeprefix(FINGERPRINT_PREFIX)
        owner = self.config["owners"].get(fingerprint)
        route = None
        if state == "in_flight":
            route = self.wait_for_route(fingerprint.removeprefix("SHA256:"))
        payload = {
            "state": state,
            "userCode": user_code,
            "url": f"{self.config['authenticate_url']}/.pomerium/sign_in"
            f"?user_code={user_code}",
            "fingerprint": fingerprint,
            "machine": owner["machine"] if owner else None,
            "sourceAddr": binding.details.get("Source Address"),
            "route": route["hostname"] if route else None,
            "username": route["username"] if route else None,
            "expiresAt": binding.expires_at.ToJsonString(),
        }
        user = owner["user"] if owner else self.config["default_user"]
        self.post(user, payload)

    def wait_for_route(self, fingerprint):
        for _ in range(ROUTE_JOIN_ATTEMPTS):
            entry = self.context.get(fingerprint)
            if entry:
                return entry
            time.sleep(ROUTE_JOIN_DELAY_S)
        log.warning("no route context for fingerprint %s", fingerprint)
        return None

    def post(self, user, payload):
        # At-most-once: a missed notification must not kill the stream or be
        # retried into a duplicate Signal message; log loudly instead.
        try:
            response = requests.post(
                self.config["fenwick_url"],
                json={"type": "pomerium_ssh_auth", "payload": payload},
                headers={
                    "X-Podhaus-Gateway-Token": self.config["gateway_token"],
                    "Authorization": f"Bearer {self.config['event_token']}",
                    "X-Fenwick-User": user,
                },
                timeout=10,
            )
            response.raise_for_status()
            log.info(
                "forwarded %s %s to %s (machine=%s route=%s)",
                payload["state"],
                payload["userCode"],
                user,
                payload["machine"],
                payload["route"],
            )
        except requests.RequestException as exc:
            log.error("fenwick post failed for %s: %s", payload["userCode"], exc)


def sync_loop(config, forwarder):
    channel = grpc.insecure_channel(config["databroker_addr"])
    stub = databroker_pb2_grpc.DataBrokerServiceStub(channel)
    shared_key = config["shared_key"]
    while True:
        try:
            records, server_version, record_version = sync_latest(stub, shared_key)
            for record in records:
                forwarder.handle_record(record, initial=True)
            request = databroker_pb2.SyncRequest(
                server_version=server_version,
                record_version=record_version,
                type=SBR_TYPE,
                wait=True,
            )
            for response in stub.Sync(request, metadata=signed_metadata(shared_key)):
                if response.WhichOneof("response") == "record":
                    forwarder.handle_record(response.record, initial=False)
        except grpc.RpcError as exc:
            # ABORTED means our versions are stale; anything else is likely a
            # pomerium restart. Both recover through a fresh SyncLatest.
            log.warning("databroker stream error (%s); resyncing", exc.code())
            time.sleep(2)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config()
    context = RouteContext()
    threading.Thread(
        target=log_follower_thread,
        args=(config["pomerium_container"], context),
        daemon=True,
    ).start()
    sync_loop(config, EventForwarder(config, context))


if __name__ == "__main__":
    main()
