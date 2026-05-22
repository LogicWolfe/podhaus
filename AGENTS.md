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

Docker container infrastructure for **three** hosts:
- **bilby** (Apple M1 Mac mini, primary; Fedora Asahi Linux) — runs
  Komodo Core, MinIO, Caddy, every primary service.
- **kangaroo** (QNAP NAS, QTS + Container Station) — secondary LAN
  deploy target via linked-repo Periphery.
- **kookaburra** (DigitalOcean droplet, syd1, Fedora 43, x86_64) —
  off-LAN public-ingress relay host. Runs rathole (server) so external
  clients reaching `storage.pod.haus` are tunneled back to bilby's
  Caddy (TLS terminates at bilby; the droplet only sees ciphertext —
  intrinsic relay config only, no MinIO data/certs/creds).

Managed as Docker Compose stacks under a single Komodo Core; secrets
flow from 1Password; ingress for most services via Cloudflare Tunnel
+ Access at `*.pod.haus`, and for `storage.pod.haus` specifically via
the kookaburra rathole relay (the UDM Pro SE binds WAN:443 itself, so
direct port-forward never worked from genuine external clients — see
`docs/hosts.html#kookaburra`). A planned fourth host **pinelake** will
slot into the kookaburra pattern (linked-repo Periphery + tailscale).

**Management plane (tag:podnet on Tailscale):** Komodo Core →
kookaburra Periphery + log ship-back ride a private tailnet between
bilby (`bilby-1`) and kookaburra (`kookaburra`) — kookaburra's
Periphery is never internet-exposed; the public surface there is
only :443 (rathole data) + :2333 (rathole control, noise+token).
ACL is asymmetric: your devices → podnet freely; podnet ↛ your
devices (blast-radius containment).

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
- Non-secret variables live in TOML and apply via the ResourceSync
  (`include_variables = true` on the `podhaus` sync). Global ones
  (`TZ`, `MEDIA_DIR`) live in `komodo/sync/variables.toml`;
  stack-private ones (e.g. `FENWICK_*`) live as inline `[[variable]]`
  blocks in the relevant `<stack>/stack.toml`.
  - **Exception:** `PODHAUS_REPO` is host-discovered (`= $PWD` at
    bootstrap time, varies per host), so it can't live in a TOML.
    `komodo-start` seeds it directly via the Komodo API.
  - **Caveat:** the sync runs with `delete: false` (additive only —
    flipping `delete: true` would nuke komodo-op's continuously-synced
    `OP__KOMODO__*` vars). Side effect: a variable removed from TOML
    lingers in Komodo until manually deleted via the API
    (`DeleteVariable`). See `docs/secrets.html`.
- Volumes are declared in compose without `external: true` unless they
  exist outside the stack — Docker Compose creates them on first deploy.
- `komodo-start` is bootstrap-only (Komodo Core stack up + 5
  chicken-and-egg vars + create-resource-sync + bootstrap double-sync).
  Steady-state debug iteration uses `komodo-sync`; push-to-deploy uses
  the `podhaus-push-deploy` procedure.

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
- **bilby's `/etc/docker/daemon.json` sets
  `"dns": ["100.100.100.100", "1.1.1.1"]`**, so Docker's embedded DNS
  resolver (`127.0.0.11`) forwards unknown names to Tailscale's MagicDNS
  first, then 1.1.1.1. This is what lets `komodo/sync/servers.toml`
  use `https://kookaburra-podnet.tail9ceb.ts.net:8120` instead of
  the drifting tailnet IP. Service-name resolution (`ferretdb`,
  `caddy`, etc.) is still handled internally by the embedded resolver
  before forwarding. **Never reintroduce per-container `dns: [...]`
  in compose** — that replaces `127.0.0.11` entirely and breaks
  service-name resolution (this exact mistake bit Komodo Core earlier
  in 2026-05). Daemon-wide is the only correct knob.

---

## Key files

| File | What it is |
|---|---|
| `komodo/ferretdb.compose.yaml` | Komodo Core infra (postgres, FerretDB, Core, Periphery) |
| `komodo/compose.env` | Komodo config with `op://` secret references |
| `<name>/compose.yaml` | Docker Compose file for each service stack |
| `<name>/stack.toml` | Komodo stack metadata (server assignment, environment block) |
| `komodo/sync/variables.toml` | Global non-secret variable declarations (TZ, MEDIA_DIR). Authoritative — applied by the podhaus sync (`include_variables = true`). Stack-private vars live as inline `[[variable]]` blocks in `<stack>/stack.toml` instead. |
| `komodo/sync/servers.toml` | Server definitions (bilby + kangaroo + kookaburra) |
| `komodo/sync/repos.toml` | Linked Repo definitions for kangaroo (`podhaus`) + kookaburra (`podhaus-kookaburra`) |
| `komodo/sync/procedures.toml` | `podhaus-push-deploy` procedure: Stage 0 RunSync (reconcile defs) → Stage 1 deploy-if-changed (bilby) → Stage 2 force-deploy linked-repo stacks. |
| `komodo-start` | Bootstrap-only script: Komodo Core stack up, 5 chicken-and-egg vars seeded (4 `ONEPASSWORD_*` + `PODHAUS_REPO`), idempotent CreateResourceSync (with existence check), bootstrap double-sync (first sync + wait for komodo-op + second sync). Idempotent — safe to re-run. |
| `komodo-sync` | Steady-state debug-iterate tool: single RunSync + redeploy any stack whose `deployed_hash` diverges from `HEAD`. Use when iterating locally without pushing. |
| `tools/lint-stack-env.py` | Pre-commit env-lint: walks every `<stack>/stack.toml`'s `environment` block, verifies each key is referenced in compose. Hook at `tools/pre-commit`; install via `ln -sf ../../tools/pre-commit .git/hooks/pre-commit`. |
| `komodo-stop` | Stop Komodo Core |
| `komodo-status` | Show Komodo Core container status |
| `komodo-upgrade` | Pull latest images + restart Komodo |
| `kangaroo_bootstrap` | One-time kangaroo Periphery bring-up |
| `kookaburra_bootstrap` | Idempotent kookaburra bring-up: SSH hardening → dockernet bridge → tailscale (Komodo adopts it post-handoff) → Periphery. Defaults `DROPLET_IP` to the reserved IP (`170.64.241.136`) so it stays correct across `terraform apply -replace`. |
| `terraform/` | The ONE consolidated Terraform root for the whole fleet — Cloudflare (DNS, Access, Tunnel), UniFi DNS, GitHub deploy webhook, Tailscale auth-key rotation, DigitalOcean (kookaburra relay), MinIO IAM/bucket policies (Publii tenants). State `s3://terraform-state/podhaus.tfstate` in MinIO via `https://storage.pod.haus`. Run **stock `terraform`** directly (creds from the chezmoi-rendered, PWD-scoped `~/.config/fish/conf.d/podhaus-tf.fish`; no wrapper). Replaced the split `cloudflare/` + `minio/terraform/` + relay-only `terraform/` roots in 2026-05; see `/docs/terraform.html`. |
| `minio/` | Single-node MinIO — S3 backend for Terraform state + public S3 (Publii) via `storage.pod.haus`. |
| `caddy/` | TLS front (own LE wildcard) for `storage.pod.haus` → MinIO; for genuine external clients, traffic arrives via the kookaburra rathole tunnel (the UDM Pro SE binds WAN:443 itself so direct port-forward is a dead path). LAN clients reach Caddy directly via UniFi split-horizon. See `docs/hosts.html#kookaburra` + `docs/terraform.html`. |
| `relay/` | rathole stacks — `relay/bilby/` (Komodo-managed client, dials out) + `relay/kookaburra/` (Komodo-managed server, public :443 + :2333). Built from upstream release binary (no arm64 image). |
| `tailscale/` | Tailscale management-plane nodes. `tailscale/bilby/` and `tailscale/kookaburra/` are both Komodo-managed (Komodo Core on bilby, `kookaburra-tailscale` linked-repo stack on kookaburra). kookaburra's tailscale is bootstrap-launched (via `kookaburra_bootstrap`) so Periphery can join the tailnet, then Komodo adopts the running container — bootstrap and Komodo use the same compose project name + container name (`kookaburra-podnet`) so the named state volume and tailnet identity survive the handoff. `tailscale/compose.shared.yaml` has a `tailscale-cleanup` init service (built from the shared `init-tools:local` image — `curl + jq` baked in) that calls the Tailscale API before tailscaled starts to prune offline devices matching `${TS_HOSTNAME}` — claims the bare hostname back when the state volume is regenerated (rebuild, accidental volume nuke). The auth key it would re-enrol with is **TF-managed** by `terraform/tailscale.tf` (mints a reusable `tag:podnet` key, 80-day rotation via `time_rotating`, writes back to the same 1P item via `op item edit`). Requires `Tailscale OAuth Client` 1P item scopes `auth_keys:write` + `devices:core:write`. |
| `kookaburra/periphery/` | kookaburra Komodo Periphery compose. Bootstrap-managed (parallels `kangaroo/periphery/`). Reachable only over tailnet (PERIPHERY_ALLOWED_IPS=100.64.0.0/10). |
| `logging/kookaburra/` | Alloy on kookaburra — ships container logs cross-tailnet to bilby's ClickStack at `bilby-podnet.tail9ceb.ts.net:4318` via MagicDNS. kookaburra's `/etc/docker/daemon.json` forwards container DNS to `100.100.100.100` + `1.1.1.1` (mirrors bilby's setup; daemon.json is system-level on the droplet, not in this repo). |
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
4. If the stack needs a non-secret variable, declare it inline in
   the stack's own `stack.toml` as a `[[variable]]` block (stack-private,
   co-located). Use `komodo/sync/variables.toml` only for things every
   stack might reference (currently TZ + MEDIA_DIR). The sync applies
   both. **Don't** add to `komodo-start` — that script is bootstrap-only
   and the only seed it still owns is host-discovered `PODHAUS_REPO`.
5. **Push the commit.** The `podhaus-push-deploy` procedure's Stage 0
   RunSync registers the new stack + any new variables; Stage 1
   `BatchDeployStackIfChanged "*"` deploys it (the
   `(None, _) => DeployIfChangedAction::FullDeploy` path covers brand-new
   stacks). No manual UI click. For local iteration without pushing,
   `./komodo-sync` does single RunSync + redeploy-stale.
6. **Nothing to do for push-to-deploy.** There is ONE GitHub `push`
   webhook for the whole repo; it drives the `podhaus-push-deploy`
   Komodo Procedure (`komodo/sync/procedures.toml`). Three stages:
   **Stage 0** `RunSync "podhaus"` reconciles stack defs + TOML-declared
   variables from disk into Komodo's stored resource state (so a push
   that adds/changes an `environment` line or a `[[variable]]` block
   reaches the deploy correctly — without this, the deploy uses the
   pre-sync stored env and renders `${VAR}` empty). **Stage 1**
   `BatchDeployStackIfChanged "*"` covers every current and future stack
   (deploy-only-if-its-files-changed; bilby no-churn; new-stack first
   deploy works via `deploy = true` + `(None, _) =>
   DeployIfChangedAction::FullDeploy`). **Stage 2** `BatchDeployStack
   "kangaroo-*" + "kookaburra-*"` force-deploys linked_repo stacks
   unconditionally. A new stack auto-deploys on the next push with
   no `terraform/` edit. (This replaced 20 per-stack webhooks: GitHub
   hard-caps a repo at 20 `push` webhooks, and the fleet outgrew it.)
   Do **not** set `webhook_force_deploy` — there are no per-stack
   webhooks for it to affect; the kangaroo force path is Stage 2.
7. If the service is a single-host pod.haus service, add a
   `module "<name>"` block in `terraform/services_pod_haus.tf` plus
   one entry in `tunnel.tf`'s `pod_haus_module_ingress`. The module
   owns DNS + Access policy chain + tunnel ingress; default policy
   chain is Homelab service-token bypass + Family allow.
   `cd terraform && terraform apply` to publish (creds are ambient
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

- **podhaus Terraform must run from any machine — ONE consolidated
  root, no exceptions.** Contract: clone podhaus + have
  chezmoi-provisioned creds ⇒ `terraform` works from `terraform/`.
  No second TF root may be introduced without a load-bearing reason
  documented in `/docs/terraform.html` — the consolidation (May 2026)
  collapsed three roots into one specifically to keep the surface
  small. No host-pinned backend endpoint (the S3 state backend uses
  the public `https://storage.pod.haus`, never `minio:9000`/loopback),
  no LAN-only provider `api_url` (UniFi uses `https://unifi.pod.haus`,
  never `10.0.0.1`; the MinIO provider uses `https://storage.pod.haus`,
  never `127.0.0.1`), no dockernet assumption anywhere. Reject any
  change reintroducing a LAN IP, dockernet name, or loopback in
  `terraform/` — and reject any "this is bilby-only / admin tooling"
  carve-out (that exact rationalisation was caught and removed once).
  Run `terraform` directly — there is no wrapper script.
  See [`docs/terraform.html`](docs/terraform.html).
- **MinIO public access-control model: SigV4, not an edge block.**
  `storage.pod.haus` serves the full MinIO API (S3 *and* admin); the
  sole boundary is MinIO's own per-request SigV4 (root/scoped creds
  live only in 1Password + the chezmoi Terraform env;
  unauthenticated calls incl. `/minio/admin/` get `AccessDenied`).
  **Do not add an edge `/minio/admin/` 403 / WAF block** — it breaks
  the from-anywhere `terraform/` root and contradicts the rule above.
  Data-plane isolation is done with per-bucket least-priv keys (e.g.
  per-Publii-site service accounts), not network filtering.
- **Never use single-file bind mounts** for any config the running
  service reads after startup. File-level binds pin the inode at mount
  time, so atomic-rename editor saves on the host leave the container
  pointed at the orphan original forever. Always bind the containing
  directory. The exception is init containers that read the file once at
  startup and exit — those are fine. See
  [`docs/stack-conventions.html#bind-mounts`](docs/stack-conventions.html).
- **Config-only commits don't auto-reload running containers.** Even
  with a directory bind, `docker compose up -d` is a no-op when nothing
  in the compose config itself changed — so `BatchDeployStack` /
  `BatchDeployStackIfChanged` pulls the new file but the running process
  keeps the cached old config. **When a push touches only
  bind-mounted config files** (anything under
  `<stack>/conf*/`, `<stack>/*-conf/`, `cloudflare-tunnel/conf/`,
  `caddy/conf*/`, `alloy-conf/`, etc.), confirm the affected daemon
  either auto-reloads (cloudflared does) or schedule a follow-up
  `docker compose up -d --force-recreate <service>` / SIGHUP /
  daemon-reload-endpoint. Bit kookaburra-logging in 2026-05 — the
  alloy endpoint flipped on disk but in-process config stayed stale
  until manual recreate. Full table + escape hatches:
  [`docs/stack-conventions.html#bind-mounts`](docs/stack-conventions.html)
  ("Config-only commits don't auto-reload" callout).
- **Never create Komodo Variables in the UI.** They don't survive a
  fresh Komodo bootstrap. Put the secret in 1Password and reference the
  `OP__KOMODO__*` synced variable name. See
  [`docs/secrets.html`](docs/secrets.html).
- **Linked Repo hosts (kangaroo, kookaburra, future pinelake) must be force-deployed
  on push — handled centrally by `podhaus-push-deploy` Stage 2, not
  per-stack.** Verified against Komodo 1.19.5 source: `DeployStack`
  *does* `git pull` the linked clone before composing — it is
  **`RestartStack`** that does not pull (it only `docker compose
  restart`s). The linked-repo trap: `DeployStackIfChanged`'s change-check
  compares against the Periphery clone, which only advances *during* a
  deploy — so on a `linked_repo` stack it no-ops forever (stale-clone
  deadlock). The push procedure resolves this structurally: Stage 1
  (`BatchDeployStackIfChanged "*"`) no-ops on linked-repo hosts
  (harmless), then Stage 2 force-deploys them via TWO executions —
  `BatchDeployStack "kangaroo-*"` AND `BatchDeployStack
  "kookaburra-*"` — running unconditional full `DeployStack` (pull +
  compose). So **no `webhook_force_deploy` on linked_repo stacks** —
  there are no per-stack webhooks; the per-host-prefix patterns are
  the contract (name new linked_repo stacks `<host>-` accordingly
  and add the matching execution to Stage 2 in
  `komodo/sync/procedures.toml`). bilby `files_on_host` stacks ride
  Stage 1 and self-skip when unchanged (free no-churn). Stage 0
  `RunSync` re-imports `stack.toml` config + TOML-declared variables
  from bilby's bind-mount (no git) but does not pull a linked clone.
  Always confirm a deploy via a config-level signal (the pulled-to
  hash / a metric), never "container healthy". See
  [`docs/komodo.html#operating-models`](docs/komodo.html).
- **Always use absolute host paths in bind mounts.**
  `${PODHAUS_REPO}/<stack>/...`, never relative paths. Relative paths
  resolve against the periphery container's filesystem, not the host's,
  and Docker silently creates empty stub directories.
- **Don't push, deploy, or change DNS / Access policy without explicit
  user authorization.** Treat all `git push`, `./komodo-sync`, and
  any `terraform apply` against `terraform/` as actions that require a
  green light. `terraform plan` is fine. Note that every `git push` to `main` fires
  the single GitHub webhook (`terraform/github.tf` →
  `komodo.pod.haus/listener/github/procedure/podhaus-push-deploy/main`),
  which runs the procedure: Stage 0 `RunSync "podhaus"` reconciles
  stack defs + TOML-declared variables, Stage 1
  `BatchDeployStackIfChanged "*"` redeploys every bilby stack whose
  files actually changed (unchanged ones self-skip — no churn), Stage 2
  force-deploys `kangaroo-*` AND `kookaburra-*` linked-repo stacks
  unconditionally. Push is not cheap and not a no-op — treat it as a
  deploy.
- **Before adding or modifying a Cloudflare / UniFi / GitHub TF
  resource, read the provider's resource doc.** Schemas change
  between minor versions and `terraform apply` errors with "Attribute X
  required" or similar without making it obvious which version you
  need. Provider doc URLs are linked from each provider's required_providers block in `terraform/backend.tf`.
- **Don't bypass git hooks (`--no-verify`, etc.) without explicit
  permission.** Same for force-push, hard reset, branch deletion.
- **Plex identity is sacred.** Never let Plex start without an init
  container that confirms `Preferences.xml` has the expected
  `MachineIdentifier`. See
  [`docs/runbooks/plex.html`](docs/runbooks/plex.html).
- **The `kookaburra` ingress relay is stateless by design — adding
  state reopens backups.** kookaburra (the off-LAN DigitalOcean
  public-ingress relay; see
  [`docs/hosts.html#kookaburra`](docs/hosts.html#kookaburra))
  is a ciphertext-only rathole passthrough: no MinIO data, certs, or
  creds — all state lives on bilby, and DR is `terraform apply`. It
  is **deliberately excluded from `backup/`**. If *any* meaningful
  state ever lands on it (a persistent volume, a local key/cert, app
  data — anything not reconstructible from `terraform apply`), that
  exemption is void: you **must** reopen the backup decision and add
  kookaburra to `backup/`. A future reader finding state there with
  no backup should treat it as a bug, not a deliberate choice. See
  [`docs/backup-and-recovery.html`](docs/backup-and-recovery.html).

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

---

## Docs vs plans — the contract

`docs/` and `docs/plans/` carry distinct contracts. Honour both.

**`docs/` reflects current state.** It is the truth about how the
system works *right now*. No history, no "we used to do X", no
"this is how we got here" narrative. A new agent or human reading
`docs/<topic>.html` should learn what's true today, full stop.
When you change behaviour, update `docs/` in the same commit.

**`docs/plans/` is work-in-progress only.** A plan exists for two
reasons: (1) capturing context an agent or user needs while the work
is in flight, (2) tracking what's left to do for partially-completed
migrations. **A plan that describes done work has no reason to exist
— delete it and ensure `docs/` reflects the new current state.**

When a plan finishes:
- Walk the plan; anything that describes how the *resulting* system
  works → fold into the appropriate `docs/` page (architecture,
  networking, runbook, hosts, secrets, etc.) if not already there.
- Anything describing the migration path itself (steps, why this
  order, deferred-traps that were closed) → delete with the plan.
- Anything still pending → trim the plan to just those remaining
  items, with a short "Done so far:" header if helpful for context.

When deferring work mid-plan, leave the plan with the remaining
items only; the closed sections come out as their content lands
in `docs/`.

This means: `docs/plans/` should always be small. If it's growing,
either work is being deferred (fine, capture it) or done plans
aren't being cleaned up (not fine).
