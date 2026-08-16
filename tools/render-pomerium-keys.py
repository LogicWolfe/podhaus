#!/usr/bin/env python3
'''
Render Pomerium's SSH key material from the Ansible inventory.

The set of registered SSH keys (Nathan's personal key plus every
`remote_dev_machines` machine key) exists in three files:

  - ansible/inventory (group_vars/all.yml + host_vars/*.yml) — the source
  - pomerium/config.yaml `&registered_ssh_keys` — PRIVILEGE: a listed key
    may assume any principal through a Pomerium SSH route
  - pomerium/stack.toml `POMERIUM_SSH_KEY_OWNERS` — NOTIFICATION: maps the
    key's SHA256 fingerprint to the fenwick account that gets the sign-in
    push

The last two were hand-synced copies of the first, and copies drift: a
deregistered fractal key survived in the fenwick map for days after it was
removed everywhere else. This script makes the inventory the only place a
key is declared — it rewrites both derived blocks in place, and `--verify`
(run by tools/pre-commit) fails the commit when a derived block does not
match the inventory.

Registering a machine is now: add podhaus_machine_key to its host_vars,
put it in the right inventory groups, run this script, commit.

Run from anywhere inside the repo. No third-party deps beyond PyYAML
(already a Pipenv dependency via Ansible).
'''
from __future__ import annotations

import base64
import hashlib
import json
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
INVENTORY = REPO_ROOT / "ansible" / "inventory"
CONFIG_YAML = REPO_ROOT / "pomerium" / "config.yaml"
STACK_TOML = REPO_ROOT / "pomerium" / "stack.toml"

# The fenwick account notified for every registered key. Single-operator
# fleet; a second person means a second account here keyed by... something,
# and that redesign should happen in this script, not by hand-editing the
# rendered JSON.
FENWICK_USER = "Nathan"


def registered_keys() -> list[str]:
    '''Personal key first, then machine keys sorted by hostname.'''
    groups = yaml.safe_load((INVENTORY / "hosts.yml").read_text())["all"]["children"]
    personal = yaml.safe_load((INVENTORY / "group_vars" / "all.yml").read_text())[
        "podhaus_personal_key"
    ]
    keys = [" ".join(personal.split())]
    for host in sorted(groups["remote_dev_machines"]["hosts"] or {}):
        host_vars = yaml.safe_load((INVENTORY / "host_vars" / f"{host}.yml").read_text())
        keys.append(" ".join(host_vars["podhaus_machine_key"].split()))
    return keys


def fingerprint(key: str) -> str:
    blob = base64.b64decode(key.split()[1])
    digest = base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")
    return f"SHA256:{digest}"


def comment(key: str) -> str:
    label = " ".join(key.split()[2:])
    if not label:
        sys.exit(f"key has no comment to use as its label: {key[:40]}…")
    return label


def render_config_yaml(text: str, keys: list[str]) -> str:
    '''Replace the &registered_ssh_keys list items, preserving indentation.'''
    pattern = re.compile(
        r"(?P<head>ssh_publickey: &registered_ssh_keys\n)(?P<items>(?:\s+- '[^']*'\n)+)"
    )
    match = pattern.search(text)
    if not match:
        sys.exit(f"{CONFIG_YAML}: could not find the &registered_ssh_keys list")
    indent = re.match(r"\s*", match["items"])[0]
    items = "".join(f"{indent}- '{key}'\n" for key in keys)
    return text[: match.start("items")] + items + text[match.end("items") :]


def render_stack_toml(text: str, keys: list[str]) -> str:
    '''Replace the POMERIUM_SSH_KEY_OWNERS value line.'''
    owners = {
        fingerprint(key): {"user": FENWICK_USER, "machine": comment(key)}
        for key in keys
    }
    pattern = re.compile(
        r"(?P<head>name = \"POMERIUM_SSH_KEY_OWNERS\"\nvalue = ')(?P<json>[^']*)(?=')"
    )
    match = pattern.search(text)
    if not match:
        sys.exit(f"{STACK_TOML}: could not find the POMERIUM_SSH_KEY_OWNERS value")
    rendered = json.dumps(owners, separators=(",", ":"))
    return text[: match.start("json")] + rendered + text[match.end("json") :]


def main() -> None:
    verify = "--verify" in sys.argv[1:]
    keys = registered_keys()
    stale = []
    for path, render in ((CONFIG_YAML, render_config_yaml), (STACK_TOML, render_stack_toml)):
        current = path.read_text()
        rendered = render(current, keys)
        if rendered == current:
            continue
        if verify:
            stale.append(path)
        else:
            path.write_text(rendered)
            print(f"rewrote {path.relative_to(REPO_ROOT)}")
    if stale:
        names = ", ".join(str(p.relative_to(REPO_ROOT)) for p in stale)
        sys.exit(
            f"{names}: key material does not match the Ansible inventory.\n"
            "Run tools/render-pomerium-keys.py and commit the result."
        )


if __name__ == "__main__":
    main()
