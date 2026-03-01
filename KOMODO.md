# Migrate Podhaus to Komodo + Deploy Paperless-ngx

## Context

The current podhaus setup uses individual `docker run` bash scripts per container. This doesn't scale to multi-container services like Paperless-ngx (5 containers). Rather than shoehorn Paperless into 5 directories, we're migrating the whole infrastructure to Komodo with 1Password-backed secrets management via komodo-op.

The setup also needs to support managing **pinelake** (a Mac Mini at a remote location behind NAT that gets turned off regularly) from the same Komodo Core instance, connected via Tailscale.

## End-State Architecture

### Two Servers, One Control Plane

```
┌─────────────────────────────┐         Tailscale          ┌──────────────────────────┐
│         podhaus             │      100.x.x.x mesh        │       pinelake           │
│                             │◄──────────────────────────►│                          │
│  Komodo Core + FerretDB     │                            │  Komodo Periphery        │
│  Komodo Periphery (local)   │                            │  Docker (OrbStack/DD)    │
│  1Password Connect          │                            │  Tailscale (native)      │
│  komodo-op                  │                            │  Service stacks          │
│  Service stacks             │                            │                          │
│  Tailscale                  │                            │  (Mac Mini, macOS)       │
│  (Linux)                    │                            │  (behind NAT, power-cycled)
└─────────────────────────────┘                            └──────────────────────────┘
```

- **Komodo Core** runs only on podhaus — single control plane for both servers
- **Periphery** runs on both — Core reaches pinelake's Periphery via its Tailscale IP
- When pinelake is off, it shows as offline in Komodo. When it powers back on, Tailscale reconnects and Core can reach it again. Stacks with `restart: unless-stopped` come back automatically on the Mac Mini via Docker's restart policy — no Komodo intervention needed for recovery.

### Management Layer (podhaus only)

**Komodo** (4 containers):
- `core` — API + web UI (port 9120)
- `periphery` — local agent for podhaus
- `ferretdb` — MongoDB-compatible API over Postgres
- `postgres` — backing store for FerretDB

**1Password + komodo-op** (3 containers):
- `op-connect-api` — 1Password Connect REST API
- `op-connect-sync` — keeps local data in sync with 1Password cloud
- `komodo-op` — syncs 1Password vault → Komodo secret variables

### Networking

**podhaus:**
- `dockernet` bridge (172.16.42.0/24) — shared external network for cross-stack communication
- Each compose stack gets its own internal network
- Tailscale for connectivity to pinelake

**pinelake:**
- Own shared external network (or per-stack defaults)
- Tailscale for connectivity back to podhaus/Core
- Cloudflare Tunnel (if exposing any pinelake services)

**Core → Periphery:**
- podhaus Periphery: `https://periphery:8120` (local, within Komodo's compose network)
- pinelake Periphery: `https://100.x.x.x:8120` (Tailscale IP — set when adding server in Komodo)

### Secrets Flow

```
1Password vault "Komodo"
  → op-connect-api (on podhaus)
    → komodo-op
      → Komodo variables (secrets)
        → interpolated into stack .env at deploy time on EITHER server
```

Secrets are available globally in Komodo. Server-specific secrets use naming convention:
- Shared: `OP__KOMODO__PAPERLESS__DB-PASSWORD`
- Per-server: `OP__KOMODO__PODHAUS-CLOUDFLARE__TOKEN`, `OP__KOMODO__PINELAKE-CLOUDFLARE__TOKEN`

### Configuration as Code

```
podhaus/
  komodo/
    ferretdb.compose.yaml
    compose.env
    sync/
      servers.toml              # Both server definitions
      variables.toml            # Non-secret variables
      podhaus-stacks.toml       # Stacks assigned to podhaus
      pinelake-stacks.toml      # Stacks assigned to pinelake (later)
  onepassword/
    docker-compose.yml
    .gitignore                  # ignores 1password-credentials.json
  cloudflare-tunnel/
    docker-compose.yml
  nginx/
    docker-compose.yml
    Dockerfile, conf.d/
  paperless/
    docker-compose.yml          # All 5 containers
    PHASE1.md, migration guide
  plex/
    docker-compose.yml
    Dockerfile
  home-assistant/
    docker-compose.yml
  flood/
    docker-compose.yml
  ... (other services)
```

TOML Resource Sync files split by server — each stack's TOML specifies which server it deploys to. Compose files are reusable across servers if needed (same compose, different server assignment in TOML).

## Implementation Steps (Podhaus First)

### 1. Deploy Komodo on podhaus

#### 1a. Prerequisites (user)

- [x] Create 1Password Service Account with read/write access to "Homelab" vault
- [x] Install `op` CLI on podhaus — https://developer.1password.com/docs/cli/get-started/
- [x] Authenticate: `export OP_SERVICE_ACCOUNT_TOKEN=<token>`
- [x] Verify: `op vault list` shows the Homelab vault

#### 1b. Create secrets in 1Password (Claude + user)

- [x] Generate random secrets and create 5 items in the Homelab vault:
  - `Komodo DB Password` (64 chars)
  - `Komodo Passkey` (64 chars)
  - `Komodo JWT Secret` (64 chars)
  - `Komodo Webhook Secret` (64 chars)
  - `Komodo Admin Password` (32 chars)

#### 1c. Create Komodo files (Claude)

- [x] Create `komodo/` directory
- [x] Create `komodo/ferretdb.compose.yaml` — upstream copy from `moghtech/komodo`, defines:
  - `postgres` (ghcr.io/ferretdb/postgres-documentdb)
  - `ferretdb` (ghcr.io/ferretdb/ferretdb)
  - `core` (ghcr.io/moghtech/komodo-core, port 9120)
  - `periphery` (ghcr.io/moghtech/komodo-periphery, Docker socket + /proc access)
- [x] Create `komodo/compose.env` with `op://Homelab/Komodo/<field>` references for secrets:
  - `KOMODO_DB_PASSWORD=op://Homelab/Komodo DB Password/password`
  - `KOMODO_PASSKEY=op://Homelab/Komodo Passkey/password`
  - `KOMODO_JWT_SECRET=op://Homelab/Komodo JWT Secret/password`
  - `KOMODO_WEBHOOK_SECRET=op://Homelab/Komodo Webhook Secret/password`
  - `KOMODO_INIT_ADMIN_PASSWORD=op://Homelab/Komodo Admin Password/password`
  - All other config: `TZ=Australia/Perth`, `KOMODO_HOST=https://komodo.pod.haus`, `KOMODO_FIRST_SERVER=https://periphery:8120`, `KOMODO_FIRST_SERVER_NAME=podhaus`, `KOMODO_LOCAL_AUTH=true`, etc.
  - Safe to commit (contains only `op://` references, no real secrets)
  - Note: `op run` resolves `op://` references as process env vars; the compose file uses `${VAR}` interpolation to pass them into containers (not `env_file`, which would pass raw `op://` strings)

#### 1d. Create helper scripts (Claude)

- [x] `komodo-start` — `op run --env-file komodo/compose.env -- docker compose -p komodo -f komodo/ferretdb.compose.yaml --env-file komodo/compose.env up -d`
- [x] `komodo-stop` — `docker compose -p komodo down`
- [x] `komodo-status` — `docker compose -p komodo ps`
- [x] `komodo-upgrade` — `op run` wrapping `pull` then `up -d`
- [x] Make all executable

No `sudo` needed — user is in the docker group.

#### 1e. Deploy (user)

- [x] Run `./komodo-start`
- [x] Run `./komodo-status` — verify 4 containers running
- [x] Add `komodo.pod.haus` route in Cloudflare Zero Trust dashboard → `http://komodo-core:9120`
- [x] Access `https://komodo.pod.haus`, log in as `nathan`
- [x] Verify podhaus server appears with system metrics
- [x] Create an API key for komodo-op (needed in step 2) — stored in 1Password as "Komodo API OnePassword Sync"

### 2. Set up 1Password Connect

#### 2a. Define onepassword stack in Resource Sync TOML (Claude)

- [x] `komodo/sync/podhaus-stacks.toml` — onepassword stack with inline compose (`file_contents`)
- [x] 3-service compose: `op-connect-api`, `op-connect-sync`, `komodo-op`
- [x] `1password-credentials.json` injected via compose `configs` from `OP_CREDENTIALS` env var — never written to disk
- [x] 4 secrets via `[[VARIABLE]]` interpolation in stack environment
- [x] `deploy = true` so Resource Sync triggers deployment

#### 2b. Bootstrap variable seeding in komodo-start (Claude)

- [x] `komodo-start` waits for Core to be healthy after startup
- [x] Reads API key/secret from 1Password via `op read`
- [x] Seeds 4 Komodo Variables via the Core API: `ONEPASSWORD_CREDENTIALS`, `ONEPASSWORD_CONNECT_TOKEN`, `ONEPASSWORD_API_KEY`, `ONEPASSWORD_API_SECRET`
- [x] Idempotent — creates on first run, updates on subsequent runs

#### 2c. Resource Sync automation in komodo-start (Claude)

- [x] Mount `komodo/sync/` into Core container at `/syncs/podhaus`
- [x] `komodo-start` creates "podhaus" ResourceSync (`files_on_host`, `resource_path: ["."]`)
- [x] `komodo-start` triggers `RunSync` after variable seeding

### 3. Deploy and verify 1Password Connect + komodo-op

- [x] Run `./komodo-start` — seeds variables, creates Resource Sync, triggers sync
- [x] Resource Sync creates and deploys onepassword stack automatically
- [x] `docker logs op-connect-api` — successfully serving vault item requests
- [x] `docker logs komodo-op` — synced 10 secrets, 0 errors
- [x] Komodo UI → Settings → Variables shows 14 variables (4 bootstrap + 10 from vault)
- [x] Naming confirmed: `OP__KOMODO__<ITEM-NAME>__<FIELD-LABEL>` pattern

### 4. Set up Resource Sync

- [ ] Write TOML for servers, stacks, variables
- [ ] Structure: `servers.toml` defines both podhaus and pinelake (pinelake address TBD)
- [ ] `podhaus-stacks.toml` for current services
- [ ] Create Resource Sync in Komodo, verify

### 5. Migrate Cloudflare Tunnel to Komodo

Switched from remotely-managed (token-based) to locally-managed tunnel with ingress rules in git.

- [x] Add cloudflare-tunnel stack to `podhaus-stacks.toml` (inline compose with Docker configs)
- [x] Credentials JSON stored in 1Password as a login field, injected via komodo-op → `TUNNEL_CREDENTIALS`
- [x] Config.yml defined inline via compose `configs` `content:` — ingress rules in git
- [x] Clean up stale nginx configs (`c.conf`, `reviewer.conf`)
- [x] Create locally-managed tunnel and store credentials in 1Password
- [x] Set up DNS CNAMEs for new tunnel UUID
- [x] Stop old tunnel, deploy new stack via Resource Sync, verify routing
- [x] Delete old tunnel (`PodHaus` / `f1ad8313`) via `cloudflared tunnel delete`
- [x] Delete stale DNS CNAME records from Cloudflare (`c.pod.haus` removed, `reviewer.pod.haus` already gone)
### 6. Create and deploy Paperless-ngx

- [ ] Write `paperless/docker-compose.yml` (webserver, postgres, redis, tika, gotenberg)
- [ ] Create Stack in Komodo pointing at compose file
- [ ] Deploy and verify
- [ ] Configure Cloudflare Tunnel route

### 7. Convert remaining podhaus services

- [ ] For each service: convert run script → compose file → Komodo Stack → verify
- [ ] Fix home.pod.haus tunnel routing: HA returns 400 on `X-Forwarded-For` from untrusted sources. Add `http:` section to HA's `configuration.yaml` with dockernet subnet (`172.18.0.0/16`) in `trusted_proxies`.
- [ ] Fix unifi.pod.haus tunnel routing

### 8. Clean up old infrastructure

- [ ] Remove run scripts, before_run, management scripts, secrets/encryption tooling
- [ ] Update CLAUDE.md and README.md

### 9. (Later) Add pinelake

- [ ] Install Tailscale on both machines if not already running
- [ ] Install Docker on pinelake (Docker Desktop or OrbStack for macOS)
- [ ] Run Periphery container on pinelake (needs Docker socket access + Tailscale connectivity)
- [ ] In Komodo, add pinelake as a server: `https://<pinelake-tailscale-ip>:8120`
- [ ] Create `pinelake-stacks.toml` with service definitions
- [ ] Periphery authenticates via the shared `KOMODO_PASSKEY`
- [ ] Port 8120 on pinelake only needs to be reachable from podhaus via Tailscale — not exposed to the internet

## Planning Considerations for Pinelake

Things to keep in mind now that affect the podhaus setup:

- **TOML structure**: split stacks by server now so the pattern is established
- **Secret naming**: use server-prefixed names for per-server secrets from the start
- **Compose file reuse**: if a service runs on both servers (e.g. cloudflare-tunnel), the same compose file can be used with different server assignments and environment variables in TOML
- **Tailscale**: if not already running on podhaus, add it as a service stack or host service. The existing `c.pod.haus` nginx proxy (100.100.99.23) suggests Tailscale is already in use

## Files to Create

- `komodo/ferretdb.compose.yaml` — Komodo compose (from upstream)
- `komodo/compose.env` — Komodo configuration
- `komodo/sync/servers.toml` — both server definitions (pinelake address placeholder)
- `komodo/sync/podhaus-stacks.toml` — podhaus stack definitions
- `komodo/sync/pinelake-stacks.toml` — pinelake stack definitions (initially empty/minimal)
- `komodo/sync/variables.toml` — non-secret variables
- `onepassword/docker-compose.yml` — 1Password Connect + komodo-op
- `onepassword/.gitignore` — ignore credentials file
- `paperless/docker-compose.yml` — Paperless-ngx full stack
- Compose files for each existing service

## Files to Remove (after full podhaus migration)

- `before_run`, `build`, `stop`, `connect`, `restart`, `create_symlinks`
- `environment`, `environment.podhaus`, `environment.pinelake`
- `secrets`, `encrypt_secrets`, `decrypt_secrets`, `secrets.podhaus.gpg`, `secrets.pinelake.gpg`
- `run` scripts in each service directory
- Symlinks in service directories

## Files to Modify

- `CLAUDE.md` — new workflow: Komodo, TOML resource sync, 1Password, Tailscale
- `README.md` — updated architecture, setup, service docs
- `.gitignore` — add `onepassword/1password-credentials.json`

## Post-Deploy Manual Steps

- **Cloudflare Tunnel routes**: configure in Zero Trust dashboard
- **Paperless web UI**: Fastmail IMAP config, mail rules, admin password
- **SwiftPaperless iOS**: server URL + Cloudflare service token headers
- **Komodo backup procedure**: scheduled daily DB backup
- **Tailscale**: ensure running on podhaus, ACL allows podhaus ↔ pinelake on port 8120

## Verification

1. Komodo UI accessible, podhaus server showing metrics
2. 1Password secrets visible in Komodo Settings → Variables
3. Paperless-ngx running as a Komodo Stack at `https://paperless.pod.haus`
4. All migrated podhaus services running and healthy
5. Resource Sync TOML in git matches running state
6. Everything restarts automatically after a podhaus reboot
7. Komodo DB backup procedure running on schedule
8. (Later) pinelake server appears in Komodo, shows online/offline correctly
