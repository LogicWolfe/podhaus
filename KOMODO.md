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
- `dockernet` bridge (172.18.0.0/16) — shared external network for cross-stack communication
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
    ferretdb.compose.yaml       # Komodo Core infrastructure (not managed by ResourceSync)
    compose.env                 # Komodo config with op:// references
    sync/
      servers.toml              # Server definitions
      variables.toml            # Non-secret variables (MEDIA_DIR, TZ)
      podhaus-stacks.toml       # All stack definitions (inline compose via file_contents)
  paperless/                    # Paperless-ngx
    onenote-to-paperless-migration-guide.md
```

Stack compose definitions live in `komodo/stacks/<name>/compose.yaml`, mounted into Periphery at `/etc/komodo/stacks/`. Stacks use `files_on_host = true` + `run_directory` in TOML. Secrets flow from 1Password → komodo-op → Komodo Variables → `[[VARIABLE]]` interpolation in stack environment.

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

### 4. Migrate Cloudflare Tunnel to Komodo

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

### 5. Migrate remaining services, retire nginx, clean up

Services to migrate: flood, home-assistant (only 2 services are still running as legacy containers).

Retired services (not running or no longer needed): certbot, nginx, plex, unifi (now appliance), elasticsearch, elasticsearch-hq, kibana, owntone, reviewer, cloudflare-ddns, postgres (standalone).

#### 5a. Add Komodo variables

- [x] Add `MEDIA_DIR=/mnt/NFSPouch` to `variables.toml` (NFS4, replacing CIFS `/mnt/Pouch`)
- [x] Add `TZ=Australia/Perth` to `variables.toml`
- [x] Run sync to register variables

#### 5b. Create Flood Secret in 1Password

- [x] Read `FLOOD_SECRET` from legacy `secrets` file
- [x] Create `Flood Secret` item in Homelab vault via `op item create`
- [x] Verify komodo-op syncs it as `OP__KOMODO__FLOOD_SECRET__PASSWORD`

#### 5c. Migrate flood to Komodo stack

Flood uses `jesec/rtorrent-flood` upstream image directly (Dockerfile adds nothing). Entrypoint is `/sbin/tini -- flood`, which starts rtorrent as a child process. Config lives at `/flood-db/.rtorrent.rc` (rtorrent reads `$HOME/.rtorrent.rc`, and `HOME=/flood-db`). All session state (`.torrent`, `.torrent.rtorrent`, `.torrent.libtorrent_resume`) is in the `flood-db` Docker volume.

- [x] Add flood stack to `podhaus-stacks.toml` (inline compose, `flood-db` volume external, `/mnt/NFSPouch:/data` bind mount)
- [x] Stop old flood container
- [x] Deploy via `komodo-sync` — 168 torrents loaded from session, Flood UI serving on port 3000, NFS4 mount confirmed

#### 5d. Migrate home-assistant to Komodo stack

HA uses `homeassistant/home-assistant:stable` upstream image (Dockerfile adds nothing). All config in `home-assistant-config` volume at `/config/`. Needs trusted proxies fix for Cloudflare Tunnel routing (400 on X-Forwarded-For from dockernet 172.18.0.0/16).

- [x] Append `http:` trusted_proxies section to `/var/lib/docker/volumes/home-assistant-config/_data/configuration.yaml`
- [x] Add home-assistant stack to `podhaus-stacks.toml` (inline compose, volume external, host network, privileged)
- [x] Stop old home-assistant container
- [x] Deploy via `komodo-sync` — HA running, web UI responds 200
- [ ] Verify `home.pod.haus` loads without 400 errors (user to test)

#### 5e. Update tunnel ingress and retire nginx

- [x] Verify LAN reachability from tunnel container (10.0.0.25 returns 200 from dockernet)
- [x] Update cloudflare-tunnel ingress: route kangaroo/syncthing/unifi directly to backends
- [x] Destroy + redeploy tunnel stack to pick up config changes
- [x] Stop and remove nginx and certbot containers

#### 5f. Delete legacy files and clean up

- [x] Remove all retired service directories (certbot, cloudflare-ddns, cloudflare-tunnel, elasticsearch, elasticsearch-hq, kibana, nginx, owntone, plex, postgres, reviewer, unifi, forked-daapd)
- [x] Clean flood/ and home-assistant/ dirs (removed entirely — all config is inline in TOML or in Docker volumes)
- [x] Remove root-level management scripts (build, stop, connect, restart, create_symlinks, create_network, before_run, encrypt_secrets, decrypt_secrets)
- [x] Remove environment templates (environment.podhaus, environment.pinelake)
- [x] Remove stale stopped containers and prune unused Docker images (992.7MB reclaimed)
- [x] Update CLAUDE.md to reflect Komodo-based architecture
- [x] Update KOMODO.md to reflect completed migration

### 6. Migrate stack definitions from inline TOML to separate compose files

- [x] Create `komodo/stacks/<name>/compose.yaml` for each stack (onepassword, cloudflare-tunnel, flood, home-assistant)
- [x] Add Periphery volume mount for stacks directory in `ferretdb.compose.yaml`
- [x] Add `COMPOSE_KOMODO_STACKS_PATH` to `compose.env`
- [x] Update `podhaus-stacks.toml` to use `files_on_host = true` + `run_directory` instead of `file_contents`
- [x] Restart Komodo infrastructure, sync, verify all stacks running
- [x] Update CLAUDE.md and KOMODO.md

### 7. DNSControl for full DNS management

Declarative DNS management across Cloudflare (public) and UniFi (local split-horizon).

- [x] Fix tunnel ingress IP for `unifi.pod.haus` (`10.0.0.2` → `10.0.0.1`)
- [x] Back up existing Cloudflare DNS records to `dns/pod.haus.backup.json`
- [x] Create DNSControl config: `dns/dnsconfig.js`, `dns/creds.json`, `dns/.env`
- [x] Create helper scripts: `dns-preview`, `dns-push`
- [x] Clean up stale Cloudflare records (sunshine, plex, localhost, wildcard, alligator A, bilby A)
- [x] Create UniFi local DNS records for split-horizon (unifi, alligator, bilby)
- [x] Verify `dns-preview` shows 0 corrections

Note: Uses `api_version: "legacy"` for UniFi provider due to a `metadata` serialization bug in DNSControl v4.35.0's new Integration API support.

### 8. Create and deploy Paperless-ngx

- [x] Create `komodo/stacks/paperless/compose.yaml` (webserver, postgres, redis, tika, gotenberg)
- [x] Add `[[stack]]` entry to `podhaus-stacks.toml` with `files_on_host = true`
- [x] Add Cloudflare Tunnel ingress rule for `paperless.pod.haus`
- [x] Add `paperless` CNAME to `dns/dnsconfig.js`
- [x] Create 3 secrets in 1Password (secret key, postgres password, admin password)
- [x] Deploy via `komodo-sync` (volumes created automatically by Docker Compose)
- [x] Destroy + redeploy cloudflare-tunnel, push DNS
- [x] Verify 5 containers running, `https://paperless.pod.haus` returns 302 to login

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
- **Compose file reuse**: if a service runs on both servers (e.g. cloudflare-tunnel), the same compose file in `komodo/stacks/` can be used with different server assignments and environment variables in TOML
- **Tailscale**: if not already running on podhaus, add it as a service stack or host service. The existing `c.pod.haus` nginx proxy (100.100.99.23) suggests Tailscale is already in use

## Files Removed (step 5f — completed)

All legacy service directories, Dockerfiles, run scripts, management scripts, and environment templates have been removed. See git log for the full list.

## Post-Deploy Manual Steps

- **Paperless web UI**: Fastmail IMAP config, mail rules, admin password
- **SwiftPaperless iOS**: server URL + Cloudflare service token headers
- **Komodo backup procedure**: scheduled daily DB backup
- **Tailscale**: ensure running on podhaus, ACL allows podhaus ↔ pinelake on port 8120

## Verification

1. Komodo UI accessible, podhaus server showing metrics
2. 1Password secrets visible in Komodo Settings → Variables
3. All Komodo stacks running: onepassword, cloudflare-tunnel, flood, home-assistant, paperless
4. `torrent.pod.haus` — Flood UI loads, existing torrents intact
5. `home.pod.haus` — HA loads without 400 errors
6. `kangaroo.pod.haus`, `sync.pod.haus`, `unifi.pod.haus` — route directly through tunnel
7. Resource Sync TOML in git matches running state
8. No legacy `docker run` containers remain
9. Everything restarts automatically after a podhaus reboot
10. Paperless-ngx running at `https://paperless.pod.haus` — 5 containers, login works
11. (Later) pinelake server appears in Komodo, shows online/offline correctly
