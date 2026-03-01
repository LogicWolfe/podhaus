# PodHaus

Docker container infrastructure for home servers. Currently deployed to **podhaus** (pod.haus) and **pinelake** (pinelake.haus).

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

**forked-daapd** — Has config files and databases but no `run` script or Dockerfile. Replaced by owntone.

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
