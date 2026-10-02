#!/usr/bin/env python3
"""Prints a sign-in token for llm.pod.haus, signing in through Pocket ID when needed.

The token is a Pocket ID access token. Pomerium checks it on every request to
llm.pod.haus and lets in members of Pocket ID's family and friends groups. A
first run starts Pocket ID's device sign-in: it prints one link with the code
already in it, opens it when this machine has a browser on its own screen, and
waits while the link is approved on any device. Later runs return the cached
token, renew it silently with the refresh token, or print a fresh link when the
refresh token is no longer accepted.

pi runs this for every request and Claude Code runs it when a request is
refused, so the token is the only thing written to stdout. The link and any
failure go to stderr, and a failure exits non-zero.

Standard library only, so the file can be copied to any Linux or macOS machine
and run with python3 as it is.
"""

from __future__ import annotations

import contextlib
import dataclasses
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Callable, Iterator, Mapping, Protocol, Sequence, TextIO
import urllib.error
import urllib.parse
import urllib.request

ISSUER = "https://id.pod.haus"
# The public Pocket ID client declared in podhaus's terraform/pocket_id.tf.
CLIENT_ID = "llm-token"
# email and groups put the person's address and group names in what Pocket ID's
# userinfo endpoint returns for this token, which is what Pomerium reads.
SCOPE = "openid email groups"
DEVICE_CODE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
# Pocket ID's access tokens last an hour. Renewing ten minutes early means a
# token Claude Code holds in its five-minute key cache is still valid when used.
RENEW_BEFORE_EXPIRY_SECONDS = 600
# RFC 8628: each slow_down answer adds five seconds to the polling interval.
SLOW_DOWN_STEP_SECONDS = 5
HTTP_TIMEOUT_SECONDS = 30


class TokenUnavailable(Exception):
    """No token could be produced; the message says why, for the person."""


class Clock(Protocol):
    def now(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def now(self) -> float:
        return time.time()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


@dataclasses.dataclass(frozen=True)
class Token:
    access_token: str
    refresh_token: str
    expires_at: float  # Unix seconds

    @classmethod
    def from_reply(cls, body: dict, now: float) -> Token:
        return cls(body["access_token"], body["refresh_token"], now + body["expires_in"])

    def fresh_at(self, now: float) -> bool:
        return self.expires_at - now > RENEW_BEFORE_EXPIRY_SECONDS


@dataclasses.dataclass(frozen=True)
class DeviceSignIn:
    device_code: str
    link: str
    interval: float
    expires_at: float


@dataclasses.dataclass(frozen=True)
class Reply:
    status: int
    body: dict

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


@dataclasses.dataclass(frozen=True)
class Endpoints:
    device_authorization: str
    token: str


class TokenCache:
    """The token file, and the lock that lets one run at a time replace it.

    Pocket ID issues a new refresh token on every renewal and refuses the old
    one, so two runs renewing at once would leave one of them refused and
    asking the person to sign in again for nothing.
    """

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self.token_file = directory / "token.json"

    @contextlib.contextmanager
    def locked(self) -> Iterator[None]:
        self._directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        with open(self._directory / "lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def load(self) -> Token | None:
        try:
            text = self.token_file.read_text()
        except FileNotFoundError:
            return None
        try:
            return Token(**json.loads(text))
        except json.JSONDecodeError:
            raise TokenUnavailable(f"{self.token_file}: damaged") from None

    def save(self, token: Token) -> None:
        """Replaces the token file so that a power loss leaves the old file or
        the new one, never an empty one. Pocket ID has already spent the old
        refresh token, so the directory is synced too: a lost rename would cost
        a needless sign-in."""
        self._directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        staging = self.token_file.with_suffix(".tmp")
        descriptor = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as staged:
            json.dump(dataclasses.asdict(token), staged)
            staged.flush()
            os.fsync(staged.fileno())
        os.replace(staging, self.token_file)
        directory = os.open(self._directory, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


class PocketID:
    """Pocket ID's device sign-in and refresh grants, for one public client."""

    def __init__(self, issuer: str, client_id: str, clock: Clock) -> None:
        self._issuer = issuer
        self._client_id = client_id
        self._clock = clock
        self._discovered: Endpoints | None = None

    def renew(self, refresh_token: str) -> Token | None:
        """A new token, or None when Pocket ID no longer accepts the refresh token."""
        reply = self._post(self._endpoints().token, {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self._client_id,
        })
        if not reply.ok:
            return None
        return Token.from_reply(reply.body, self._clock.now())

    def start_sign_in(self) -> DeviceSignIn:
        reply = self._post(self._endpoints().device_authorization, {
            "client_id": self._client_id,
            "scope": SCOPE,
        })
        if not reply.ok:
            raise TokenUnavailable(reply.body["error"])
        return DeviceSignIn(
            device_code=reply.body["device_code"],
            link=reply.body["verification_uri_complete"],
            interval=reply.body["interval"],
            expires_at=self._clock.now() + reply.body["expires_in"],
        )

    def finish_sign_in(self, sign_in: DeviceSignIn) -> Token:
        """Waits until the link is approved, polling as RFC 8628 prescribes."""
        interval = sign_in.interval
        while True:
            self._clock.sleep(interval)
            if self._clock.now() >= sign_in.expires_at:
                raise TokenUnavailable("expired")
            reply = self._post(self._endpoints().token, {
                "grant_type": DEVICE_CODE_GRANT,
                "device_code": sign_in.device_code,
                "client_id": self._client_id,
            })
            if reply.ok:
                return Token.from_reply(reply.body, self._clock.now())
            error = reply.body["error"]
            if error == "slow_down":
                interval += SLOW_DOWN_STEP_SECONDS
            elif error != "authorization_pending":
                raise TokenUnavailable(error)

    def _endpoints(self) -> Endpoints:
        if self._discovered is None:
            url = self._issuer + "/.well-known/openid-configuration"
            with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT_SECONDS) as response:
                document = json.load(response)
            self._discovered = Endpoints(
                device_authorization=document["device_authorization_endpoint"],
                token=document["token_endpoint"],
            )
        return self._discovered

    def _post(self, url: str, form: dict[str, str]) -> Reply:
        """Pocket ID's answer, refusals included. A server error is raised:
        Pocket ID failing is not a reason to ask the person to sign in again."""
        request = urllib.request.Request(
            url,
            data=urllib.parse.urlencode(form).encode(),
            headers={"Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                return Reply(response.status, json.load(response))
        except urllib.error.HTTPError as refusal:
            with refusal:
                if refusal.code >= 500:
                    raise
                return Reply(refusal.code, json.load(refusal))


class LinkPresenter:
    """Puts the sign-in link in front of the person: always printed, and also
    opened when this machine has a browser on its own screen.

    The opener is not waited for: xdg-open can stay attached to a browser it
    started, and the sign-in must not wait on that. Its process is kept in
    `opened` for any caller that outlives it.
    """

    def __init__(self, stream: TextIO, opener: Sequence[str] | None) -> None:
        self._stream = stream
        self._opener = opener
        self.opened: subprocess.Popen[bytes] | None = None

    def show(self, link: str) -> None:
        print(link, file=self._stream, flush=True)
        if self._opener is not None:
            self.opened = subprocess.Popen(
                [*self._opener, link],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )


class TokenCommand:
    """A usable token: the cached one, a silently renewed one, or a new sign-in's."""

    def __init__(self, cache: TokenCache, pocket_id: PocketID, presenter: LinkPresenter, clock: Clock) -> None:
        self._cache = cache
        self._pocket_id = pocket_id
        self._presenter = presenter
        self._clock = clock

    def token(self) -> str:
        with self._cache.locked():
            cached = self._cache.load()
            if cached is not None and cached.fresh_at(self._clock.now()):
                return cached.access_token
            token = self._renewed(cached) or self._signed_in()
            self._cache.save(token)
            return token.access_token

    def _renewed(self, cached: Token | None) -> Token | None:
        if cached is None:
            return None
        return self._pocket_id.renew(cached.refresh_token)

    def _signed_in(self) -> Token:
        sign_in = self._pocket_id.start_sign_in()
        self._presenter.show(sign_in.link)
        return self._pocket_id.finish_sign_in(sign_in)


def browser_opener(platform: str, environ: Mapping[str, str], which: Callable[[str], str | None]) -> list[str] | None:
    """The command that opens a link on this machine's own screen, or None.

    Over SSH any screen belongs to the far end. Only a graphical opener counts:
    a console browser would take over the terminal that a tool is reading.
    """
    if "SSH_CONNECTION" in environ:
        return None
    if platform == "darwin":
        return ["open"]
    if platform.startswith("linux") and ("DISPLAY" in environ or "WAYLAND_DISPLAY" in environ):
        opener = which("xdg-open")
        return None if opener is None else [opener]
    return None


def state_directory(environ: Mapping[str, str]) -> Path:
    """XDG's state directory, which the specification places at ~/.local/state
    when XDG_STATE_HOME is unset or empty."""
    base = environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "llm-token"


def main() -> int:
    clock = SystemClock()
    command = TokenCommand(
        cache=TokenCache(state_directory(os.environ)),
        pocket_id=PocketID(ISSUER, CLIENT_ID, clock),
        presenter=LinkPresenter(sys.stderr, browser_opener(sys.platform, os.environ, shutil.which)),
        clock=clock,
    )
    try:
        token = command.token()
    except (TokenUnavailable, urllib.error.URLError) as failure:
        print(failure, file=sys.stderr)
        return 1
    print(token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
