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
| `cloudflare/` | Terraform sources for all Cloudflare resources (DNS, Access apps, policies, service tokens). State at `s3://terraform-state/cloudflare.tfstate` in MinIO via `https://storage.pod.haus`. Run **stock `terraform`** directly (creds from the chezmoi-rendered `~/.config/fish/conf.d/podhaus-tf.fish`; no wrapper). |
| `minio/` | Single-node MinIO — S3 backend for Terraform state + public S3 (Publii) via `storage.pod.haus`. |
| `caddy/` | TLS front (own LE wildcard) for `storage.pod.haus` → MinIO; reached via the UniFi WAN port-forward, not Cloudflare. See `docs/plans/minio-public-caddy.md`. |
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
   - **If the stack has a one-shot / init container** (any service that
     exits 0 by design — e.g. an `init-tools` setup container, a config
     renderer, an identity-merge init), you **must** add
     `ignore_services = ["<init-service-name>"]` to `[stack.config]`.
     Without it Komodo counts the exited init and marks the *whole
     stack* `Unhealthy` — a false red that erodes the monitoring
     signal (this bit `flood` until 2026-05). Pattern in:
     `plex/stack.toml`, `backup/{bilby,kangaroo}/stack.toml`,
     `flood/stack.toml`. If the init also builds an image inline
     (`build:`), set `run_build = true` too (see `plex`/`backup`).
3. Add any new secrets to the 1Password **Homelab** vault — `komodo-op`
   auto-syncs them as `OP__KOMODO__<ITEM>__<FIELD>` Komodo Variables.
4. If the stack needs a non-secret variable, seed it in `komodo-start`
   (not in `variables.toml` alone — see `docs/secrets.html`).
5. Run `./komodo-sync` to register the stack. The smart-deploy pass
   redeploys any stack whose `info.deployed_hash` diverges from
   `HEAD`, so the freshly-registered stack deploys immediately.
   `komodo-sync` is the manual "register + deploy my changes now"
   tool — not a workaround for broken webhooks (steady-state
   push-to-deploy works; see the auto-deploy hard rule below).
6. **Nothing to do for push-to-deploy.** There is ONE GitHub `push`
   webhook for the whole repo; it drives the `podhaus-push-deploy`
   Komodo Procedure (`komodo/sync/procedures.toml`), whose Stage 1
   `BatchDeployStackIfChanged "*"` already covers every current and
   future stack (deploy-only-if-its-files-changed; bilby no-churn),
   and whose Stage 2 `BatchDeployStack "kangaroo-*"` force-deploys
   linked_repo stacks. A new stack auto-deploys on the next push with
   no `cloudflare/` edit. (This replaced 20 per-stack webhooks: GitHub
   hard-caps a repo at 20 `push` webhooks, and the fleet outgrew it.)
   Do **not** set `webhook_force_deploy` — there are no per-stack
   webhooks for it to affect; the kangaroo force path is Stage 2.
7. If the service is a single-host pod.haus service, add a
   `module "<name>"` block in `cloudflare/services_pod_haus.tf` plus
   one entry in `tunnel.tf`'s `pod_haus_module_ingress`. The module
   owns DNS + Access policy chain + tunnel ingress; default policy
   chain is Homelab service-token bypass + Family allow.
   `cd cloudflare && terraform apply` to publish (creds are ambient
   from the chezmoi-rendered fish env; no wrapper, runs from any
   machine).

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

- **podhaus Terraform must run from any machine.** Contract: clone
  podhaus + have chezmoi-provisioned creds ⇒ `terraform` works. No
  host-pinned backend endpoint (the S3 state backend uses the public
  `https://storage.pod.haus`, never `minio:9000`/loopback), no
  LAN-only provider `api_url` (UniFi uses `https://unifi.pod.haus`,
  never `10.0.0.1`), no dockernet assumption in any TF root. Reject
  any change reintroducing a LAN IP, dockernet name, or loopback in a
  TF root. Run `terraform` directly — there is no wrapper script.
  See [`docs/plans/tf-runner-decommission.md`](docs/plans/tf-runner-decommission.md).
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
- **Linked Repo hosts (kangaroo, future pinelake) must be force-deployed
  on push — handled centrally by `podhaus-push-deploy` Stage 2, not
  per-stack.** Verified against Komodo 1.19.5 source: `DeployStack`
  *does* `git pull` the linked clone before composing — it is
  **`RestartStack`** that does not pull (it only `docker compose
  restart`s). The linked-repo trap: `DeployStackIfChanged`'s change-check
  compares against the Periphery clone, which only advances *during* a
  deploy — so on a `linked_repo` stack it no-ops forever (stale-clone
  deadlock). The push procedure resolves this structurally: Stage 1
  (`BatchDeployStackIfChanged "*"`) no-ops on kangaroo (harmless), then
  Stage 2 (`BatchDeployStack "kangaroo-*"`) runs an unconditional full
  `DeployStack` (pull + compose). So **no `webhook_force_deploy` on
  linked_repo stacks** — there are no per-stack webhooks; the pattern
  `kangaroo-*` is the contract (name new linked_repo stacks `kangaroo-`
  / future-host-prefixed accordingly, or extend Stage 2's pattern in
  `komodo/sync/procedures.toml`). bilby `files_on_host` stacks ride
  Stage 1 and self-skip when unchanged (free no-churn). `RunSync`
  re-imports `stack.toml` config from bilby's bind-mount (no git) but
  does not pull a linked clone. Always confirm a deploy via a
  config-level signal (the pulled-to hash / a metric), never "container
  healthy". See [`docs/komodo.html#operating-models`](docs/komodo.html).
- **Always use absolute host paths in bind mounts.**
  `${PODHAUS_REPO}/<stack>/...`, never relative paths. Relative paths
  resolve against the periphery container's filesystem, not the host's,
  and Docker silently creates empty stub directories.
- **Don't push, deploy, or change DNS / Access policy without explicit
  user authorization.** Treat all `git push`, `./komodo-sync`, and
  any `terraform apply` against `cloudflare/` as actions that require a
  green light. `terraform plan` is fine. Note that every `git push` to `main` fires
  the single GitHub webhook (`cloudflare/github.tf` →
  `komodo.pod.haus/listener/github/procedure/podhaus-push-deploy/main`),
  which runs the procedure: Stage 1 `BatchDeployStackIfChanged "*"`
  redeploys every bilby stack whose files actually changed (unchanged
  ones self-skip — no churn), Stage 2 `BatchDeployStack "kangaroo-*"`
  always full-deploys the 3 kangaroo `linked_repo` stacks. Push is not
  cheap and not a no-op — treat it as a deploy.
- **Before adding or modifying a Cloudflare / UniFi / GitHub TF
  resource, read the provider's resource doc.** Schemas change
  between minor versions and `terraform apply` errors with "Attribute X
  required" or similar without making it obvious which version you
  need. Resource docs are linked from `cloudflare/README.md`.
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
- [Bugsink](docs/runbooks/bugsink.html)

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
