#!/usr/bin/env python3
'''
Lint that every podhaus-managed compose service correctly depends on
the procedure-time-injected per-service content hashes.

The consumer side of the podhaus content-hash mechanism (see AGENTS.md
"Content-hash change detection"). The producer side — the Action that
populates STACK_CONTENT_HASH + per-service BUILD_HASH_<svc> in each
stack's stored env — is guaranteed by the procedure, not by lint.

Three checks per compose:

1. Every service has a `podhaus.stack-content-hash` label referencing
   `${STACK_CONTENT_HASH:-unset}` (or any default). The label is
   tracked in docker compose's per-service config hash; its
   substituted value changing forces a recreate. This catches any
   in-stack-dir change uniformly.

2. Every service with a `build:` directive additionally has
   `build.args.STACK_CONTENT_HASH` referencing `${BUILD_HASH_<SELF>...}`
   (the per-service variable, where <SELF> is the service name
   uppercased with non-alphanumerics → `_`), AND the Dockerfile at the
   resolved build context declares `ARG STACK_CONTENT_HASH` and
   propagates it. The ARG/ENV-from-ARG pair busts docker's build-layer
   cache when the per-service hash changes — without it, a Dockerfile
   or build-context edit produces the same image because the cache
   is reused.

3. Every service that `depends_on` a service with `build:` has a
   `podhaus.depends-on-<dep>` label referencing the dependent's
   `${BUILD_HASH_<DEP>...}`. Otherwise the depender won't recreate
   when the dependent's build context changes (its own
   `podhaus.stack-content-hash` only tracks the depender's stack dir,
   which may not include the dependent's build context — e.g. shared
   build images like init-tools/).

Run from repo root. Exits 1 on missing wiring (diagnostic on stderr);
0 on clean. Designed for use as a git pre-commit hook (see
tools/pre-commit).
'''
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent

LABEL_KEY = "podhaus.stack-content-hash"
DEPENDS_LABEL_PREFIX = "podhaus.depends-on-"

# Any ${SOME_VAR...} reference where SOME_VAR is the given name.
def _interp_re(varname: str) -> re.Pattern[str]:
    return re.compile(r"\$\{" + re.escape(varname) + r"(?:[:?\-+}]|\})")


# Compose files outside the podhaus deploy surface (bootstrap-only,
# not Komodo-managed by the podhaus sync).
SKIP_PATH_FRAGMENTS = (
    "kangaroo/periphery",
    "kookaburra/periphery",
)


def is_skipped(path: Path) -> bool:
    s = str(path)
    if ".terraform" in s or "node_modules" in s:
        return True
    return any(frag in s for frag in SKIP_PATH_FRAGMENTS)


def env_safe(svc: str) -> str:
    """Mirror of the Action's `envSafeName`: uppercase + non-alnum → _."""
    return re.sub(r"[^A-Z0-9]", "_", svc.upper())


def label_value(labels, key: str) -> str | None:
    """Extract a label's value from compose's map-or-list-of-strings form."""
    if isinstance(labels, dict):
        v = labels.get(key)
        return v if isinstance(v, str) else None
    if isinstance(labels, list):
        for item in labels:
            if not isinstance(item, str) or "=" not in item:
                continue
            k, _, v = item.partition("=")
            if k.strip() == key:
                return v
    return None


def label_keys(labels) -> list[str]:
    if isinstance(labels, dict):
        return list(labels.keys())
    if isinstance(labels, list):
        out = []
        for item in labels:
            if isinstance(item, str) and "=" in item:
                k, _, _ = item.partition("=")
                out.append(k.strip())
        return out
    return []


def build_args_value(build, arg_name: str) -> str | None:
    """Extract a build-arg's value from compose's map-or-list-of-strings form."""
    if not isinstance(build, dict):
        return None
    args = build.get("args")
    if isinstance(args, dict):
        v = args.get(arg_name)
        return v if isinstance(v, str) else None
    if isinstance(args, list):
        for item in args:
            if not isinstance(item, str) or "=" not in item:
                continue
            k, _, v = item.partition("=")
            if k.strip() == arg_name:
                return v
    return None


def resolve_dockerfile(compose_path: Path, service: dict) -> Path | None:
    build = service.get("build")
    if isinstance(build, str):
        context = Path(build)
        dockerfile_name = "Dockerfile"
    elif isinstance(build, dict):
        context = Path(build.get("context", "."))
        dockerfile_name = build.get("dockerfile", "Dockerfile")
    else:
        return None
    base = compose_path.parent / context
    return (base / dockerfile_name).resolve()


def dockerfile_has_arg_propagation(dockerfile: Path) -> bool:
    try:
        text = dockerfile.read_text()
    except OSError:
        return False
    has_arg = re.search(
        r"^\s*ARG\s+STACK_CONTENT_HASH(?:=|\s|$)", text, re.MULTILINE
    ) is not None
    uses_arg = re.search(
        r"\$\{?STACK_CONTENT_HASH(?:[}:?\-+]|\b)", text
    ) is not None
    return has_arg and uses_arg


def depends_on_services(service: dict) -> list[str]:
    """Extract dependent service names from a service's depends_on field.
    depends_on can be a list (short form) or a map (long form)."""
    dep = service.get("depends_on")
    if dep is None:
        return []
    if isinstance(dep, list):
        return [d for d in dep if isinstance(d, str)]
    if isinstance(dep, dict):
        return list(dep.keys())
    return []


def collect_services(compose_files: list[Path]) -> dict[str, dict]:
    """Merge services across all compose files for a stack. Later files'
    entries deep-overlay earlier ones'."""
    merged: dict[str, dict] = {}
    for f in compose_files:
        try:
            doc = yaml.safe_load(f.read_text()) or {}
        except yaml.YAMLError:
            continue
        services = doc.get("services") or {}
        if not isinstance(services, dict):
            continue
        for name, svc in services.items():
            if not isinstance(svc, dict):
                continue
            if name in merged:
                # Shallow merge — enough for our needs (we only inspect
                # `build`, `labels`, `depends_on`, all top-level fields).
                merged[name] = {**merged[name], **svc}
            else:
                merged[name] = dict(svc)
    return merged


def stack_compose_files(stack_toml: Path) -> list[Path]:
    """Resolve a stack.toml's file_paths into existing compose files."""
    import tomllib
    with open(stack_toml, "rb") as fp:
        data = tomllib.load(fp)
    out: list[Path] = []
    stacks = data.get("stack", [])
    if not stacks:
        return [stack_toml.parent / "compose.yaml"]
    cfg = stacks[0].get("config", {})
    paths = cfg.get("file_paths") or ["compose.yaml"]
    for p in paths:
        candidate = (stack_toml.parent / p).resolve()
        if candidate.exists():
            out.append(candidate)
    return out


def main() -> int:
    errors: list[str] = []

    # Iterate stacks via stack.toml so we can pick up multi-host overlays
    # (compose.shared.yaml + per-host compose.yaml) via file_paths.
    # Standalone compose.yamls without stack.toml are caught via the
    # global compose walk below.
    seen_compose_files: set[Path] = set()
    stack_services_checked = 0
    stack_build_services_checked = 0

    for stack_toml in sorted(REPO_ROOT.rglob("stack.toml")):
        rel = stack_toml.relative_to(REPO_ROOT)
        if is_skipped(stack_toml) or "komodo-src" in rel.parts:
            continue

        compose_files = stack_compose_files(stack_toml)
        if not compose_files:
            continue
        seen_compose_files.update(compose_files)

        services = collect_services(compose_files)

        # Build a set of which services in this stack have a `build:` —
        # used by check 3 (depends_on a build service).
        build_service_names = {n for n, s in services.items() if s.get("build") is not None}

        for svc_name, svc in services.items():
            stack_services_checked += 1
            labels = svc.get("labels")

            # Check 1: stack-content-hash label
            label_val = label_value(labels, LABEL_KEY)
            if not label_val or not _interp_re("STACK_CONTENT_HASH").search(label_val):
                errors.append(
                    f"{rel}::{svc_name}: missing label "
                    f"`{LABEL_KEY}: ${{STACK_CONTENT_HASH:-unset}}` "
                    f"(needed so compose recreates the container when the "
                    f"stack dir changes)"
                )

            build = svc.get("build")
            if build is not None:
                stack_build_services_checked += 1

                # Check 2: build.args.STACK_CONTENT_HASH must reference
                # this service's own BUILD_HASH_<self>.
                arg_val = build_args_value(build, "STACK_CONTENT_HASH")
                expected_var = f"BUILD_HASH_{env_safe(svc_name)}"
                if not arg_val or not _interp_re(expected_var).search(arg_val):
                    errors.append(
                        f"{rel}::{svc_name}: build-mode service is missing "
                        f"`build.args.STACK_CONTENT_HASH: "
                        f"${{{expected_var}:-unset}}` (needed so docker's "
                        f"build-layer cache busts when the service's build "
                        f"context changes)"
                    )

                dockerfile = resolve_dockerfile(compose_files[0], svc)
                if dockerfile is not None and dockerfile.exists():
                    if not dockerfile_has_arg_propagation(dockerfile):
                        df_rel = (
                            dockerfile.relative_to(REPO_ROOT)
                            if dockerfile.is_relative_to(REPO_ROOT)
                            else dockerfile
                        )
                        errors.append(
                            f"{df_rel} (for {rel}::{svc_name}): missing "
                            f"`ARG STACK_CONTENT_HASH` + ENV / RUN that "
                            f"references `${{STACK_CONTENT_HASH}}`; "
                            f"without an ARG-using layer the build cache "
                            f"won't bust on content changes"
                        )

            # Check 3: depends_on a build service → need depends-on-<dep>
            # label referencing that service's BUILD_HASH_<dep>.
            for dep_name in depends_on_services(svc):
                if dep_name not in build_service_names:
                    continue
                dep_label_key = f"{DEPENDS_LABEL_PREFIX}{dep_name}"
                dep_label_val = label_value(labels, dep_label_key)
                expected_dep_var = f"BUILD_HASH_{env_safe(dep_name)}"
                if not dep_label_val or not _interp_re(expected_dep_var).search(dep_label_val):
                    errors.append(
                        f"{rel}::{svc_name}: depends_on `{dep_name}` "
                        f"(a build service) but missing label "
                        f"`{dep_label_key}: ${{{expected_dep_var}:-unset}}` "
                        f"(without it, an init-image rebuild won't recreate "
                        f"this service to pick up the new init output)"
                    )

    # Catch any compose files we didn't visit via a stack.toml (shouldn't
    # happen for podhaus stacks, but kookaburra-periphery / kangaroo-
    # periphery compose.yamls would land here — those are skipped above).
    for f in sorted(REPO_ROOT.rglob("compose*.yaml")):
        if is_skipped(f):
            continue
        if f in seen_compose_files:
            continue
        if any(part.startswith(".") for part in f.relative_to(REPO_ROOT).parts):
            continue
        # Shared overlay file that's only consumed via file_paths from
        # per-host stack.tomls — already covered transitively.
        if f.name == "compose.shared.yaml":
            continue
        # Lint a bare compose.yaml that no stack.toml referenced (none
        # currently expected in podhaus, but a defensive belt).
        try:
            doc = yaml.safe_load(f.read_text()) or {}
        except yaml.YAMLError as e:
            errors.append(f"{f.relative_to(REPO_ROOT)}: yaml parse error: {e}")
            continue
        services = doc.get("services") or {}
        for svc_name, svc in services.items():
            if not isinstance(svc, dict):
                continue
            labels = svc.get("labels")
            label_val = label_value(labels, LABEL_KEY)
            if not label_val or not _interp_re("STACK_CONTENT_HASH").search(label_val):
                errors.append(
                    f"{f.relative_to(REPO_ROOT)}::{svc_name}: missing "
                    f"`{LABEL_KEY}` label (orphan compose.yaml)"
                )

    if errors:
        print("stack-content-hash lint: MISSING WIRING", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        print(
            "\nFix: see AGENTS.md \"Content-hash change detection\" for the "
            "expected per-service convention.",
            file=sys.stderr,
        )
        return 1

    print(
        f"stack-content-hash lint: OK "
        f"({stack_services_checked} service(s), "
        f"{stack_build_services_checked} build-mode)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
