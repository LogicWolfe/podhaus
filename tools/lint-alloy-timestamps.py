#!/usr/bin/env python3
'''
Lint that Alloy log parsers leave a container row's time alone.

Every container log line already carries Docker's nanosecond receive
time before any parser runs. A parser that re-reads the time printed in
the line replaces it with a coarser one in whatever zone the container
happens to print, and a module that pins that zone breaks the moment the
service runs on a host with another TZ: Pinelake's Syncthing landed
fourteen hours in the past under a module pinned to Australia/Perth.

So two rules:

  - `stage.timestamp` appears only in the file-source modules listed in
    FILE_SOURCE_MODULES, whose lines carry the only time there is.
  - No `location = "<zone>"` literal anywhere under logging/. A zone
    comes in as an argument from the host config (a literal there for
    Plex, the stack's TZ for ClickHouse). "UTC" is allowed: it is not a
    host's zone but the zone a line itself states (the Flood job logs
    print " UTC").

Comments are ignored, so a module may explain why it has no timestamp
stage. Run from repo root. Exits 1 on offending entries; 0 on clean.
'''
from __future__ import annotations

import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
LOGGING = REPO_ROOT / "logging"
MODULES = LOGGING / "alloy-modules"

FILE_SOURCE_MODULES = frozenset({
    "plex-server-log",
    "flood-job-logs",
    "clickhouse-error-log",
})

TIMESTAMP_STAGE = re.compile(r"\bstage\.timestamp\b")
LOCATION_LITERAL = re.compile(r'\blocation\s*=\s*"([^"]*)"')


def strip_comments(text: str) -> str:
    """Drop `//` and `/* */` comments, leaving string literals intact."""
    out: list[str] = []
    i, n = 0, len(text)
    quote: str | None = None
    while i < n:
        c = text[i]
        if quote:
            out.append(c)
            if c == "\\" and quote == '"' and i + 1 < n:
                out.append(text[i + 1])
                i += 1
            elif c == quote:
                quote = None
        elif c in ('"', "`"):
            quote = c
            out.append(c)
        elif text.startswith("//", i):
            i = text.find("\n", i)
            if i == -1:
                break
            continue
        elif text.startswith("/*", i):
            i = text.index("*/", i) + 2
            continue
        else:
            out.append(c)
        i += 1
    return "".join(out)


def main() -> int:
    errors: list[str] = []
    files = sorted(LOGGING.rglob("*.alloy"))

    for name in sorted(FILE_SOURCE_MODULES):
        if not (MODULES / f"{name}.alloy").is_file():
            errors.append(
                f"FILE_SOURCE_MODULES names {name}, but "
                f"logging/alloy-modules/{name}.alloy does not exist."
            )

    for path in files:
        rel = path.relative_to(REPO_ROOT)
        code = strip_comments(path.read_text())
        if (
            path.parent == MODULES
            and path.stem not in FILE_SOURCE_MODULES
            and TIMESTAMP_STAGE.search(code)
        ):
            errors.append(
                f"{rel}: `stage.timestamp` in a module that is not a file "
                f"source. A container row keeps Docker's nanosecond receive "
                f"time; remove the stage (and the `ts` extraction feeding "
                f"it). Only modules in FILE_SOURCE_MODULES parse a line's time."
            )
        for zone in LOCATION_LITERAL.findall(code):
            if zone != "UTC":
                errors.append(
                    f'{rel}: `location = "{zone}"` pins a time zone. Pass the '
                    f"zone in as an argument from the host config."
                )

    if errors:
        print("alloy-timestamps lint: BAD TIMESTAMP HANDLING", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 1

    print(f"alloy-timestamps lint: OK ({len(files)} Alloy file(s) checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
