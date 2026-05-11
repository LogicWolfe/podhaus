# AGENTS.md — instructions for AI agents working in podhaus

This is the canonical instruction file for any AI agent (Claude Code,
Codex, Cursor, Aider, etc.) working in this repository. `CLAUDE.md`
re-exports it via `@AGENTS.md` so Claude Code sees the same content.

Read the **Required reading** section below before making any changes.

---

## Required reading

Live docs: <https://docs.pod.haus>. Local fallback: open
`docs/index.html` directly in a browser (everything except the plans
auto-listing works on `file://`).

Consult these pages before acting:

| For… | Read |
|---|---|
| The big picture, in one page | [`docs/architecture.html`](docs/architecture.html) |
| Adding or changing a service stack | [`docs/stack-conventions.html`](docs/stack-conventions.html) |
| Multi-host shared services (backup, autoheal, logging) | [`docs/stack-conventions.html`](docs/stack-conventions.html) + [`docs/komodo.html`](docs/komodo.html) |
| How Komodo, ResourceSync, and the two operating models work | [`docs/komodo.html`](docs/komodo.html) |
| Secrets, Komodo Variables, the `[[VAR]]` flow | [`docs/secrets.html`](docs/secrets.html) |
| dockernet, Cloudflare Tunnel, Access, DNS | [`docs/networking.html`](docs/networking.html) |
| Storage tier rule (local / Jump / Pouch) | [`docs/storage.html`](docs/storage.html) |
| Backup / restore / off-site sync | [`docs/backup-and-recovery.html`](docs/backup-and-recovery.html) |
| Gatus alerts, log pipeline, autoheal | [`docs/monitoring.html`](docs/monitoring.html) |
| Cron / ofelia jobs | [`docs/scheduling.html`](docs/scheduling.html) |
| DR rebuild runbooks | [`docs/disaster-recovery.html`](docs/disaster-recovery.html) |
| Service-specific quirks | [`docs/runbooks/<service>.html`](docs/runbooks/) |
| Current or recent migrations, design context | [`docs/plans/`](docs/plans/) |

**If you're about to modify a stack and the relevant runbook page exists,
read it first.** Plex and Paperless in particular have non-obvious
constraints (identity preservation, dockernet-only access pattern) that
aren't obvious from the compose files alone.

---

## What podhaus is

Docker container infrastructure for two home servers — **bilby** (Apple
M1 Mac mini, primary; Fedora Asahi Linux) and **kangaroo** (QNAP NAS,
QTS + Container Station). Managed as Docker Compose stacks under a
single Komodo Core; secrets flow from 1Password; ingress via Cloudflare
Tunnel + Access at `*.pod.haus`. A planned third host **pinelake** will
slot into the same pattern.

---

## Architecture

- **Komodo Core** on bilby manages every stack on both hosts via per-host
  Periphery agents.
- Single-host services live in a top-level directory with `compose.yaml`
  and `stack.toml` (e.g. `paperless/`, `plex/`, `gatus/`).
- **Multi-host shared services** use `<service>/{compose.shared.yaml,
  <host>/...}`. Each host's `<service>/<host>/compose.yaml` does
  `include: [../compose.shared.yaml]` (or Komodo's
  `file_paths = ["compose.yaml", "../compose.shared.yaml"]`) and overlays
  host-specific bits. Pattern in use: `backup/`, `autoheal/`, `logging/`.
- Repo root is bind-mounted into both bilby's Komodo Core (ResourceSync)
  and bilby's Periphery (compose files). Kangaroo's Periphery clones the
  repo itself via Komodo's Linked Repo feature.
- Secrets flow: **1Password Homelab vault → `komodo-op` → Komodo
  Variables → `[[VARIABLE]]` interpolation in stack environment**.
- Non-secret variables are seeded by `komodo-start` (TZ, MEDIA_DIR,
  PODHAUS_REPO). The `komodo/sync/variables.toml` file is descriptive,
  not authoritative.
- Volumes are declared in compose without `external: true` unless they
  exist outside the stack — Docker Compose creates them on first deploy.
- `komodo-start` bootstraps everything (idempotent).

---

## Networking

- **`dockernet`**: bridge network at `172.18.0.0/16` for cross-stack
  communication. Containers join via `networks: [dockernet]` plus a
  top-level `networks: { dockernet: { external: true } }` block.
- Containers reach each other by **container name** (Docker DNS), never
  by static IP.
- Static IPs are for LAN devices (e.g. UniFi gateway at `10.0.0.1`) or
  host-network services.
- Services needing device access (Home Assistant, Plex, Syncthing) use
  `network_mode: host`. Cloudflare Tunnel reaches them via the dockernet
  bridge gateway at `172.18.0.1:<port>`.
- Cloudflare Tunnel routes `*.pod.haus` subdomains directly to backends
  (no nginx). Ingress rules in `cloudflare-tunnel/conf/config.yml`.
- A single Cloudflare Access app gates the entire `*.pod.haus` wildcard
  on a Family identity policy — no per-service Access app needed.

---

## Key files

| File | What it is |
|---|---|
| `komodo/ferretdb.compose.yaml` | Komodo Core infra (postgres, FerretDB, Core, Periphery) |
| `komodo/compose.env` | Komodo config with `op://` secret references |
| `<name>/compose.yaml` | Docker Compose file for each service stack |
| `<name>/stack.toml` | Komodo stack metadata (server assignment, environment block) |
| `komodo/sync/variables.toml` | Non-secret variable declarations (descriptive, see `komodo-start` for authoritative) |
| `komodo/sync/servers.toml` | Server definitions (bilby + kangaroo) |
| `komodo/sync/repos.toml` | Linked Repo definitions for kangaroo |
| `komodo-start` | Bootstrap script (Core + variables + ResourceSync). Idempotent. |
| `komodo-sync` | Trigger ResourceSync without a full Core restart |
| `komodo-stop` | Stop Komodo Core |
| `komodo-status` | Show Komodo Core container status |
| `komodo-upgrade` | Pull latest images + restart Komodo |
| `kangaroo_bootstrap` | One-time kangaroo Periphery bring-up |
| `cloudflare/` | Terraform sources for all Cloudflare resources (DNS, Access apps, policies, service tokens). State at `s3://terraform-state/cloudflare.tfstate` in MinIO. |
| `tf` | `op run`-wrapped `hashicorp/terraform` docker runner, attaches to `dockernet`. |
| `minio/` | Single-node MinIO — S3 backend for Terraform state. |
| `dns/dnsconfig.js` | DNSControl zone declarations for UniFi split-horizon only (Cloudflare moved to Terraform). |
| `dns/creds.json` | DNSControl UniFi provider credentials (env var refs, no secrets). |
| `dns-preview` | DNSControl dry-run script (UniFi only). |
| `dns-push` | DNSControl apply script (UniFi only). |
| `docs/` | The published docs (served at `docs.pod.haus`) |
| `docs-server/` | nginx stack serving `docs/` |
| `AGENTS.md` | This file |
| `CLAUDE.md` | One-line `@AGENTS.md` re-export |

---

## When adding a new service

1. Create `<name>/compose.yaml` with the Docker Compose definition.
2. Create `<name>/stack.toml` with `files_on_host = true` and
   `run_directory = "/etc/komodo/repo/<name>"` (bilby) or
   `linked_repo = "podhaus"` (kangaroo).
3. Add any new secrets to the 1Password **Homelab** vault — `komodo-op`
   auto-syncs them as `OP__KOMODO__<ITEM>__<FIELD>` Komodo Variables.
4. If the stack needs a non-secret variable, seed it in `komodo-start`
   (not in `variables.toml` alone — see `docs/secrets.html`).
5. Run `./komodo-sync` to register the stack. Deploy it from the Komodo
   UI.
6. If the service needs a hostname, add an ingress rule to
   `cloudflare-tunnel/conf/config.yml` and a `cloudflare_dns_record`
   resource to the appropriate `cloudflare/dns_<zone>.tf`. Then
   `cd cloudflare && op run --env-file=.env -- ../tf apply` to
   publish the DNS change.

## When adding a new instance of a shared service to another host

Multi-host services already in this layout: `backup/`, `autoheal/`,
`logging/`. Each has `<service>/compose.shared.yaml` plus per-host
subdirs.

1. Create `<service>/<host>/compose.yaml` that does
   `include: [../compose.shared.yaml]` (or set `file_paths` in
   `stack.toml`) and overlays host-specific bits.
2. Create `<service>/<host>/stack.toml` setting the per-host
   `environment` block. Variable **names** must match the shared
   compose's contract; **values** come from host-specific 1P items.
3. If the host needs a config template, put it at
   `<service>/<host>/<template>` and reference it from the per-host
   overlay's bind mount.
4. Run `./komodo-sync`.

When fixing a bug in a multi-host service, edit
`<service>/compose.shared.yaml` (and the shared template if present) —
the change applies to all hosts uniformly. Per-host overlay edits should
only touch genuinely host-specific bits.

---

## Hard rules

These have failure modes that you must not introduce:

- **Never use single-file bind mounts** for any config the running
  service reads after startup. File-level binds pin the inode at mount
  time, so atomic-rename editor saves on the host leave the container
  pointed at the orphan original forever. Always bind the containing
  directory. The exception is init containers that read the file once at
  startup and exit — those are fine. See
  [`docs/stack-conventions.html#bind-mounts`](docs/stack-conventions.html).
- **Never create Komodo Variables in the UI.** They don't survive a
  fresh Komodo bootstrap. Put the secret in 1Password and reference the
  `OP__KOMODO__*` synced variable name. See
  [`docs/secrets.html`](docs/secrets.html).
- **Always use absolute host paths in bind mounts.**
  `${PODHAUS_REPO}/<stack>/...`, never relative paths. Relative paths
  resolve against the periphery container's filesystem, not the host's,
  and Docker silently creates empty stub directories.
- **Don't push, deploy, or change DNS / Access policy without explicit
  user authorization.** Treat all `git push`, `./komodo-sync` (deploy),
  `./dns-push`, and any `tf apply` against `cloudflare/` as actions that
  require a green light. `dns-preview` and `tf plan` are fine.
- **Don't bypass git hooks (`--no-verify`, etc.) without explicit
  permission.** Same for force-push, hard reset, branch deletion.
- **Plex identity is sacred.** Never let Plex start without an init
  container that confirms `Preferences.xml` has the expected
  `MachineIdentifier`. See
  [`docs/runbooks/plex.html`](docs/runbooks/plex.html).

---

## Doc index

The full set of pages on `docs.pod.haus`:

**Getting started**
- [Overview](docs/index.html)
- [Architecture](docs/architecture.html)
- [Hosts](docs/hosts.html)
- [Storage](docs/storage.html)
- [Networking](docs/networking.html)

**Platform**
- [Komodo](docs/komodo.html)
- [Secrets & variables](docs/secrets.html)
- [Stack conventions](docs/stack-conventions.html)

**Operations**
- [Backup & recovery](docs/backup-and-recovery.html)
- [Monitoring](docs/monitoring.html)
- [Scheduling](docs/scheduling.html)
- [Disaster recovery](docs/disaster-recovery.html)

**Service runbooks**
- [Plex](docs/runbooks/plex.html)
- [Plex maintenance log](docs/runbooks/plex-maintenance.html)
- [Paperless](docs/runbooks/paperless.html)
- [Syncthing](docs/runbooks/syncthing.html)
- [Flood + RAR pipeline](docs/runbooks/flood.html)

**Plans**
- [All plans](docs/plans/)
- Plans can be authored as `.md`, `.html`, or as a directory containing
  `index.md` plus sub-pages (for big multi-phase plans). See the
  [Sample Nested Plan](docs/plans/sample-nested-plan/) for the
  convention.

---

## Editing docs

Every page under `docs/` is a static HTML file or `.md` plan. Edit it,
save, refresh the browser — changes appear immediately, no rebuild or
container restart (the nginx server is bind-mount-backed with no-cache
headers on HTML / JSON / Markdown / site JS+CSS). Adding a new doc:

1. Copy `docs/_template.html`.
2. Set `<title>` and the `<meta name="doc-group">` /
   `<meta name="doc-order">` / optional `<meta name="doc-title">` tags.
3. Save — the sidebar discovers it automatically on next page load.

Adding a new plan: drop a `.md` or `.html` into `docs/plans/`, or create
a subdirectory with `index.md` for a multi-page plan.
