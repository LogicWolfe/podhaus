#!/usr/bin/env python3
'''
Lint that no podhaus-tagged stack.toml carries `deploy = true`.

Komodo's RunSync has a built-in "Sync Deploy" sub-stage that auto-deploys
any stack whose stored config differs from deployed when `deploy = true`
is set. That sub-stage:

  - duplicates Stage 2's `BatchDeployStackIfChanged "*"` work
  - runs serially with no per-stack failure tolerance, so a transient
    linked-repo Periphery timeout fails the entire RunSync (Stage 0) and
    aborts Stages 1–3 (bit kookaburra-relay / kookaburra-tailscale on
    2026-05-25)

Per the "deploy authority" architecture, every podhaus stack omits
`deploy` (defaults to false per Komodo source
`client/core/rs/src/entities/toml.rs`). Stage 2 is the sole deploy
authority; first-deploys still work via
`DeployStackIfChanged`'s `(None, _) => FullDeploy` path, which never
reads `stack.config.deploy` (`bin/core/src/api/execute/stack.rs:368-447`).

`vpn-diagnostics` is the only stack that intentionally carries
`deploy = false` (a separate "don't auto-deploy on file change" intent
inherited from the older procedure design — see its stack.toml comment).
That's allowed.

Run from repo root. Exits 1 on offending entries; 0 on clean.
'''
from __future__ import annotations

import sys
import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

# Bootstrap-only compose files outside the podhaus deploy surface.
SKIP_PATH_FRAGMENTS = (
    "kangaroo/periphery",
    "kookaburra/periphery",
)


def is_skipped(path: Path) -> bool:
    s = str(path)
    if ".terraform" in s or "node_modules" in s:
        return True
    return any(frag in s for frag in SKIP_PATH_FRAGMENTS)


def main() -> int:
    errors: list[str] = []
    checked = 0

    for stack_toml in sorted(REPO_ROOT.rglob("stack.toml")):
        rel = stack_toml.relative_to(REPO_ROOT)
        if is_skipped(stack_toml) or "komodo-src" in rel.parts:
            continue

        with open(stack_toml, "rb") as fp:
            data = tomllib.load(fp)

        stacks = data.get("stack", [])
        for s in stacks:
            checked += 1
            tags = s.get("tags", [])
            if "podhaus" not in tags:
                continue
            if s.get("deploy") is True:
                errors.append(
                    f"{rel}: `deploy = true` on a podhaus stack — Komodo's "
                    f"RunSync Sync Deploy sub-stage will auto-deploy it and "
                    f"a single linked-repo Periphery timeout will fail "
                    f"Stage 0. Omit the field (defaults to false); Stage 2 "
                    f"BatchDeployStackIfChanged is the deploy authority. "
                    f"See AGENTS.md Hard Rules."
                )

    if errors:
        print("stack-toml lint: BAD DEPLOY FLAG", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 1

    print(f"stack-toml lint: OK ({checked} stack(s) checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
