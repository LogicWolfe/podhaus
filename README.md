# PodHaus

Docker container infrastructure for home servers. Currently deployed to **podhaus** (pod.haus) and **pinelake** (pinelake.haus).

## Principles

**Config as code.** Any configuration that *can* live in this repo, *should* live in this repo. That includes service preference files, identity/UUID strings, and anything else you'd lose sleep over if a container volume got wiped. Checked-in config is the safety net for the day a service blows up and you need to rebuild from scratch.

Secrets never go in raw — they live in the 1Password Homelab vault and are templated into rendered config at deploy time (`op run --env-file`, `op inject`, or env-var substitution in init containers). The existing Komodo stack is the reference pattern: `komodo/compose.env` holds `op://Homelab/...` references, `op run` resolves them into environment variables, and compose interpolates them into the running container.

The operational reality is that long-running stateful services (Plex is the canonical example) *will* eventually need a rebuild. Having the config in git turns that from a multi-hour recovery scramble into a clone-and-deploy. The corollary: if you find yourself arguing against checking config in because "the file drifts at runtime" or "it contains some secrets", the answer is to check it in AND solve the drift/secrets problem — not to leave it out. Narrow the enforcement scope (init container only templates the attrs we care about) if the service rewrites its own state.

## NAS storage (kangaroo, 10.0.0.25)

Two NFS exports, same host, different drives, different RAID arrays:

| Export | Backing | Capacity | Best for |
|---|---|---|---|
| `/Jump` | 2× SATA SSD | 382 GB | Container state, databases, config — anything latency-sensitive |
| `/Pouch` | 5× spinning HDD | 29 TB | Media libraries, document archives, backup repositories — anything big |

Throughput is equivalent between the two (both CPU-limited on the NFS controller). The real difference is IOPS — Jump is dramatically faster for small-random access, with ~0.1 ms operation latency. Place workloads accordingly:

- **Latency-sensitive → Jump.** Postgres/SQLite databases, application config trees, search indexes, anything that does many small reads and writes.
- **Bulk throughput → Pouch.** Video libraries, document archives, backup chunks, anything sequential.

Jump has 2 free bays for future SSD expansion if needed.

Each service lives in its own directory with a `run` script that starts it via `sudo docker run`. Root-level shell scripts (`build`, `stop`, `connect`, `restart`) are symlinked into each service directory by `create_symlinks`.

## Setup

1. Run `create_network` to create the `dockernet` bridge network (172.16.42.0/24)
2. Copy the appropriate environment file: `cp environment.podhaus environment`
3. Decrypt the matching secrets: `./decrypt_secrets secrets.podhaus.gpg`
4. Run `create_symlinks` to set up management script symlinks
5. Start services from their directories: `cd nginx && ./run`

## Secrets

Secrets are stored as GPG-encrypted files per environment (`secrets.podhaus.gpg`, `secrets.pinelake.gpg`). The active secrets live in `secrets` (git-ignored).

```
./decrypt_secrets secrets.podhaus.gpg   # decrypt to ./secrets
./encrypt_secrets                        # encrypt ./secrets symmetrically
```

## Services

### Active

**nginx** — Reverse proxy with SSL/TLS termination. Routes `*.pod.haus` subdomains to backend services. Certs from Let's Encrypt via Cloudflare DNS validation. Network: `dockernet`, ports 80/443.

**flood** — RTorrent + Flood torrent client. Image: `jesec/rtorrent-flood`. Network: `dockernet`, port 42000. Sometimes stalls at startup — `ls /data` inside the container can unstick it.

**plex** — Plex media server with GPU transcoding (i965-va-driver). Image: `plexinc/pms-docker:plexpass`. Network: `host`. Claim token from https://www.plex.tv/claim/.

**home-assistant** — Home automation. Image: `homeassistant/home-assistant:stable`. Network: `host`, privileged mode with dbus access.

**certbot** — Automated SSL cert renewal via Cloudflare DNS plugin. Custom image built on `python:latest`. Renews every 24h.

**cloudflare-tunnel** — Cloudflare Argo tunnel. Image: `cloudflare/cloudflared:latest`. Network: `dockernet`.

**cloudflare-ddns** — Dynamic DNS updates for pinelake.haus. Image: `oznu/cloudflare-ddns:latest`.

**unifi** — UniFi network controller. Image: `jacobalberty/unifi:latest`. Network: `host`. Web UI on port 8443.

### Stable but outdated

**postgres** — PostgreSQL 13.2 (current is 17.x). Network: `host`, port 5432.

**owntone** — Music server. Image: `dwinks/owntone-aarch64`. Network: `host`. Has a `sleep 300` in its CMD that delays startup.

### Stale

**elasticsearch** — Elasticsearch 7.10.1 (from 2021). Network: `dockernet`. Not recently used.

**kibana** — Kibana 7.10.1, matched to the old Elasticsearch. Network: `dockernet`. Not recently used.

**elasticsearch-hq** — Admin UI for Elasticsearch. Only useful if Elasticsearch is running.

### Abandoned

**reviewer** — Build script references a path outside the repo. Nginx config exists but the service is broken.

**paperless** — Only contains a OneNote migration guide. No service files.

### External (nginx-proxied only)

These services are proxied by nginx but not managed by this repo:

- **syncthing** (sync.pod.haus) — 172.18.0.1:8384
- **kangaroo** (kangaroo.pod.haus) — 10.0.0.25:8080
- **c** (c.pod.haus) — 100.100.99.23:8888 (Tailscale)

## Environment variables

Defined in environment files (`environment.podhaus`, `environment.pinelake`):

| Variable | Description |
|---|---|
| `MEDIA_DIR` | Path to media storage |
| `TRANSCODE_DIR` | Path for Plex transcoding |
| `TZ` | Timezone |
| `VIDEO_GID` | Video group ID for GPU access |
| `ADMIN_EMAIL` | Admin email for certbot |
| `DOMAIN` | Domain name (pinelake only) |
| `PLEX_NAME` | Plex hostname (pinelake only) |

## docker-compose.yml

Mostly vestigial. Only nginx is defined as an active service. The repo primarily uses individual `run` scripts instead.

---

## Komodo (migration in progress)

Infrastructure is being migrated from individual `docker run` scripts to [Komodo](https://komo.do), a container management platform. See `KOMODO.md` for the full migration plan and progress.

### Architecture

Komodo Core runs on podhaus as the single control plane. Periphery agents run on each managed server. Secrets are stored in 1Password and injected at startup via `op run`.

```
komodo/
  ferretdb.compose.yaml   # Komodo stack: postgres, ferretdb, core, periphery
  compose.env             # Config + op:// secret references
```

### Secrets management

Secrets use 1Password Service Accounts with `op run` for injection:

- `compose.env` contains `op://Homelab/...` references (safe to commit)
- `op run --env-file compose.env` resolves references into process env vars
- The compose file uses `${VAR}` interpolation to pass resolved values into containers
- `OP_SERVICE_ACCOUNT_TOKEN` file provides the service account credential (git-ignored)

### Helper scripts

| Script | Description |
|---|---|
| `komodo-start` | Resolve secrets via `op run`, start all containers |
| `komodo-stop` | Stop and remove all containers |
| `komodo-status` | Show container status |
| `komodo-upgrade` | Pull latest images and restart |

### Containers

| Container | Image | Purpose |
|---|---|---|
| `komodo-core` | `ghcr.io/moghtech/komodo-core` | API + web UI (port 9120) |
| `komodo-periphery` | `ghcr.io/moghtech/komodo-periphery` | Local agent, Docker socket access |
| `komodo-ferretdb` | `ghcr.io/ferretdb/ferretdb` | MongoDB-compatible API over Postgres |
| `komodo-postgres` | `ghcr.io/ferretdb/postgres-documentdb` | Backing store for FerretDB |

### Access

- Web UI: `https://komodo.pod.haus` (via Cloudflare Tunnel)
- komodo-core is temporarily on `dockernet` so the legacy tunnel container can reach it
