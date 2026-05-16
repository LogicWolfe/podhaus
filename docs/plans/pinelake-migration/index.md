# Pinelake migration

Bring the second household Mac mini (`home.pinelake.haus`,
`Baxters-Mac-mini.local`, Apple M1, macOS 26.2) under Komodo + podhaus
management with **zero state loss** — especially for the native Plex
install — and lift its DNS / tunnel / Access provisioning into the same
Terraform model that already covers bilby.

This plan is the inventory + decision matrix + per-stream migration
plan. No timelines, no implementation work yet — investigation +
planning only.

## Status

Nothing migrated. Live snapshot of pinelake as observed
2026-05-13 — see [Inventory](inventory.md) for the full state. Summary:

| Component | Current state | Target state |
|---|---|---|
| Container runtime | Colima (Lima/vz) — 1 profile, 2 CPU / 2 GiB RAM, virtiofs mounts | Same colima, resized to ≥ 4 CPU / 8 GiB RAM, dockernet added |
| Auto-start | Hand-rolled `colima-start-wait.sh` LaunchDaemon + `unless-stopped` | Same wrapper, kept (it solves a real boot race) |
| Komodo Periphery | None | Periphery container managed by colima (linked-repo mode, like kangaroo) |
| rtorrent-flood | One bare `docker run` container, no compose, no project | `flood/pinelake/` stack under Komodo |
| Plex | **Native macOS app**, 22 GB state, identity present, no backup | Containerised under Komodo with identity preserved (see [Plex](plex.md)) |
| Syncthing | Native Homebrew + LaunchAgent, 345 MB state | Containerised under Komodo with config + DB preserved |
| cloudflared | Native LaunchDaemon, config on-host (`/etc/cloudflared/config.yml`) | TF-managed CF-side config (`source = "cloudflare"`), tunnel still daemon-run OR moved to compose |
| DNS records (`*.pinelake.haus`) | TF-managed already | Unchanged; keep |
| Access apps (3) | TF-managed already (Nathan-only) | Optionally normalise to a `pinelake_service` module mirroring `pod_haus_service` |
| Tunnel ingress | On-host YAML, not in TF | `cloudflare_zero_trust_tunnel_cloudflared_config.pinelake` in TF |
| Logs | None shipped off-host | Alloy on pinelake → bilby's ClickStack collector (cross-LAN OTLP, matches kangaroo) |
| Backups | **None** (no Time Machine, no rsync, no Backrest) | Local Backrest restic repo on TerraMaster, mirrored to OneDrive |
| Autoheal | None | Local autoheal container (matches bilby + kangaroo) |
| Scheduling / cron | None | Local ofelia (host-side cron pattern, runs Plex DB optimise / log rotation / etc.) |
| Health checks | None — Cloudflare can answer 200 with the backend down | Gatus probes from bilby on each `*.pinelake.haus` hostname + push heartbeats |
| Sleep behaviour | `pmset` already correct (`sleep 0`), no idle-sleep observed in 25 days, but power button + GUI sleep both unprotected | Pin `pmset` settings via LaunchDaemon, suppress power-button sleep, add `caffeinate -i -s` as belt-and-braces |
| Tailscale | App Store build (no CLI), per-user IPNExtension, no LaunchDaemon watchdog | Switch to homebrew `tailscaled` LaunchDaemon, install CLI, optionally `tailscale serve` Plex |

## Plan structure

Independent streams — each can be planned or executed on its own.

1. [**Inventory**](inventory.md) — full current state. Reference for
   every other doc here.
2. [**Host bootstrap**](host-bootstrap.md) — resize colima, create
   dockernet, install Komodo Periphery, fix sleep, install Tailscale
   CLI. The platform foundation everything else builds on.
3. [**Flood / rtorrent**](flood.md) — easiest stream. Move the one
   existing container into a real compose stack under Komodo.
4. [**Syncthing**](syncthing.md) — containerise the native install
   without losing the index DB or peer relationships.
5. [**Plex**](plex.md) — **the highest-risk stream.** Identity
   preservation, macOS `defaults` → `Preferences.xml` translation,
   22 GB of state, no current backup, library paths bound to
   `/Volumes/TerraMaster`.
6. [**Cloudflare tunnel + Terraform**](cloudflare-tunnel.md) — move
   ingress rules from on-host YAML into TF, mirror the
   `pod_haus_service` module pattern, decide on Access policy chain.
7. [**Platform stacks**](platform-stacks.md) — the four multi-host
   shared services pinelake joins: **logging** (Alloy → bilby's
   ClickStack collector via cross-LAN OTLP), **autoheal** (local),
   **backup** (local Backrest →
   TerraMaster restic repo → OneDrive mirror), **scheduling** (local
   ofelia). Per-host overlays only.
8. [**Monitoring**](monitoring.md) — Gatus checks + push heartbeats
   for pinelake services from bilby's existing Gatus.
9. [**Network resiliency**](network-resiliency.md) — verify Tailscale
   is a viable fallback when Cloudflare is down, add `tailscale serve`
   for Plex, decide on exit-node / subnet-router, decline a second
   overlay.

## Open decisions (need user input before any migration step)

These are the calls that can't be made automatically — list-form so
they're easy to walk through.

1. **Plex hosting model** —
   (a) keep on pinelake, containerise in place (recommended; media
   stays where it is, identity is preserved, matches bilby's pattern);
   (b) consolidate onto bilby (would require copying 6.5 TB media
   across the LAN or physically moving the TerraMaster, and either
   accepting library-path rewrites or symlinking); (c) per-household
   Plex (current de-facto state but unmanaged).
2. **TerraMaster volume** — stays attached to pinelake under option
   1a above; this is the simplest path. Confirm.
3. **Plex public exposure** — there is **no** `plex.*` ingress today
   on pinelake. Add a `plex.pinelake.haus` tunnel ingress + Access
   app, expose Plex only over LAN + tailnet (recommended — Plex's own
   relay handles remote access), or keep current state (`PublishServer
   OnPlexOnlineKey=1` only).
4. **Tunnel name** — the existing tunnel is named `torrent-pinelake`
   (historical). Rename to `pinelake` for clarity? Cosmetic only;
   requires recreating credentials. Default: leave.
5. **Access policy chain on `*.pinelake.haus`** — current Access apps
   are Nathan-only with no Family / Homelab tokens. Options: keep
   household-private; add the Homelab service token bypass so
   automation (e.g. Gatus) can probe without UI auth (recommended);
   add Family group for shared access.
6. **Cloudflared deployment shape** — current native LaunchDaemon
   keeps working with TF-managed config (`source = "cloudflare"`) and
   is the minimum-change path. Alternative: replicate bilby's
   `cloudflare-tunnel/` compose stack on pinelake. Default: keep
   LaunchDaemon (reduces moving parts during the migration).
7. **Komodo Periphery auth model** — Periphery v2 keypair auth lands
   for bilby + kangaroo on a separate stream
   ([Periphery v2 auth](../alligator-bilby-migration/periphery-v2-auth.md)).
   Bring pinelake up on whichever model is canonical at the time;
   don't introduce a third auth path mid-flight.
8. **Tailscale daemon shape** — App Store build (current) has no
   LaunchDaemon, can't be watchdog'd, doesn't expose CLI by default.
   Switching to Homebrew `tailscaled` (recommended) makes it a real
   daemon and enables `tailscale serve`. Tradeoff: loses the menu-bar
   UI niceties.
9. **Router** — pinelake LAN is `192.168.1.0/24` behind an ISP-style
   gateway (not UniFi). Long-term: matching bilby's UniFi setup
   (`10.0.0.0/24`) makes docs/runbooks transfer cleanly. Out of scope
   for this migration but flagged.
10. **Backup target for pinelake** — restic repo location. Options:
    on the TerraMaster itself (cheap, but no off-host until the
    OneDrive sync runs); on the same Jump volume as bilby/kangaroo
    over NFS/SMB (requires a route from pinelake's network to the QNAP
    LAN — not currently routable). Default: local TerraMaster repo +
    OneDrive mirror, matching kangaroo's "primary + mirror" topology.

## Credentials that will need 1Password Homelab vault entries

For the new stacks. Each becomes a Komodo Variable via `komodo-op`.

- `Plex Token (pinelake)` — the existing `PlexOnlineToken` from
  `~/Library/Preferences/com.plexapp.plexmediaserver.plist`. Used by
  the Plex Preferences init container.
- `Gatus Backrest pinelake push token` — separate from bilby's and
  kangaroo's. Mirrors the existing `GATUS_BACKREST_*_PUSH_TOKEN`
  pattern.
- `Restic Repo password (pinelake)` — separate repo, separate
  password. New 1Password item.
- `Komodo Periphery passkey OR keypair` — depends on auth model
  decision (#7 above).

## Hard rules (reminders for the implementers)

These come from [AGENTS.md](/AGENTS.md) and the existing runbooks. Worth
restating because every one of them is relevant here:

- **Never single-file bind mounts.** Always bind the containing
  directory. macOS atomic-rename saves orphan the inode.
- **Always absolute host paths** in bind mounts —
  `${PODHAUS_REPO}/<stack>/...`.
- **Never create Komodo Variables in the UI** — 1Password is the
  source of truth.
- **Plex identity is sacred.** Plex never starts without an init
  container confirming `Preferences.xml` has the expected
  `MachineIdentifier`. See [Plex](plex.md) + the existing
  [Plex runbook](/runbooks/plex.html).
- **Don't push, deploy, or apply TF without explicit authorization.**
  Investigation done here is non-mutating; nothing has changed on
  pinelake, in the repo (this plan aside), or in Cloudflare.

## Cross-references

- [Architecture](/architecture.html)
- [Stack conventions](/stack-conventions.html)
- [Komodo](/komodo.html)
- [Secrets](/secrets.html)
- [Storage](/storage.html)
- [Backup & recovery](/backup-and-recovery.html)
- [Networking](/networking.html)
- [Terraform](/terraform.html)
- [Plex runbook](/runbooks/plex.html) + [Plex maintenance log](/runbooks/plex-maintenance.html)
- [Syncthing runbook](/runbooks/syncthing.html)
- [Flood runbook](/runbooks/flood.html)
