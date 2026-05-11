# Railway migrations — doggos and yiayia

Two Railway-hosted services need to come home. **Depends on**
[Cloudflare as Terraform](cloudflare-terraform.md) for the Komodo
webhook bypass Access Application — start that one first.

## Auth setup (already done)

Railway CLI installed at `~/.local/bin/railway` v4.38.0.

The token at `op://Homelab/railway-api-token/credential` is an
**account/API token**, not a workspace-scoped token. The CLI needs:

- `RAILWAY_API_TOKEN` env var (not `RAILWAY_TOKEN`)
- `RAILWAY_PROJECT_ID` + `RAILWAY_ENVIRONMENT_ID` per invocation

The `me` GraphQL query returns "Not Authorized", but project-scoped
queries and CLI commands work. To read the token from 1P without an
interactive `op signin`, use the `OP_SERVICE_ACCOUNT_TOKEN` file at
the repo root (the same credential `komodo-op` uses).

The base64-pipe state transfer pattern is proven from the earlier Kuma
migration.

## Project survey (done 2026-04-17)

### Yiayia Board

- Project `2ac95713-3aad-413e-b116-5e8a591dbd58`, env `8729fa0e-…`,
  service `yiayia-board`.
- Deployment from github repo `LogicWolfe/yiayia-board`.
- **Always-on** — doesn't sleep.
- Base image: `python:3.13` on Debian Trixie (nixpacks-built from
  repo).
- Entrypoint: `/app/entrypoint.sh` → `uvicorn main:app --host 0.0.0.0
  --port 8000`.
- Structure: `/app/backend/` (FastAPI) + `/app/frontend/` (static).
- Runtime deps: Playwright (node driver alongside Python — headless
  browser automation).
- State: `/data` volume (5 GB allocated, **380 MB used**), contains
  `yiayia_board.db` (SQLite, 270 KB) + `lost+found`.
- App env: `DEFAULT_BOARD_ID=fe9d9fb4-…` (UUID of a board record),
  `PORT=8000`, `SECRET_KEY=…` (move to 1P as `yiayia-board-secret-key`
  on migration).
- Public: `yiayia.pod.haus` (Railway-managed domain, currently
  proxied).
- Purpose: the board-app Gatus already monitors as "Yiayia Board
  Frontend/Device" — a real-time status board using Playwright to
  scrape some device/service.

### Indigo's Stuff ("Doggos Alive")

- Project `dcaac4dd-62b3-403d-8060-2a0166a7353e`, env `c1bad88e-…`,
  service `indigo-web-server`.
- Deployment from github repo `LogicWolfe/indigo-web-server`.
- **Serverless** — sleeps when idle.
- Content: a kid-built static website about dogs (built with the Blocs
  web builder; bootstrap + custom CSS + JPEG/WebP images; landing at
  `tibetan-spaniels.html`).
- Port: 80.
- **No Railway volume.** Content lives in the repo, no runtime
  mutation.
- App env: `FTP_PASSWORD=…` + `SSH_AUTHORIZED_KEYS=ssh-ed25519 …`
  — service exposes FTP/SSH deploy paths so Indigo can upload new
  content directly from Blocs (Mac web builder).
- Public: `doggos.indigo.pod.haus`.
- Purpose: kid's personal site; low traffic, hence serverless sleep.

## Open decision — source path

Both repos under `LogicWolfe/*` return 404 on the public GitHub API,
so they're **private** to Railway's GitHub integration. Three options:

1. **Clone the private repos locally** (requires LogicWolfe GitHub
   access) and build standard Docker images from source. Cleanest
   long-term.
2. **Dump the running container's `/app` tree** via
   `railway ssh … | tar | base64` + restore on bilby. Works but heavy
   for the Python app (Playwright browser binaries are hundreds of
   MB) and bakes the Railway-specific build output into the migration
   (less portable).
3. **Hybrid** — for Indigo (static files only), scrape the public site
   via `wget -mk https://doggos.indigo.pod.haus/` and host with nginx;
   for Yiayia, rebuild from source when repo access is sorted.

Decide before writing compose files. Recommend #1 if GitHub access is
cheap to obtain, otherwise #3.

## Steps

After the source-path decision:

1. **Create `doggos/` and `yiayia/` directories** in the repo with
   `compose.yaml` + `stack.toml` following the
   [Stack conventions](/stack-conventions.html).
2. **Move secrets to 1P** as Homelab items:
   - `yiayia-board-secret-key`
   - `indigo-ftp-password`
   - `indigo-ssh-pubkey`
3. **Migrate Yiayia's `/data/yiayia_board.db`** via base64 pipe (same
   pattern as the Kuma migration).
4. **Deploy local stacks via Komodo** — `./komodo-sync` then deploy
   each from the UI.
5. **Add ingress rules** to `cloudflare-tunnel/conf/config.yml`:
   - `yiayia.pod.haus → http://yiayia-board:8000`
   - `doggos.indigo.pod.haus → http://indigo-web-server:80`
6. **Update DNS** via Terraform (preferred — see
   [Cloudflare as Terraform](cloudflare-terraform.md)) or DNSControl
   as fallback if these run before that work completes: remove Railway
   CNAMEs, let the tunnel handle both.
7. **Apply DNS, verify.**
8. **Create Access Application for Komodo's webhook path** via
   Terraform — Bypass policy scoped to the exact path. Komodo
   validates the HMAC signature on its end.
9. **Add Gatus monitors** — Yiayia already has Frontend/Device
   endpoints in `gatus/conf/config.yaml`; just point them at bilby-
   side after DNS flips. Add `doggos.indigo.pod.haus` endpoint.
10. **Decommission Railway projects** — keep 72h for rollback, then
    delete.

## Open question on `doggos.indigo.pod.haus`

The current hostname has two labels under `pod.haus`
(`doggos.indigo`). That falls **outside** the `*.pod.haus` Cloudflare
Access wildcard. Decide:

- Keep the two-label name and accept that the site has no Access gate
  (it's a public kids' site — that may be fine).
- Rename to a single-label hostname (`doggos-indigo.pod.haus`?) to
  inherit the wildcard policy.

If the site is meant to be public anyway, the two-label name is fine.
