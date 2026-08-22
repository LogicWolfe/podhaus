# AGENTS.md — instructions for AI agents working in podhaus

This is the canonical instruction file for any AI agent (Claude Code,
Codex, Cursor, Aider, etc.) working in this repository. `CLAUDE.md`
re-exports it via `@AGENTS.md` so Claude Code sees the same content.

Read the **Required reading** section below before making any changes.

---

## Required reading

Live docs: <https://docs.pod.haus>, served by the central **docs-server**
(`~/repos/docs`), which renders every repo's `docs/` into one shell.
Edits are live — no build, no restart. Authoring conventions:
`~/repos/docs/docs/authoring.md` (served at
<https://docs.pod.haus/docs/authoring.md>). Locally, just read the
Markdown/HTML under `docs/`.

Consult these pages before acting:

| For… | Read |
|---|---|
| The big picture, in one page | [`docs/architecture.html`](docs/architecture.html) |
| Adding or changing a service stack | [`docs/stack-conventions.html`](docs/stack-conventions.html) |
| Multi-host shared services (backup, autoheal, logging) | [`docs/stack-conventions.html`](docs/stack-conventions.html) + [`docs/komodo.html`](docs/komodo.html) |
| How Komodo, ResourceSync, and the two operating models work | [`docs/komodo.html`](docs/komodo.html) |
| Secrets, Komodo Variables, the `[[VAR]]` flow | [`docs/secrets.html`](docs/secrets.html) |
| dockernet, Numbat, Pomerium, rathole, DNS, and Cloudflare CDN | [`docs/networking.html`](docs/networking.html) |
| Public website caching and invalidation | [`docs/caching.md`](docs/caching.md) |
| Storage tier rule (local / Jump / Pouch) | [`docs/storage.html`](docs/storage.html) |
| Backup / restore / off-site sync | [`docs/backup-and-recovery.html`](docs/backup-and-recovery.html) |
| Gatus alerts, log pipeline, autoheal | [`docs/monitoring.html`](docs/monitoring.html) |
| Cron / ofelia jobs | [`docs/scheduling.html`](docs/scheduling.html) |
| DR rebuild runbooks | [`docs/disaster-recovery.html`](docs/disaster-recovery.html) |
| Provisioning a host; the Ansible / chezmoi boundary | [`docs/host-provisioning.md`](docs/host-provisioning.md) |
| Service-specific quirks | [`docs/runbooks/`](docs/runbooks/) |
| Current or recent migrations, design context | [`docs/plans/`](docs/plans/) |

**If you're about to modify a stack and the relevant runbook page exists,
read it first.** Plex and Paperless in particular have non-obvious
constraints (identity preservation, dockernet-only access pattern) that
aren't obvious from the compose files alone.

### Development authentication

Use `op-vault dev -- <command>` for Podhaus and personal Dev-vault work, and
`op-vault switch -- <command>` for Switch Dev-vault work only on a machine that
declares Switch development access. Bilby deliberately has no Switch identity.
A missing token, hardware backend, or vault grant is an authorization boundary.
Never invoke, request, or recommend `op-unlock`, a personal 1Password session,
or a Personal vault read unless Nathan explicitly asks for that personal
operation in the current conversation. Git, SSH, signing, and Ansible use the
machine SSH key.

---

## What podhaus is

Docker container infrastructure for **five** active hosts:
- **bilby** (Apple M1 Mac mini, primary; Fedora Asahi Linux) — runs
  Komodo Core, MinIO, Caddy, every primary service.
- **kangaroo** (QNAP NAS, QTS + Container Station) — secondary LAN
  deploy target via linked-repo Periphery.
- **numbat** (BinaryLane Perth, Rocky Linux 10, x86_64) is the active
  public gateway. Pomerium authenticates through Pocket ID; named rathole
  services carry public TLS, private mTLS origins, Forgejo/host SSH,
  outbound Periphery, and mTLS log shipping. It has no route into the LAN.
  Host state is Ansible's: `playbooks/numbat-bootstrap.yml` brings up a
  fresh VM, `playbooks/numbat.yml` is steady state.
- **fractal** (Fedora 44 under WSL2 on a Windows desktop, x86_64) is
  Nathan's remote dev machine *and* an ordinary podhaus host. Its only
  inbound path is LAN SSH — `10.0.0.70` is the Windows host, forwards only
  :22, and split-horizon `fractal.pod.haus` resolves to it on the home
  network — so it reaches the fleet exclusively by dialing out: Periphery to
  `core-connect.pod.haus`, rathole to Numbat for `fractal.docs.pod.haus`
  and `ssh://fractal`, Alloy to `logs-ingest.pod.haus`. **Provisioned by
  Ansible** rather than a bootstrap script, like numbat.
- **voltaire** (Fedora Workstation desktop, x86_64, foreign LAN) is
  Nathan's other remote dev machine and an ordinary podhaus host on the
  fractal pattern: no inbound path at all, so it dials out — Periphery to
  `core-connect.pod.haus`, a rathole client (`relay/voltaire`) carrying
  `ssh://voltaire`, Alloy to `logs-ingest.pod.haus`. Provisioned by
  Ansible (`playbooks/voltaire.yml`); its old Cloudflare tunnel and
  systemd rathole origin are gone.

Managed as Docker Compose stacks under a single Komodo Core; secrets
flow from 1Password. Protected names resolve to Numbat Pomerium; public
and raw endpoints use Numbat's second address and Caddy. Cloudflare stays
authoritative DNS and CDN for public websites. The old Podhaus Cloudflare
Tunnel, Access estate, DigitalOcean relay, and routed Tailscale management
plane have been removed. A planned host **pinelake** will use the proven
outbound Numbat contract; its existing Cloudflare setup remains until then.

---

## Architecture

- **Komodo Core** on bilby manages stacks on all active deploy hosts via per-host
  Periphery agents.
- Single-host services live in a top-level directory with `compose.yaml`
  and `stack.toml` (e.g. `paperless/`, `plex/`, `gatus/`).
- **Multi-host shared services** use `<service>/{compose.shared.yaml,
  <host>/...}`. Each host stack sets
  `file_paths = ["compose.yaml", "../compose.shared.yaml"]`; its compose
  file contains only the host-specific overlay. Pattern in use: `backup/`,
  `autoheal/`, `logging/`.
- Komodo Core and bilby's Periphery both mount the **deploy tree**, a
  Komodo-managed clone of this repo (`/etc/komodo/repos/podhaus-deploy`,
  Repo resource `podhaus-deploy` in `komodo/sync/repos.toml`) — never
  bilby's own working checkout (`~/repos/podhaus`). A push forces the
  deploy tree to `origin/main`; `./komodo-sync` instead overlays it with
  the working checkout's current state. See `docs/komodo.html`.
  Kangaroo's Periphery clones the repo itself via Komodo's Linked Repo
  feature.
- Secrets flow: **1Password Homelab vault → `komodo-op` → Komodo
  Variables → `[[VARIABLE]]` interpolation in stack environment**.
- Non-secret variables live in TOML and apply via the ResourceSync
  (`include_variables = true` on the `podhaus` sync). Global ones
  (`TZ`, `MEDIA_DIR`) live in `komodo/sync/variables.toml`;
  stack-private ones (e.g. `FENWICK_*`) live as inline `[[variable]]`
  blocks in the relevant `<stack>/stack.toml`.
  - **Exception:** `PODHAUS_CHECKOUT` is host-discovered (`= $PWD` at
    bootstrap time, varies per host), so it can't live in a TOML.
    `komodo-start` seeds it directly via the Komodo API. It's consumed
    by exactly one bind — home-assistant's UI-editable config mount,
    the one deliberate read-write checkout bind in the repo. Every
    other `${PODHAUS_REPO}` bind is fixed (declared in
    `komodo/sync/variables.toml`, pointing at the Komodo-managed
    deploy tree, not the working checkout).
  - **Caveat:** the sync runs with `delete: false` (additive only —
    flipping `delete: true` would nuke komodo-op's continuously-synced
    `OP__KOMODO__*` vars). Side effect: a variable removed from TOML
    lingers in Komodo until manually deleted via the API
    (`DeleteVariable`). See `docs/secrets.html`.
- Volumes are declared in compose without `external: true` unless they
  exist outside the stack — Docker Compose creates them on first deploy.
- `komodo-start` is bootstrap-only (Komodo Core stack up + 5
  chicken-and-egg vars + deploy-tree bootstrap + create-resource-sync +
  bootstrap double-sync). Steady-state debug iteration uses
  `komodo-sync` (overlays the deploy tree with the working checkout);
  push-to-deploy uses the `podhaus-push-deploy` procedure (pulls the
  deploy tree to `origin/main` first, then runs the internal
  `podhaus-deploy` procedure).

---

## Networking

- **`dockernet`**: bridge network at `172.18.0.0/16` for cross-stack
  communication. Containers join via `networks: [dockernet]` plus a
  top-level `networks: { dockernet: { external: true } }` block.
- **External networks are host-provisioned by the Ansible docker role**
  (`ansible/roles/docker`) — the only config-as-code path, since Komodo
  has no `CreateNetwork` execution and Compose won't adopt a pre-existing
  external network. Bilby declares `dockernet` (Komodo Core itself
  attaches to it) plus, via `podhaus_extra_networks`, the two
  Fenwick-private nets `fenwick-net` and `fenwick-webagent-net` (the
  browser-quarantine link); per-container membership stays config-as-code
  in each stack's `compose.yaml`. Fenwick's topology + rationale live in
  the fenwick repo's `docs/networking.html`.
- Containers reach each other by **container name** (Docker DNS), never
  by static IP.
- Static IPs are for LAN devices (e.g. UniFi gateway at `10.0.0.1`) or
  host-network services.
- Services needing device access (Home Assistant, Plex, Syncthing) use
  `network_mode: host`. Caddy reaches them via the dockernet
  bridge gateway at `172.18.0.1:<port>`.
- Protected names are DNS-only A records to Numbat's application IP.
  Pomerium authenticates with Pocket ID and reaches Caddy's private
  `:4443` listener through loopback rathole plus client mTLS.
- Managed devices use `<host>.pod.haus` for SSH. Chezmoi sends Bilby,
  Kangaroo, and Fractal directly on the home LAN and rewrites every other
  case through Pomerium at `ssh.pod.haus`; its route portal covers
  unmanaged devices. Kangaroo's direct SSH selection belongs in chezmoi,
  not split DNS, because HTTPS must remain behind Pomerium; fractal gets a
  split-horizon `fractal.pod.haus` A record to the Windows host (`10.0.0.70`,
  UniFi-reserved, both in Terraform) because that name is SSH-only — its
  HTTPS name `fractal.docs.pod.haus` is separate and stays on Pomerium, so
  there is no identity boundary to leak. Tailscale keeps separate
  `*-recovery` names for explicit break-glass use.
- Public and raw endpoints use Numbat's relay IP and Caddy `:4444`.
  Cloudflare proxies only public CDN sites. Pine Lake retains its
  explicitly scoped Cloudflare Tunnel resources until it moves to the
  outbound Numbat contract.
- **Do not set per-container `dns: [...]` in compose.** It replaces Docker's
  embedded resolver (`127.0.0.11`) and breaks service-name resolution such as
  `ferretdb` and `caddy`. Bilby's daemon configuration has no DNS override;
  containers use Docker DNS and the host's ordinary upstream resolver.

---

## Key files

| File | What it is |
|---|---|
| `komodo/ferretdb.compose.yaml` | Komodo Core infra (postgres, FerretDB, Core, Periphery) |
| `komodo/compose.env` | Komodo config with `op://` secret references |
| `<name>/compose.yaml` | Docker Compose file for each service stack |
| `<name>/stack.toml` | Komodo stack metadata (server assignment, environment block) |
| `komodo/sync/variables.toml` | Global non-secret variable declarations (TZ, MEDIA_DIR, and `PODHAUS_REPO` — the fixed path of bilby's Komodo-managed deploy tree). Authoritative — applied by the podhaus sync (`include_variables = true`). Stack-private vars live as inline `[[variable]]` blocks in `<stack>/stack.toml` instead. |
| `komodo/sync/servers.toml` | Server definitions (bilby, kangaroo, numbat, fractal) |
| `komodo/sync/repos.toml` | Per-host Linked Repo definitions (including `podhaus-numbat`), plus the `podhaus-deploy` Repo resource — bilby's own Komodo-managed deploy tree, fed by `podhaus-push-deploy`'s pull stage and by `komodo-sync`'s local-tree overlay. |
| `komodo/sync/procedures.toml` | Two procedures. `podhaus-push-deploy` is the GitHub webhook entrypoint: Stage 0 `PullRepo podhaus-deploy` force-pulls the deploy tree to `origin/main`, Stage 1 `RunProcedure podhaus-deploy` runs the internal procedure below. `podhaus-deploy` (webhook/schedule disabled — invoked only by `podhaus-push-deploy` and by `./komodo-sync`; deploys whatever the deploy tree currently holds) has three stages: Stage 0 RunSync (reconcile defs) → Stage 1 RunAction `podhaus-inject-content-hashes` (stamp content hashes into stored env **and** force-deploy stacks with stale hash labels — the actual config-only/build-context trigger) → Stage 2 BatchDeployStackIfChanged "*" (owns compose-text changes + new stacks; does NOT see hash changes). Ofelia `0.4.0-beta.5` follows Docker events and no longer needs a deployment-boundary restart. |
| `komodo/sync/actions.toml` | Komodo Actions invoked by procedures and by `komodo-sync`. `podhaus-load-local-tree` is `komodo-sync`'s first step: mirrors bilby's working checkout (tracked + untracked-unignored files, read-only at `/syncs/podhaus-local`) into the deploy tree at `/syncs/podhaus` via `git ls-files` enumeration on both sides, so everything downstream deploys exactly local state. `podhaus-inject-content-hashes` is Stage 1 of the internal `podhaus-deploy` procedure. For every stack visible at `/syncs/podhaus` (the deploy tree), it hashes (a) the stack directory (committed files; `.env` excluded) → `STACK_CONTENT_HASH`, and (b) each service's resolved build context → `BUILD_HASH_<UPPER_SERVICE>`; injects both into stored env. **Then it force-deploys any stack whose running container has stale `podhaus.*` labels or, for a build service, a stale baked `STACK_CONTENT_HASH`, while its compose text is unchanged**. This reconcile is the load-bearing trigger for podhaus's "any in-stack file change → recreate; any build-context change → image rebuild + recreate" property, because Komodo's IfChanged (Stage 2) only diffs compose text and never sees a hash change. `podhaus-purge-stack-cache` reads a deployed stack's `podhaus.cloudflare-cache-*` labels and purges those tags after the stack's deployment stage. See the Stage-1/content-hash notes in "When adding a new service" and [`docs/caching.md`](docs/caching.md). |
| `tools/lint-stack-content-hash.py` | Pre-commit consumer-wiring lint for the content-hash mechanism: every service has the `podhaus.stack-content-hash` label; every build service has `build.args.STACK_CONTENT_HASH` referencing its own `BUILD_HASH_<self>` + the matching `ARG`/`ENV` pair in its Dockerfile; every service that `depends_on` a build service has the `podhaus.depends-on-<dep>` label. Run via `tools/pre-commit` alongside `lint-stack-env.py`. |
| `komodo-start` | Bootstrap-only script: Komodo Core stack up, 5 chicken-and-egg vars seeded (4 `ONEPASSWORD_*` + `PODHAUS_CHECKOUT`, the host-discovered `$PWD` consumed only by home-assistant's live config bind), idempotent deploy-tree bootstrap (`CreateRepo podhaus-deploy` + `PullRepo` + poll, so `/syncs/podhaus` is populated before the first sync reads it), idempotent CreateResourceSync (with existence check), bootstrap double-sync (first sync + wait for komodo-op + second sync). Needs no sudo — host prerequisites (external networks, `/etc/komodo/ssl`, `/opt/komodo/keys`) come from `ansible/playbooks/bilby.yml`. Idempotent — safe to re-run. |
| `komodo-sync` | Steady-state debug-iterate tool, **and** the recovery path for procedure-stage edits the push webhook can't apply by itself. Step 0: `RunAction podhaus-load-local-tree` overlays the deploy tree with bilby's working checkout's current state (tracked + untracked-unignored). Step 1: unfiltered `RunSync(podhaus)` directly via the API (out-of-procedure, so Komodo's `resource::update::<Procedure>` busy guard doesn't fire — procedure-definition changes land cleanly here, surgically — only stacks whose files actually changed get redeployed), now reading the overlaid tree. Step 2+: invokes `podhaus-deploy` (deliberately **not** `podhaus-push-deploy` — that procedure's own first stage would pull the deploy tree back to `origin/main` and clobber the overlay step 0 just wrote) + `fenwick-push-deploy` + `pets-push-deploy` + `docs-push-deploy` procedures (whose own Stage 0 RunSync is now a no-op because step 1 already reconciled state). Use when iterating locally without pushing, or after a push that touches `komodo/sync/procedures.toml`. |
| `tools/lint-stack-env.py` | Pre-commit env-lint: walks every `<stack>/stack.toml`'s `environment` block, verifies each key is referenced in compose. |
| `tools/lint-stack-toml.py` | Pre-commit lint: rejects `deploy = true` on any podhaus-tagged stack. See "Hard rules" for why — Komodo's `Sync Deploy` sub-stage in `RunSync` would auto-deploy on Stage 0 and break on transient linked-repo timeouts. |
| `mise.toml` + `Pipfile` | Current stable Python and Pipenv plus the unpinned Python tooling dependencies. Bootstrap with the commands in `README.md`; no lock file is kept. |
| `tools/pre-commit` | The pre-commit hook runner. Invokes `lint-stack-env.py` + `lint-stack-content-hash.py` + `lint-stack-toml.py` through Pipenv. Install with `ln -sf ../../tools/pre-commit .git/hooks/pre-commit` so future edits to the hook are live. |
| `komodo-stop` | Stop Komodo Core |
| `komodo-status` | Show Komodo Core container status |
| `komodo-upgrade` | Pull latest images + restart Komodo |
| `ansible/roles/nfs_binds/` | bilby's NFS-bind hardening and stopped-container recovery: a recurring systemd timer starts only opted-in `created`/`exited` containers whose retained OCI error names an unavailable Jump/Pouch bind after that exact export is healthy again; `StartLimit*=0` drop-ins keep the automount units retryable; the `chattr +i` tripwire protects bare `/mnt/{pouch,jump}`; share sentinels prove the expected exports; and the role owns Forgejo directory ownership plus `/boot/efi`'s fsck pass number. Apply via `ansible-playbook playbooks/bilby.yml` (tag `nfs`). See [`docs/postmortems/2026-08-22-delayed-nfs-container-recovery.md`](docs/postmortems/2026-08-22-delayed-nfs-container-recovery.md). |
| `ansible/roles/firewalld/` | **Source of truth for bilby's firewalld** (absorbed the deleted `bilby/firewalld/`) — `files/zones/public.xml` (LAN `end0` zone) + `files/services/*.xml` (custom port groups). The role installs services, then the zone, runs `firewall-cmd --check-config`, then reloads. **Never** run `firewall-cmd --add-*` (even `--permanent`) — it diverges from the role files and the next play run reverts it; edit the XML and re-run `ansible-playbook playbooks/bilby.yml` (tag `firewall`). The `public` zone trusts the whole home LAN (`10.0.0.0/24 → accept`), so LAN-only services need no explicit rule; services reached from dockernet get an explicit service XML (plex, music-assistant). See [`docs/hosts.html#bilby-firewall`](docs/hosts.html#bilby-firewall). |
| `iot/` | **Devices bridged into Home Assistant** — BLE/RF remotes, plus purpose-built hardware such as the grasshopper LED strip switch. One subdirectory per bridging system: `iot/esphome/` (the ESPHome dashboard stack plus one config-as-code YAML per physical device in `iot/esphome/config/`) and `iot/pizero/` (a systemd unit and install script for flicd on the Pi Zero, which bridges the Flic buttons — **not** a Komodo stack, because ARMv6 has no Docker; see [`docs/runbooks/pizero.md`](docs/runbooks/pizero.md)). Device YAMLs are flat in that directory because the ESPHome dashboard only lists configs at its config root. Firmware is built and OTA-pushed from the dashboard; `secrets.yaml` is rendered at deploy time by `esphome-init` from the 1Password Homelab item **ESPHome** and is never in the checkout. The matching Home Assistant automations live in `home-assistant/config/automations.yaml` alongside the other remotes, not in a package. Button *behaviour* is HA-side — firmware emits `event` entities and knows nothing about lights or scenes. Firmware does own link health: a connection-state BLE watchdog plus diagnostic entities exported as OpenMetrics for bilby's Alloy to scrape into HyperDX (`service.name = esphome`). A new device needs a UniFi DHCP reservation and a scrape target, or the scrape dies silently on the first DHCP drift. See [`docs/runbooks/ble-remotes.md`](docs/runbooks/ble-remotes.md) for the remotes and the shared dashboard/deploy flow, and [`docs/runbooks/led-strip-grasshopper.md`](docs/runbooks/led-strip-grasshopper.md) for the LED strip switch. |
| `ansible/` | **Host provisioning — the machine half of a host.** Roles for base packages, WSL, Docker engine/daemon + host-provisioned networks, the developer toolchain, Komodo Periphery, Komodo Core's host directories (`komodo_core_host`), Pomerium SSH CA trust, NFS-bind hardening (`nfs_binds`), firewalld, and numbat's edge (`numbat_edge`: dual-address nftables + relay-IP dispatcher as jinja templates fed from 1P-published addresses). Ansible owns root state; chezmoi owns `$HOME`; the boundary is "needs sudo" and it means chezmoi never prompts for a password. **fractal**, **bilby**, **numbat**, and **voltaire** are the `provisioned` group that `site.yml` targets (numbat keeps `playbooks/numbat-bootstrap.yml` for a fresh VM and `playbooks/numbat.yml` as its single-host entry point, reached through Pomerium; voltaire's is `playbooks/voltaire.yml`); kangaroo is permanently `excluded` (QTS has no Python — `kangaroo_bootstrap` covers it, including Pomerium SSH CA trust). **Not wired into push-to-deploy:** host state changes when a human runs a playbook, never on a push. Read `--check --diff` and audit every delta before a real run against a loaded host; second run must report `changed=0`. See [`docs/host-provisioning.md`](docs/host-provisioning.md). |
| `fractal/periphery/`, `voltaire/periphery/` | The dev hosts' bootstrap-managed outbound Peripheries, dialing `wss://core-connect.pod.haus`. Installed by the `komodo_periphery` Ansible role, not by a script. |
| `relay/fractal/`, `caddy/fractal/`, `logging/fractal/` | fractal's outbound ingress + observability: rathole client → Numbat (`fractal_http` → `127.0.0.1:8444`, `fractal_ssh` → `127.0.0.1:2204`), Caddy mTLS origin on `:4443`, Alloy to `logs-ingest.pod.haus`. The `fractal-docs` stack (docs-server over `~/repos`) is defined in the **docs repo's** `stack.toml`, beside its compose. |
| `relay/voltaire/`, `logging/voltaire/`, `autoheal/voltaire/` | voltaire's outbound ingress + observability on the fractal pattern: rathole client → Numbat (`voltaire_ssh` only — no HTTPS service), Alloy to `logs-ingest.pod.haus`, autoheal. All linked-repo (`podhaus-voltaire`); the Fedora Workstation host runs SELinux enforcing, so every bind-mounting service carries `security_opt: [label:disable]`. |
| `kangaroo_bootstrap` | One-time kangaroo Periphery bring-up |
| `ansible/playbooks/numbat-bootstrap.yml` + `ansible/playbooks/numbat.yml` | Numbat's two plays. The bootstrap play (fresh VM only, run from bilby) pins Terraform's 1P-published host key for first contact, connects on first-boot port 2222, stages the `numbat_edge` firewall without activating it, starts rathole before outbound Periphery, enrolls the userspace SSH recovery daemon, then loads the final ruleset and closes 2222 last. The steady-state play (base, docker, numbat_edge, sshd_pomerium_ca, komodo_periphery) reaches the host through Pomerium and is what check-mode equivalence proves. Numbat application stacks are Komodo-managed. |
| `tailscale-recovery-bootstrap` | Host-native, userspace-mode Tailscale recovery bootstrap for bilby, numbat, and kangaroo. It publishes only loopback OpenSSH through Tailscale Serve on TCP 22; no host route, DNS override, TUN, or container socket/state exposure. |
| `terraform/` | The ONE consolidated Terraform root for the whole fleet. It owns BinaryLane/Numbat, Cloudflare DNS/CDN/AOP, Pine Lake's current Cloudflare edge, UniFi DNS, GitHub deploy webhooks, the SSH-only Tailscale recovery plane, MinIO IAM, Pocket ID, edge PKI, and 1Password handoffs. State is in MinIO via public `https://storage.pod.haus`; run stock `terraform` directly. |
| `minio/` | Single-node MinIO — S3 backend for Terraform state + public S3 (per-site static hosting) via `storage.pod.haus`. |
| `caddy/` | Bilby's split origin: private mTLS `:4443` for Pomerium, public-only `:4444` for Numbat raw/CDN endpoints, and `:443` for LAN routes. |
| `relay/` | Outbound rathole clients on internal hosts and the Numbat server. Services are individually tokened and use Noise transport. |
| `pomerium/` | Pomerium Core on Numbat: Pocket ID browser policy, scoped machine exceptions, native SSH, private-origin client mTLS, and persistent replaceable Autocert cache. Includes the `ssh-auth-notify` sidecar, which pushes parked SSH sign-in links to the key owner's Signal via fenwick (see `docs/networking.html#ssh-auth-notify`); fingerprint→owner routing lives as variables in `pomerium/stack.toml`. |
| `forgejo/` | Local Git hosting on bilby. Pomerium protects HTTPS; a raw Numbat rathole owns ordinary `git@git.pod.haus` SSH. Forgejo retains native Pocket ID OIDC and key synchronization. |
| `numbat/periphery/` | Numbat's outbound Periphery compose, dialing the exact public `wss://core-connect.pod.haus/ws/periphery` connector with Komodo Noise keys. Installed by the `komodo_periphery` Ansible role, not by Komodo. |
| `logging/numbat/` | Alloy ships to `logs-ingest.pod.haus` through rathole and Caddy with per-host mTLS. |
| `docs/` | This repo's docs, served by the central docs-server at `docs.pod.haus`. Author as Markdown (HTML for layout); conventions in `~/repos/docs/docs/authoring.md`. |
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
   and the only seed it still owns is host-discovered `PODHAUS_CHECKOUT`.
5. **Push the commit.** The webhook fires `podhaus-push-deploy`, which
   pulls bilby's Komodo-managed deploy tree to `origin/main`
   (`PullRepo podhaus-deploy`) and then runs the internal
   `podhaus-deploy` procedure. Its Stage 0 RunSync registers the new
   stack + any new variables; Stage 2 `BatchDeployStackIfChanged "*"`
   deploys it (the `(None, _) => DeployIfChangedAction::FullDeploy`
   path covers brand-new stacks regardless of the `deploy` flag). No
   manual UI click. For local iteration without pushing, `./komodo-sync`
   overlays the deploy tree with the working checkout's current state
   and invokes `podhaus-deploy` directly — identical downstream
   behaviour, no commit/push round-trip. **Do not set `deploy = true`**
   in the new `stack.toml` — see Hard Rules.
6. **Nothing to do for push-to-deploy.** There is ONE GitHub `push`
   webhook for the whole repo; it drives the `podhaus-push-deploy`
   Komodo Procedure (`komodo/sync/procedures.toml`), which force-pulls
   bilby's Komodo-managed **deploy tree**
   (`/etc/komodo/repos/podhaus-deploy`) to `origin/main`
   (`PullRepo podhaus-deploy`) and then runs the internal
   `podhaus-deploy` procedure — source-agnostic, it just deploys
   whatever the deploy tree currently holds, whether that's a fresh
   pull from a push or (via `./komodo-sync`) an overlay of the working
   checkout. Bilby's own working checkout (`~/repos/podhaus`) is never
   read by either pipeline path. Four stages inside `podhaus-deploy`:
   **Stage 0** `RunSync "podhaus"` reconciles stack defs + TOML-declared
   variables from disk into Komodo's stored resource state (so a push
   that adds/changes an `environment` line or a `[[variable]]` block
   reaches the deploy correctly — without this, the deploy uses the
   pre-sync stored env and renders `${VAR}` empty). Stage 0 is
   **config-reconcile-only**: every podhaus `stack.toml` omits the
   `deploy` flag (defaults to `false`), so Komodo's `Sync Deploy`
   sub-stage inside RunSync — which auto-deploys any stack whose
   config differs from deployed, no-ops on podhaus stacks. RunSync is
   reconcile-only; Stages 1 and 2 own deployment. Without this, a single linked-repo
   Periphery timeout inside `Sync Deploy` would fail Stage 0 and abort
   Stages 1–3 entirely; bit kookaburra-relay/kookaburra-tailscale on
   2026-05-25 (~24 h stale until investigation). **Stage 1**
   `RunAction "podhaus-inject-content-hashes"` walks every stack
   visible at Komodo Core's `/syncs/podhaus` mount and appends two
   kinds of env entries to each stack's stored environment:
   `STACK_CONTENT_HASH=<hash>` (hash of the stack's own directory),
   and one `BUILD_HASH_<UPPER_SERVICE>=<hash>` per service that has a
   `build:` directive (hash of the resolved build context — may live
   outside the stack dir, e.g. shared `init-tools/` or `relay/`). The
   hashes are derived from the deploy tree's current state (so they
   work uniformly for files_on_host AND linked_repo stacks). **The injected
   env is necessary but is NOT a deploy trigger on its own.** Komodo's
   `DeployStackIfChanged` decides "changed" by diffing the compose-file
   *text* it stored at deploy time — and the hashes live in
   `${STACK_CONTENT_HASH}` / `${BUILD_HASH_*}` variable refs, so a hash
   change never alters that text (proven 2026-06-18: a conf-only edit
   injected the right hash but Stage 2 no-op'd, leaving gatus on a stale
   config; see the content-hash note below). So **Stage 1 also does the
   actual triggering**: after injecting, it reads each stack's running
   containers and force-deploys any whose `podhaus.*` hash labels are
   stale *while the compose text is unchanged* — exactly the config-only
   (`conf/`, `scripts/`) and build-context changes Stage 2 can't see.
   **Stage 2** `BatchDeployStackIfChanged "*"` then owns the rest:
   compose-text changes (its IfChanged fires on those) and brand-new
   stacks (`(None, _) => FullDeploy`, verified against
   `bin/core/src/api/execute/stack.rs:368-447`). The two paths are
   disjoint — Stage 1 only deploys *compose-unchanged* stacks — so
   nothing double-recreates. Ofelia is pinned to `0.4.0-beta.5`, whose
   Docker-event reload applies added, replaced, and removed job labels
   without a scheduler restart. Do **not** set `webhook_force_deploy` — there are no
   per-stack webhooks for it to affect; linked-repo stacks now flow
   through the same Stage 2 IfChanged path as everything else.

   **Content-hash change detection — what counts and what doesn't.**
   `STACK_CONTENT_HASH` covers every *committed* file in the stack
   directory (including bind-mounted runtime paths like `<stack>/scripts/`
   or `<stack>/conf/`). The trade-off is that a script edit triggers a
   container recreate even where the script is also live-mounted; we
   chose this for the "make a change → see the change" invariant
   over more precise but per-stack-configured exclusions. **`hashDir`
   excludes the deploy-written `.env`** — Komodo writes a rendered `.env`
   (resolved secrets + the just-stamped `STACK_CONTENT_HASH`) into each
   stack's run_directory at deploy time, so hashing it would make the
   hash depend on its own previous output (never converges) and fold
   secret values into the trigger. Consequence: a **secret rotation or a
   `variables.toml` (`TZ`/`MEDIA_DIR`) change does NOT auto-redeploy** —
   only committed in-stack content does. (Catching rotations would mean
   hashing the *currently-resolved* env, not `.env`, which lags until the
   next deploy — a deliberate non-goal.) Per-service `BUILD_HASH_<svc>`
   additionally covers the resolved build context for any service with
   `build:` — including contexts outside the stack dir (shared
   `init-tools/`, `relay/`). The two hashes are consumed via different
   conventions:

   - **Every service** has a `podhaus.stack-content-hash` label that
     references `${STACK_CONTENT_HASH:-unset}`. **This label is the
     ground truth for in-stack content** that Stage 1 reads to decide whether the
     running container is stale — NOT a trigger by itself. (Compose
     *does* fold the label into its per-service config-hash, so when a
     deploy actually runs, a changed label forces the recreate; but
     nothing makes that deploy run except the Stage-1 reconcile —
     Komodo's IfChanged never sees the env. This was the long-standing
     latent bug, dormant because compose-text edits happened often
     enough to refresh labels as a side effect. Fixed 2026-06-18.)
   - **Build-mode services** additionally have
     `build.args.STACK_CONTENT_HASH: ${BUILD_HASH_<SELF>:-unset}` in
     compose, and an `ARG STACK_CONTENT_HASH=unset` + `ENV
     STACK_CONTENT_HASH=${STACK_CONTENT_HASH}` pair in their Dockerfile.
     A different ARG value produces a different layer fingerprint from
     that point down — docker's build-layer cache busts on
     build-context change. Stage 1 compares that baked environment value
     with the fresh build-context hash, which is the build service's
     force-deploy trigger when compose text is unchanged.
   - **Services that depend on a build service** have a
     `podhaus.depends-on-<dep>: ${BUILD_HASH_<DEP>:-unset}` label per
     dependent. Without this, an init image rebuild wouldn't recreate
     the long-running service that depends on it, so the new init
     output (rendered configs, etc.) wouldn't be picked up.

   The producer side is the Action; the consumer side is what
   `tools/lint-stack-content-hash.py` enforces at commit time. Service
   names with non-alphanumerics get translated for the variable name:
   uppercased, non-alnum → underscore. So `plex-preferences-init` →
   `BUILD_HASH_PLEX_PREFERENCES_INIT`.

   **Caveat — edits to `komodo/sync/procedures.toml` need a follow-up
   `./komodo-sync` to land.** Komodo's `resource::update::<Procedure>`
   has an explicit busy guard: a procedure can't be modified while
   it's running. So when a push includes a procedure-stage edit, the
   internal `podhaus-deploy` procedure's own Stage 0 RunSync — invoked
   from `podhaus-push-deploy`'s `RunProcedure` stage, so both
   procedures are still "running" up the call chain — tries to update
   either procedure's definition, hits the busy guard, the sync loop
   bails after 10 retries with a generic "max iterations" error, and
   the procedure aborts (the per-iteration error is silently discarded
   by Komodo's sync loop, so the failure is opaque). Stack/variable
   updates inside Stage 0 still succeed via the sync's deploy
   sub-stage, but the remaining stages don't run. The recovery is a
   single `./komodo-sync` invocation: its step 1 calls `RunSync(podhaus)`
   directly via the API — out-of-procedure, so the busy guard doesn't
   fire — applies the procedure change, then triggers the procedures
   normally. Pushes that DON'T touch procedures.toml apply fully via
   the webhook with no manual step.
7. If the service is a single-host pod.haus service, add a
   DNS entry to `local.pod_haus_service_dns` in
   `terraform/services_pod_haus.tf`, add the protected
   route to `pomerium/config.yaml`, and add its private-origin host to
   `caddy/Caddyfile`. Podhaus services do not get Cloudflare Tunnel or
   Access resources.
   Run `op-vault dev -- op run --env-file=terraform/terraform.env.op --
   terraform -chdir=terraform apply` to publish from a Podhaus operator.

## When adding a new instance of a shared service to another host

Multi-host services already in this layout: `backup/`, `autoheal/`,
and `logging/`. Each has `<service>/compose.shared.yaml` plus per-host
subdirs.

1. Create `<service>/<host>/compose.yaml` with only the host-specific
   overlay, then set
   `file_paths = ["compose.yaml", "../compose.shared.yaml"]` in its
   `stack.toml`.
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
  documented in `/docs/terraform.html`; the single-root design
  exists deliberately to keep the surface small and reject the
  "this is bilby-only / admin tooling" carve-out rationale.
  No host-pinned backend endpoint (the S3 state backend uses
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
  per-site service accounts), not network filtering.
- **Never use single-file bind mounts** for any config the running
  service reads after startup. File-level binds pin the inode at mount
  time, so atomic-rename editor saves on the host leave the container
  pointed at the orphan original forever. Always bind the containing
  directory. The exception is init containers that read the file once at
  startup and exit — those are fine. See
  [`docs/stack-conventions.html#bind-mounts`](docs/stack-conventions.html).
- **Config-only commits to in-stack files DO recreate the container —
  via the Stage-1 reconcile, not via compose.** On its own,
  `docker compose up -d` / Komodo's `DeployStackIfChanged` is a no-op
  when the compose *text* is unchanged: it pulls the new bind-mounted
  file but leaves the running process on the cached old config. The
  `podhaus-inject-content-hashes` action closes this (since 2026-06-18):
  any change to a committed in-stack file (`<stack>/conf*/`,
  `<stack>/*-conf/`, `caddy/conf*/`,
  `alloy-conf/`, `<stack>/scripts/`, etc.) changes `STACK_CONTENT_HASH`,
  the action sees the running container's `podhaus.stack-content-hash`
  label is stale, and force-deploys → the container is recreated and the
  process re-reads its config. **Caveats:** (a) it's a *recreate* (full
  restart), not an in-place reload — fine for startup-read config; if you
  specifically want a graceful SIGHUP instead of a restart, that's a
  separate manual step; (b) only the push procedure / `komodo-sync`
  triggers it (not a bare `docker compose up -d`); (c) it does NOT cover
  secret / `variables.toml` value changes — the hash excludes the
  deploy-written `.env` (see the content-hash note in "When adding a new
  service"). Before 2026-06-18 this was all-manual and bit
  kookaburra-logging in 2026-05. Full table:
  [`docs/stack-conventions.html#bind-mounts`](docs/stack-conventions.html).
- **Never create Komodo Variables in the UI.** They don't survive a
  fresh Komodo bootstrap. Put the secret in 1Password and reference the
  `OP__KOMODO__*` synced variable name. See
  [`docs/secrets.html`](docs/secrets.html).
- **Never set `deploy = true` on a podhaus `stack.toml`.** Komodo's
  `RunSync` has a built-in `Sync Deploy` sub-stage that auto-deploys
  any stack whose stored config differs from deployed — `deploy = true`
  is the opt-in. That sub-stage (a) duplicates Stage 2's
  `BatchDeployStackIfChanged` work and (b) runs serially with no
  per-stack failure tolerance, so a transient kookaburra-Periphery
  timeout fails the whole RunSync and aborts Stages 1–3. With `deploy`
  omitted (defaults to `false`, per Komodo source
  `client/core/rs/src/entities/toml.rs`), the Sync Deploy sub-stage
  no-ops on the stack. First-deploys still work via Stage 2's
  `(None, _) => FullDeploy` path in `DeployStackIfChanged`, which
  ignores the flag entirely (verified against
  `bin/core/src/api/execute/stack.rs:368-447`). The lint
  `tools/lint-stack-toml.py` rejects `deploy = true` on podhaus stacks
  at commit time. (`vpn-diagnostics` is the only stack that
  intentionally carries `deploy = false`; for podhaus stacks just
  omit the field.)
- **Linked Repo hosts (kangaroo, numbat, fractal, voltaire, future pinelake) use the
  same four-stage procedure as bilby.** Komodo v2 semantics:
  `DeployStack` `git pull`s the linked clone before composing;
  `RestartStack` does not pull (it only `docker compose restart`s).
  Komodo's native `DeployStackIfChanged` sees compose-text changes,
  but it does not see a changed value behind a `${VAR}` reference. The
  internal `podhaus-deploy` procedure (invoked by `podhaus-push-deploy`
  after pulling the deploy tree to `origin/main`, and directly by
  `komodo-sync` after overlaying it with the local checkout) closes
  that gap via its Stage 1 `RunAction "podhaus-inject-content-hashes"`:
  the Action computes hashes from the deploy tree's current state and
  stamps `STACK_CONTENT_HASH=<hash>` + per-service
  `BUILD_HASH_<svc>=<hash>` into each stack's stored env. It then reads
  the running containers' `podhaus.*` labels and directly force-deploys
  a stale stack when its compose text is unchanged. Stage 2 owns the
  disjoint cases: compose changes and new stacks. New linked_repo
  stacks are picked up automatically by the wildcard; **no per-host
  force-deploy patterns to maintain, no `webhook_force_deploy` on
  individual stacks, and no `<host>-` naming contract** (the prefix is
  a readability convention, not a deploy-routing contract). Stage 0
  `RunSync` re-imports `stack.toml` config + TOML-declared variables
  from the deploy tree's bind-mount; any `DeployStack` does the per-host `git pull`
  on the linked-repo Periphery as part of its normal flow. Always
  confirm a deploy via a config-level signal (the
  pulled-to hash / a metric), never "container healthy". See
  [`docs/komodo.html#operating-models`](docs/komodo.html).
- **Always use absolute host paths in bind mounts.**
  `${PODHAUS_REPO}/<stack>/...`, never relative paths. Relative paths
  resolve against the periphery container's filesystem, not the host's,
  and Docker silently creates empty stub directories.
- **NFS-bind containers need a sentinel healthcheck; bare mount points
  need the `chattr +i` tripwire.** Any container that binds Pouch
  (`/mnt/pouch`) or Jump (`/mnt/jump`) — flood, plex,
  paperless, backrest today — must healthcheck via
  `[ -e <bind>/.podhaus-share-mounted ]` (the sentinel exists on the
  QNAP share; absent if the bind landed on a bare local-disk stub).
  Wrapping in `timeout N` bounds the soft-NFS-stall case. Do not
  healthcheck via `grep " /path " /proc/mounts` alone — Docker creates
  a bind entry regardless of source state, so `/proc/mounts` presence
  false-greens on stub-shadowed binds. The host complement is
  `chattr +i` on bare `/mnt/pouch` and `/mnt/jump` — if NFS isn't
  mounted, Docker's auto-create of bind-source subdirs fails loudly at
  container start. With NFS mounted, the bit is irrelevant (NFS
  supersedes the btrfs dir). When you add a stack that binds a new
  sub-path under Pouch/Jump, drop a marker first
  (`sudo touch /mnt/<share>/<subpath>/.podhaus-share-mounted`). Bit
  flood/plex/paperless/backrest in 2026-05; see
  [`docs/postmortems/2026-05-23-pouch-jump-mount-failure.md`](docs/postmortems/2026-05-23-pouch-jump-mount-failure.md)
  +
  [`docs/stack-conventions.html#nfs-bind-healthcheck`](docs/stack-conventions.html).
- **Don't push, deploy, or change DNS / Access policy without explicit
  user authorization.** Treat all `git push`, `./komodo-sync`, and
  any `terraform apply` against `terraform/` as actions that require a
  green light. `terraform plan` is fine. Note that every `git push` to `main` fires
  the single GitHub webhook (`terraform/github.tf` →
  `komodo.pod.haus/listener/github/procedure/podhaus-push-deploy/main`),
  which force-pulls bilby's Komodo-managed deploy tree
  (`/etc/komodo/repos/podhaus-deploy`) to `origin/main`
  (`PullRepo podhaus-deploy`) and then runs the internal
  `podhaus-deploy` procedure: Stage 0 `RunSync "podhaus"` reconciles
  stack defs + TOML-declared variables; Stage 1 `RunAction
  "podhaus-inject-content-hashes"` stamps a per-stack content hash
  into each stack's stored env; Stage 2 `BatchDeployStackIfChanged
  "*"` redeploys every stack whose tracked files actually changed
  (any file in the stack dir, including bind-mounted config paths,
  plus any service's build context) — same path
  for files_on_host and linked_repo. Ofelia follows the resulting
  Docker events and reloads job labels itself. Push is not cheap and not a no-op — treat it as a
  deploy.
- **Before adding or modifying a Cloudflare / UniFi / GitHub TF
  resource, read the provider's resource doc.** Schemas change
  between minor versions and `terraform apply` errors with "Attribute X
  required" or similar without making it obvious which version you
  need. Provider doc URLs are linked from each provider's required_providers block in `terraform/backend.tf`.
- **Use the current stable release by default.** Do not introduce a
  version or digest pin merely for reproducibility. Every image pull,
  package install, build, and host bootstrap is an opportunity to take
  an available upgrade. A temporary compatibility pin needs a concrete,
  documented reason and should be removed the next time that component
  is touched and the current release can be verified.
- **Don't bypass git hooks (`--no-verify`, etc.) without explicit
  permission.** Same for force-push, hard reset, branch deletion.
- **Komodo Core ↔ Periphery uses v2 X25519 noise-handshake PKI auth
  (no shared passkey).** Private keys live in `/opt/komodo/keys/` on
  bilby (Core's + bilby Periphery's) and on each Periphery host's keys
  dir (kangaroo/numbat/fractal). Pubkeys are checked in at
  `komodo/keys/*.pub`. Never commit a `*.key` file; the
  `komodo/keys/.gitignore` defends against it. To add a new Periphery
  host: generate its keypair on bilby (openssl in alpine container, see
  `docs/komodo.html#auth`), SCP the privkey to the new host's keys dir,
  drop its pubkey in `/opt/komodo/keys/` + `komodo/keys/<host>.pub`,
  and append `file:/config/keys/<host>.pub` to
  `KOMODO_PERIPHERY_PUBLIC_KEYS` in `komodo/compose.env`.
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
- [Host provisioning](docs/host-provisioning.md)
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
- [BLE remotes](docs/runbooks/ble-remotes.md)
- [Bugsink](docs/runbooks/bugsink.html)
- [Forgejo](docs/runbooks/forgejo.md)
- [Grasshopper LED strip](docs/runbooks/led-strip-grasshopper.md)
- [Home Assistant](docs/runbooks/home-assistant.md)
- [Mumble](docs/runbooks/mumble.md)
- [Music Assistant + doorbell](docs/runbooks/music-assistant.html)
- [pizero](docs/runbooks/pizero.md)
- [Pocket ID](docs/runbooks/pocket-id.md)
- [Pouch MinIO](docs/runbooks/pouch-minio.md)
- [StreamFab publish](docs/runbooks/streamfab-publish.html)

**Plans**
- [All plans](docs/plans/)
- Plans can be authored as `.md`, `.html`, or as a directory containing
  `index.md` plus sub-pages for a larger, active workstream.

**Postmortems**
- [All postmortems](docs/postmortems/)
- [How we write postmortems](docs/postmortems/conventions.md): when to
  open one, structure, action-item discipline.

---

## Postmortems

Incident records — one file per incident, written when something
user-visible broke or a near-miss surfaced a latent defect. Action
items live in each postmortem's Resolution section as dated checkboxes
that get flipped to done in-place as they land, rather than spawning
follow-up postmortems. Conventions:
[`docs/postmortems/conventions.md`](docs/postmortems/conventions.md).

- **2026-08-22 — delayed-nfs-container-recovery** — a hard power reset brought Bilby back before QNAP NFS; the finite pre-Docker wait timed out, Flood and StreamFab parked on OCI bind failures after storage later recovered, and stable Ofelia retained a schedule without their jobs. Manual starts plus an Ofelia restart exposed a second latent failure: Claude Code's `Write` bug had created six tracked files as `0600`; Git hid that local difference and the deploy mirror preserved it into a root-owned tree, making two uid-1000 job scripts unreadable. The six modes were corrected manually; that is the complete resolution, with no ongoing permission-regression work. EFI was also dirty because its fstab pass number disabled boot checking. No data loss; all non-Yiayia services recovered. The completed prevention replaces the finite gate with recurring, exact-mount-aware reconciliation for narrowly eligible `created`/`exited` containers, enables normal systemd EFI checking, pins Ofelia `0.4.0-beta.5`, removes its deployment restart workaround after live event-reload validation, and corrects Backrest's missing scheduler opt-in. [`docs/postmortems/2026-08-22-delayed-nfs-container-recovery.md`](docs/postmortems/2026-08-22-delayed-nfs-container-recovery.md)

- **2026-08-09 — turn-touch-ble-link-wedge** — a child spam-pressed all four buttons on the burrow Turn Touch; HA kept up (lights still changing state at the last event), then the remote stopped transmitting and its BLE link died for **5h09m** until the cell was physically reseated. Every connect attempt returned `ESP_GATT_CONN_FAIL_ESTABLISH` and hand-pressing the buttons produced no advertisement, so the remote was silent, not merely unreachable. **Nothing detected it**: the four button `event` entities are `template` entities on the ESP32, so they report the *bridge's* health and stayed `available` throughout while the ESP32 sat up, on wifi, answering HA's API. No error, no alert; the sole trace anywhere was `sensor.turn_touch_burrow_battery` going `unknown` (NAN from a failed GATT read) at the next 30-min poll, consumed by nothing. The device had no observability of its own either — logs shipped nowhere, no link-state/notification/RSSI/heap entity — so diagnosis was done by querying HA's recorder SQLite after the fact. Fixed with a connection-state BLE watchdog (deliberately *not* press-timeout, which would spend the coin cell proving liveness every quiet night), diagnostic entities exported as OpenMetrics and scraped by Alloy into ClickStack, and a UniFi reservation pinning the scrape target. Remediation surfaced a second trap now in the runbook: the esphome container's `/config` is a volume seeded at deploy, **not** a bind mount, so compiling straight after a repo edit silently builds the previously-deployed YAML while the OTA still reports success. **Alerting is still open** — metrics exist, nothing pages. [`docs/postmortems/2026-08-09-turn-touch-ble-link-wedge.md`](docs/postmortems/2026-08-09-turn-touch-ble-link-wedge.md)

- **2026-08-08 — bilby-oom-session-teardown** — bilby hit a global OOM with swap already 100% full; an ESPHome build (9× concurrent `cc1plus`, ~1.2 GB unswappable) was the trigger. The kernel spent five kill cycles on processes averaging <3 MB — including the `user@1000.service` manager (`OOMScoreAdjust=100`) — freeing ~13 MB before `clickhouse-serv` (884 MB) actually ended it. Killing the user manager tore down the whole unit: tmux server, 5 fish, 4 claude, docker. Symptom was "tmux died, no obvious cause"; nothing logs the word tmux. Containers were fine (clickhouse + pocket-id auto-restarted in ~1 s; ingestion dipped 7% for one bucket). The lasting damage was silent: `user@1000.service` has no `Restart=` and logind won't restart it while sessions exist, so it sat `failed` for 2h32m and `machine-ssh-agent` stayed dead — no SSH off bilby at all. Separately fractal's Alloy exhausted its `max_elapsed_time = "30m"` retry budget and stopped exporting permanently while reporting `healthy` (2h41m of logs lost) — **notable because that bounded retry IS the 2026-06-19 fix**, here acting as the outage mechanism. Fixed with a `user@.service.d/` restart drop-in (verified by SIGKILL) + an Alloy restart. The session-expendable OOM ordering is intentional and stays. [`docs/postmortems/2026-08-08-bilby-oom-session-teardown.md`](docs/postmortems/2026-08-08-bilby-oom-session-teardown.md)

- **2026-06-19 — alloy-exporter-keepalive-wedge** — kangaroo's Alloy OTLP exporter went silently stale for 68 min (Gatus staleness alert fired). Running, healthy, dockernet-attached, collector reachable, zero error logs — a true wedge. Root cause: kangaroo/kookaburra push cross-network to a fixed IP behind bilby's published `:4318` + NAT; when the `clickstack-otel` collector container recreated (a `clickstack/` edit bumped the whole stack's content hash), the old keepalive TCP connection stayed conntrack-mapped to the dead container and the next send blackholed and hung silently — and `retry_on_failure max_elapsed_time="0s"` (a prior fix for the *opposite* wedge) made it permanent. bilby never wedges because it ships in-network by container name (DNS re-resolves) — the asymmetry was the diagnostic key. No data loss beyond the 68-min log gap. Fixed with `disable_keep_alives = true` + a bounded 30m retry on both cross-network exporters' `config.alloy`; validated by recreating the collector and confirming kangaroo shipped across it. A second auto-heal mechanism was declined (root cause fixed; in-container detection impossible on a low-volume host). [`docs/postmortems/2026-06-19-alloy-exporter-keepalive-wedge.md`](docs/postmortems/2026-06-19-alloy-exporter-keepalive-wedge.md)

- **2026-06-16 — firmware-reboot-recovery** — QTS firmware auto-update (a recurring event) rebooted kangaroo. The `autorun.sh` hook brought the CS Docker engine back, but `backrest`+`alloy` (on `dockernet`) lost the network-attach race at boot and stayed `exited`, and `flood` (bilby) was wedged to `exited` by an autoheal restart-storm during the kangaroo NFS outage. The shared blind spot: an `exited` container with unchanged config is recovered by nothing — the restart policy is suppressed after an explicit `docker restart`, autoheal only watches *running* unhealthy containers, and Komodo IfChanged needs a content change. No data loss (NAS stayed up; host-plane tripwire/sentinels untouched); ~29 h container-plane degradation. Fixed via a kangaroo autorun reconcile (clear stale endpoint → `docker start` exited unless-stopped containers), a 15-min patient healthcheck window (`retries 3→15`) on the four NFS-bind consumers so a transient NFS outage doesn't trigger autoheal, and codifying the `chattr +i` tripwire + share sentinels into `bilby/host-systemd/install.sh`. A broad Bilby periodic reconcile was declined; the later 2026-08-22 incident added a narrower OCI/NFS-specific reconciler. [`docs/postmortems/2026-06-16-firmware-reboot-recovery.md`](docs/postmortems/2026-06-16-firmware-reboot-recovery.md)

- **2026-05-30 — power-outage-nfs-recovery** — Household power outage; bilby reboot fired automount triggers before the LAN route to QNAP was usable, `mnt-jump.automount` blew through systemd's default rate limit and went permanently-failed (no auto-retry). Four NFS-bind containers stayed exited for ~14 hours. Gatus dashboard hid it: HTTP probes of Access-fronted services returned `302 → Cloudflare Access login` and the default `[STATUS] < 400` accepted that as healthy. Also surfaced that the shared `*defaults` anchor never included `alerts:`, so ~75% of endpoints couldn't email even if a check did go red. Fixed via a `wait-for-qnap-nfs.service` oneshot ordered before `docker.service`, `StartLimit*=0` drop-ins on both automount units, Gatus switched to internal probes (dockernet container names + `172.18.0.1:<port>` for host-network services + Komodo `InspectDockerContainer` for kangaroo-resident), and `alerts: *alerts` baked into the `*defaults` anchor. [`docs/postmortems/2026-05-30-power-outage-nfs-recovery.md`](docs/postmortems/2026-05-30-power-outage-nfs-recovery.md)

- **2026-05-23 — pouch-jump-mount-failure** — Post-OOM-reboot, both QNAP NFS mounts came up silently broken (Pouch race-lost network at boot; Jump had never been in fstab) and flood/plex/paperless/backrest silently degraded for ~1 hour, with backrest about to write the next scheduled backup to local disk. Fixed via `x-systemd.automount` for both mounts, per-share `.podhaus-share-mounted` sentinel files, hardened healthchecks across every NFS-bind consumer, and `chattr +i` tripwires on bare `/mnt/{pouch,jump}`. [`docs/postmortems/2026-05-23-pouch-jump-mount-failure.md`](docs/postmortems/2026-05-23-pouch-jump-mount-failure.md)

---

## Editing docs

`docs/` is served by the central **docs-server** (`~/repos/docs`) at
`docs.pod.haus` — it scans every repo's `docs/` and renders Markdown
(GFM) or HTML into one server-generated shell + sidebar. Edits are live:
save, reload, no rebuild (it bind-mounts `~/repos` read-only).

Adding a doc: **write a Markdown `.md`** under `docs/` (preferred — the
first `# H1` is the title). HTML works for layout, but only its `<main>`
is used and the shell is injected, so write no `<head>`, topbar/sidebar,
or `<script>`. There are **no** per-file metadata tags, no `nav.js`, and
no per-repo `docs/assets/` — that old `_template.html` machinery is gone.

Ordering is filesystem-based (directories + alphabetical; a leading
number in a filename sorts it). To pin order or label a directory, add a
`_nav.toml` (see `docs/_nav.toml`). Underscore/dotfiles are never served.

Adding a plan: drop a `.md` into `docs/plans/`, or a subdirectory with an
`index.md` for a multi-page plan. Full authoring guide:
`~/repos/docs/docs/authoring.md`.

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
