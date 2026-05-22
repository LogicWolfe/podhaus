#!/usr/bin/env python3
'''
Lint every <stack>/stack.toml's `environment` block against the matching
compose file(s) to catch the documented two-place footgun: a Komodo-side
env declaration that's never referenced in the compose's service
`environment:` map renders empty (silent auth/empty-value failures).

Bit logging/compose.shared.yaml (CLICKSTACK_INGESTION_KEY) and
gatus/compose.yaml (CLICKHOUSE_PASSWORD) already. Generalised here so
the hook catches the next one mechanically instead of waiting for a
container to crash-loop.

Run from repo root. Exits 1 on mismatch (with a diagnostic on stderr);
0 on clean. Designed for use as a git pre-commit hook.
'''
from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
# stack.toml env line: KEY=[[VAR]] or KEY=${...} or KEY=literal
ENV_KEY_RE = re.compile(r"^([A-Z_][A-Z0-9_]*)\s*=")


def parse_env_keys(env_block: str) -> list[str]:
    keys: list[str] = []
    for line in env_block.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = ENV_KEY_RE.match(line)
        if m:
            keys.append(m.group(1))
    return keys


def resolve_compose_files(stack_dir: Path, file_paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for fp in file_paths:
        p = (stack_dir / fp).resolve()
        if p.exists():
            out.append(p)
    return out


def key_referenced(key: str, content: str) -> bool:
    '''Return True if `key` is referenced in `content` by any Compose
    env-reference syntax: ${KEY}, ${KEY:-default}, ${KEY-default},
    ${KEY:?error}, ${KEY?error}, ${KEY:+value}, ${KEY+value}, or as
    a project-env config source (e.g. `environment: KEY`).

    Also accepts `KEY:` followed by `${KEY}` later (the common
    `KEY: ${KEY}` pattern), and bare `- KEY` list-style env reference.
    '''
    # ${KEY} or ${KEY:-default} / ${KEY-default} / ${KEY:?err} / ${KEY?err} / ${KEY:+x} / ${KEY+x}
    if re.search(r"\$\{" + re.escape(key) + r"(?:[:?\-+}]|\})", content):
        return True
    # Compose `environment: KEY` (single-value form: env var is sourced from project env)
    if re.search(r"^\s*environment:\s*" + re.escape(key) + r"\s*$", content, re.MULTILINE):
        return True
    # YAML list form: `- KEY` (no value -> sourced from project env)
    if re.search(r"^\s*-\s+" + re.escape(key) + r"\s*$", content, re.MULTILINE):
        return True
    return False


def main() -> int:
    errors: list[str] = []
    checked = 0

    for stack_toml in sorted(REPO_ROOT.rglob("stack.toml")):
        rel = stack_toml.relative_to(REPO_ROOT)
        # Skip non-stack paths defensively
        if rel.parts[0] in {"docs", ".git", "node_modules"}:
            continue
        # Skip the Komodo source clone if present (verifications)
        if "komodo-src" in rel.parts:
            continue

        with open(stack_toml, "rb") as f:
            data = tomllib.load(f)

        for stack in data.get("stack", []):
            cfg = stack.get("config", {})
            env_block = cfg.get("environment", "").strip()
            if not env_block:
                continue

            keys = parse_env_keys(env_block)
            if not keys:
                continue

            file_paths = cfg.get("file_paths", ["compose.yaml"])
            compose_files = resolve_compose_files(stack_toml.parent, file_paths)
            if not compose_files:
                errors.append(
                    f"{rel}: stack declares env vars but no compose file resolves "
                    f"(file_paths={file_paths})"
                )
                continue

            content = "\n".join(p.read_text() for p in compose_files)
            for key in keys:
                if not key_referenced(key, content):
                    files_str = ", ".join(
                        str(p.relative_to(REPO_ROOT)) for p in compose_files
                    )
                    errors.append(
                        f"{rel}: env declares {key} but never referenced "
                        f"in {files_str}"
                    )
            checked += 1

    if errors:
        print("stack-env lint: MISMATCHES", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        print(
            "\nFix: either add the variable to the service's `environment:` "
            "block in compose, or remove the declaration from stack.toml.",
            file=sys.stderr,
        )
        return 1

    print(f"stack-env lint: OK ({checked} stack(s) checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
