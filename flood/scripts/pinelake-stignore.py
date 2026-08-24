#!/usr/bin/env python3
"""Reconcile Pinelake-tagged torrents into four source-side ignore files."""

from __future__ import annotations

import fcntl
import importlib.util
import os
import stat
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path


DATA_ROOT = Path("/data")
SESSION_DIR = Path("/flood-db")
LOG_FILE = SESSION_DIR / "pinelake-stignore.log"
LOCK_FILE = SESSION_DIR / "pinelake-stignore.lock"
WHITELIST_MARKER = "// Selected media: exact !path entries live only in this slice"
DENY_MARKER = "// Deny all unselected content"
TERMINAL_DENY = "**"
SOURCE_MODE_ENV = "PINELAKE_STIGNORE_SOURCE"


class IgnoreContractError(RuntimeError):
    pass


@dataclass(frozen=True)
class Share:
    name: str
    root: Path

    @property
    def ignore_file(self) -> Path:
        return self.root / ".stignore"

    def allow_line(self, published_path: Path) -> str | None:
        try:
            relative = published_path.relative_to(self.root)
        except ValueError:
            return None
        if not relative.parts:
            raise IgnoreContractError(f"refusing broad allow for {self.name}")
        return f"!/{relative.as_posix()}"


class IgnoreFile:
    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            self.lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise IgnoreContractError(f"cannot read {path}: {exc}") from exc
        self.whitelist_index, self.deny_index = self._validate()

    def _single_index(self, value: str) -> int:
        indexes = [index for index, line in enumerate(self.lines) if line == value]
        if len(indexes) != 1:
            raise IgnoreContractError(
                f"{self.path} must contain exactly one {value!r}"
            )
        return indexes[0]

    def _validate(self) -> tuple[int, int]:
        whitelist = self._single_index(WHITELIST_MARKER)
        deny = self._single_index(DENY_MARKER)
        if whitelist >= deny:
            raise IgnoreContractError(f"{self.path} slice markers are out of order")
        if sum(line == TERMINAL_DENY for line in self.lines) != 1:
            raise IgnoreContractError(f"{self.path} must contain one final **")
        meaningful_suffix = [line for line in self.lines[deny + 1 :] if line]
        if meaningful_suffix != [TERMINAL_DENY]:
            raise IgnoreContractError(f"{self.path} final slice is malformed")
        for line in self.lines[whitelist + 1 : deny]:
            if line and not line.startswith("!"):
                raise IgnoreContractError(f"{self.path} whitelist contains {line!r}")
        return whitelist, deny

    def rendered_with(self, additions: set[str]) -> str:
        current = {
            line for line in self.lines[self.whitelist_index + 1 : self.deny_index]
            if line
        }
        whitelist = sorted(current | additions, key=str.casefold)
        before = self.lines[: self.whitelist_index + 1]
        after = self.lines[self.deny_index :]
        middle = [""] if not whitelist else ["", *whitelist, ""]
        return "\n".join([*before, *middle, *after, ""])

    def write(self, content: str) -> bool:
        current = self.path.read_text(encoding="utf-8")
        if current == content:
            return False
        mode = stat.S_IMODE(self.path.stat().st_mode)
        descriptor, temporary_name = tempfile.mkstemp(dir=self.path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, mode)
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
        return True


class IgnoreReconciler:
    def __init__(self, data_root: Path = DATA_ROOT) -> None:
        self.shares = tuple(
            Share(name, data_root / relative)
            for name, relative in (
                ("Movies", "Movies"),
                ("TV", "TV"),
                ("Kids", "Kids"),
                ("Sports", "Sports"),
            )
        )

    def route(self, published_path: str) -> tuple[Share, str]:
        path = Path(published_path)
        for share in self.shares:
            line = share.allow_line(path)
            if line is not None:
                return share, line
        raise IgnoreContractError(f"publish target is outside selected roots: {path}")

    def reconcile(self, published_paths: list[str]) -> int:
        layouts = {share: IgnoreFile(share.ignore_file) for share in self.shares}
        additions: dict[Share, set[str]] = {share: set() for share in self.shares}
        for path in published_paths:
            share, line = self.route(path)
            additions[share].add(line)
        rendered = {
            share: layout.rendered_with(additions[share])
            for share, layout in layouts.items()
        }
        return sum(layouts[share].write(content) for share, content in rendered.items())


def load_rpc():
    script = Path(__file__).with_name("flood-publish.py")
    spec = importlib.util.spec_from_file_location("flood_publish", script)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load flood-publish transport")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.rpc


def parse_tags(value: str) -> set[str]:
    decoded = [urllib.parse.unquote(raw).strip() for raw in value.split(",")]
    return {tag.casefold() for tag in decoded if tag}


def selected_publish_paths() -> list[str]:
    rows = load_rpc()(
        "d.multicall2",
        "",
        "main",
        "d.complete=",
        "d.custom1=",
        "d.custom=publishdir",
        "d.directory=",
    )
    selected = []
    for complete, custom1, publishdir, directory in rows:
        if int(complete) == 1 and "pinelake" in parse_tags(custom1):
            selected.append(publishdir or directory)
    return sorted(set(selected), key=str.casefold)


def log(message: str) -> None:
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S %Z')}] {message}", flush=True)


def heartbeat() -> None:
    token = os.environ.get("GATUS_OFELIA_PUSH_TOKEN")
    if not token:
        return
    base_url = os.environ["GATUS_BASE_URL"].rstrip("/")
    endpoint_id = os.environ["GATUS_STIGNORE_ENDPOINT_ID"]
    request = urllib.request.Request(
        f"{base_url}/api/v1/endpoints/{endpoint_id}/external?success=true",
        data=b"",
        method="POST",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=10):
        pass


def run() -> None:
    source_mode = os.environ.get(SOURCE_MODE_ENV)
    if source_mode == "false":
        return
    if source_mode != "true":
        raise IgnoreContractError(
            f"{SOURCE_MODE_ENV} must be explicitly true or false"
        )
    with LOCK_FILE.open("w", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        changed = IgnoreReconciler().reconcile(selected_publish_paths())
    log(f"reconciled four source ignore files; changed={changed}")
    heartbeat()


def main() -> int:
    try:
        with LOG_FILE.open("a", encoding="utf-8") as stream:
            sys.stdout = stream
            sys.stderr = stream
            run()
    except Exception as exc:
        log(f"ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
