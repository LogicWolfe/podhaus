# podhaus

Docker container infrastructure for home servers — Docker Compose stacks
managed via Komodo, secrets from 1Password, ingress via Cloudflare
Tunnel + Access at `*.pod.haus`. Two hosts today:

- **bilby** — Apple M1 Mac mini, Fedora Asahi Linux. Primary; runs
  Komodo Core + Periphery + every original stack (Plex, Paperless,
  Home Assistant, Flood, etc.).
- **kangaroo** — QNAP NAS, QTS + Container Station. Second Periphery;
  runs Syncthing + a second Backrest + autoheal + logging Alloy.

A third host, **pinelake**, is planned.

## Docs

The full documentation lives at **<https://docs.pod.haus>** (gated by
Cloudflare Access). Local fallback: open
[`docs/index.html`](docs/index.html) in a browser.

Start with [Architecture](docs/architecture.html), [Hosts](docs/hosts.html),
[Komodo](docs/komodo.html), and [Stack conventions](docs/stack-conventions.html)
— that's ~10 minutes and covers most of what you need to know.

## Quickstart on bilby

```sh
./komodo-start    # bootstrap-only: Komodo Core up, chicken-and-egg vars, sync registered
./komodo-sync     # debug iterate: single RunSync + redeploy stale (no commit needed)
./komodo-status   # show Komodo container status
./komodo-stop     # shut down Komodo Core
./komodo-upgrade  # pull latest images + restart
```

Steady-state deploys: commit + push. The single GitHub webhook
fires the `podhaus-push-deploy` Komodo Procedure (RunSync →
deploy-if-changed → force-deploy linked-repo stacks). No manual
`./komodo-sync` needed.

## Quickstart on kangaroo

Run from bilby:

```sh
./kangaroo_bootstrap   # idempotent — sets up Periphery on the QNAP
```

After that, kangaroo-targeted stacks deploy through the same Komodo UI
on bilby.

## DNS

```sh
./dns-preview   # show pending DNS changes (read-only)
./dns-push      # apply DNS changes via DNSControl
```

## Index of top-level dirs

| Dir | Purpose |
|---|---|
| `komodo/` | Komodo Core infrastructure + ResourceSync TOML |
| `onepassword/` | 1Password Connect API + komodo-op |
| `cloudflare-tunnel/` | Tunnel container + ingress rules (`conf/config.yml`) |
| `dns/` | DNSControl config |
| `init-tools/` | Shared init-container image (alpine + gettext + python3) |
| `plex/` | Plex Media Server |
| `paperless/` | Paperless-ngx + Postgres + Redis + Tika + Gotenberg |
| `home-assistant/` | Home Assistant |
| `flood/` | rtorrent + Flood UI + auto-extract pipeline |
| `unpackerr/` | RAR extraction |
| `syncthing/` | Syncthing (deployed on kangaroo) |
| `gatus/` | Endpoint monitoring + alerting |
| `ofelia/` | Docker label-driven cron |
| `backup/` | Backrest (multi-host) |
| `autoheal/` | Container restart on unhealthy (multi-host) |
| `logging/` | Alloy + Victoria Logs + Grafana (multi-host) |
| `docs/` | Documentation site (served at `docs.pod.haus`) |
| `docs-server/` | nginx serving `docs/` |
| `kangaroo/` | Kangaroo-side Periphery compose + per-host overlays |

## Agents

[`AGENTS.md`](AGENTS.md) is the canonical instructions file for any AI
agent working in this repo. Claude Code reads it via
[`CLAUDE.md`](CLAUDE.md)'s `@AGENTS.md` import.
