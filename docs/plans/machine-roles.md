# Machine roles — direction capture, not a commitment

Nathan's leaning (2026-08-11): machines take on a set of **roles** and
get built as the union of those roles — but where possible, configure
from **probed machine state/capabilities** rather than declared role.
Capture only; don't overindex.

## What already exists

The fleet has this split half-built, on both sides of the
[host-provisioning boundary](../host-provisioning.md):

- **Ansible (machine layer)** already *is* role-composition:
  `inventory/hosts.yml` role groups (`docker_hosts`,
  `komodo_periphery_hosts`, `devboxes`, `edge_hosts`, …) and
  `site.yml` gating each role on membership — "a host joins by
  capability, not by name". Nothing to invent here.
- **chezmoi (user layer)** has the complementary discipline for
  capabilities: `machine-key-mode` (hardware/soft/none — "ranked, not
  configured"), `op-homelab-ready` — probed every apply, never stored.
  Its *declared* surface is two booleans: `headless`, `homelab`.

The rule worth preserving: **a stale declaration cannot disagree with
reality if there is no declaration.** Probe whenever a probe can
answer; declare only purpose/authorization, which no probe can see.

## The gap the roles idea actually fills

chezmoi's `homelab` boolean is quietly two roles fused — "talks to
podhaus" and "reads the personal 1Password vault" — and voltaire
breaks the fusion: an office devbox wanting dev-vault access and
work-secret provisioning (today gated on `has1Password`, which
headless boxes fail) without being a home machine. The vault work
([hardware-sealed-op-tokens](hardware-sealed-op-tokens.md)) makes the
grant structure explicit per machine: voltaire holds switch+dev
tokens, no home.

Candidate user-layer role vocabulary (sketch): `remote-development`,
`local-development`, `homelab`, `switch-development`,
`home-development` — mapping to vault grants, secrets provisioning,
Claude account routing, GUI apps.

## Suggested next step (when the first consumer needs it)

Replace `homelab` in `.chezmoi.toml.tmpl` with a prompt-once `roles`
list; keep every capability probe as-is; express template gates as
role-membership checks. Ansible's inventory groups stay the machine-
layer equivalent — a new host declares its roles twice (once per
layer), which is the boundary working as designed, not duplication.
Fold the outcome into the dotfiles README and delete this page.

- [ ] Vault/secrets templates consume a role split (first real driver)
- [ ] `homelab` flag split lands with it
