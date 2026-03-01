# Phase 1: Deploy Paperless-ngx to Podhaus

> **Blocker: Multi-container services don't fit the current model.**
> Paperless-ngx requires 5 containers (webserver, postgres, redis, tika, gotenberg). The podhaus convention is one directory per container with the container name derived from the directory name. This means 5 directories (`paperless/`, `paperless-postgres/`, `paperless-redis/`, `paperless-tika/`, `paperless-gotenberg/`), each with its own `run` script, plus `run_all`/`stop_all` convenience scripts to manage them as a unit. This is clunky and will only get worse as more multi-container services are added. Consider overhauling the service management approach (e.g. docker-compose per service stack) before proceeding.

## Context

Setting up a self-hosted Paperless-ngx instance as part of a OneNote migration. This phase gets the core stack running and accessible via Cloudflare Tunnel. Email ingestion, scanner config, and mobile app setup are manual post-deploy steps done through the Paperless web UI and Cloudflare dashboard.

## Architecture Decisions

**Dedicated Postgres** — not sharing the existing `postgres` container (which is Postgres 13.2 on host network). Paperless gets its own `postgres:16` container with isolated data volume. Simpler backup story and independent upgrades.

**All containers on dockernet** with static IPs in the 172.16.42.0/24 range. No port publishing needed since access is through the Cloudflare Tunnel (already on dockernet).

**No nginx config** — all access goes through Cloudflare Tunnel + Zero Trust. No LAN reverse proxy.

## IP Assignments (dockernet 172.16.42.0/24)

| Container | IP |
|---|---|
| paperless (webserver) | 172.16.42.10 |
| paperless-postgres | 172.16.42.11 |
| paperless-redis | 172.16.42.12 |
| paperless-tika | 172.16.42.13 |
| paperless-gotenberg | 172.16.42.14 |

## Containers

### paperless-postgres
`postgres:16` image. `POSTGRES_DB=paperless`, `POSTGRES_USER=paperless`, password from `$PAPERLESS_POSTGRES_PASSWORD`. Volume: `paperless-pgdata`.

### paperless-redis
`redis:7` image. Volume: `paperless-redisdata`.

### paperless-tika
`ghcr.io/paperless-ngx/tika:latest` image. Stateless.

### paperless-gotenberg
`gotenberg/gotenberg:8` image with `--chromium-disable-javascript=true --chromium-allow-list=file:///tmp/.*`. Stateless.

### paperless (webserver)
`ghcr.io/paperless-ngx/paperless-ngx:latest`. Key env vars:
- `PAPERLESS_REDIS=redis://172.16.42.12:6379`
- `PAPERLESS_DBHOST=172.16.42.11` (+ DBPORT, DBNAME, DBUSER, DBPASS)
- `PAPERLESS_SECRET_KEY`, `PAPERLESS_ADMIN_USER=admin`, `PAPERLESS_ADMIN_PASSWORD`
- `PAPERLESS_URL=https://paperless.pod.haus`
- `PAPERLESS_CSRF_TRUSTED_ORIGINS=https://paperless.pod.haus`
- `PAPERLESS_ALLOWED_HOSTS=paperless.pod.haus`
- `PAPERLESS_OCR_LANGUAGE=eng`
- Tika/Gotenberg endpoints pointing to static IPs
- `PAPERLESS_EMAIL_TASK_CRON=*/10 * * * *`
- `PAPERLESS_CONSUMER_ENABLE_BARCODES=true`
- `PAPERLESS_TIME_ZONE=$TZ`

Volumes: `paperless-data` → `/usr/src/paperless/data`, `paperless-media` → `/usr/src/paperless/media`. Consumption folder bind mount deferred until scanner is set up.

## Secrets

Three new values needed in the `secrets` file (decrypt, edit, re-encrypt with `encrypt_secrets`):

- `PAPERLESS_SECRET_KEY` — generate with `python3 -c "import secrets; print(secrets.token_urlsafe(50))"`
- `PAPERLESS_POSTGRES_PASSWORD` — generate with `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`
- `PAPERLESS_ADMIN_PASSWORD` — chosen manually

After encrypting, rename `secrets.gpg` → `secrets.podhaus.gpg` and verify the roundtrip by decrypting again.

## Documentation Updates Needed

### CLAUDE.md
Add a secrets management section explaining:
- `encrypt_secrets` encrypts `secrets` → `secrets.gpg` using GPG symmetric (passphrase prompted interactively)
- `decrypt_secrets <file>` decrypts a `.gpg` file → `secrets`
- After encrypting, rename output from `secrets.gpg` to the environment-specific name
- Always verify decryption works before relying on a newly encrypted file

### README.md
- Expand the Secrets section to cover the encrypt output naming quirk and verification step
- Add Paperless-ngx to the Active services list once deployed

## Post-Deploy Manual Steps

- **Start the stack** on the server
- **Verify**: `docker ps --filter name=paperless`, check `docker logs paperless`
- **Cloudflare Tunnel**: add `paperless.pod.haus` hostname → `http://172.16.42.10:8000`, create Zero Trust Access policy and Service Token for mobile
- **Fastmail IMAP**: configure Mail Account and Mail Rule in Paperless web UI per the migration guide
- **SwiftPaperless**: add server URL + Cloudflare service token headers in the iOS app
- **Seed classifier**: manually tag ~20-30 documents to train the ML auto-classifier
