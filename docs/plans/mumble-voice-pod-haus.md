# Mumble at `voice.pod.haus`

Low-latency family voice chat. Single Murmur server on bilby, direct
WAN port-forward (no Cloudflare Tunnel — Mumble is not HTTP and UDP is
load-bearing for voice quality). Reinstates `cloudflare-ddns` for the
`voice.pod.haus` A record.

## Ingress decision

**Direct UDM port-forward on 64738/udp + 64738/tcp.** Lowest latency
for everyone on-continent, no extra hop. Cloudflare Tunnel can't carry
arbitrary UDP, and the kookaburra rathole relay would add ~40–60ms
Perth↔syd1 round-trip for the typical case (in-Perth family talking to
each other). Mumble's WAN-facing protocol surface has been pretty
clean historically and 64738 isn't a common scan target. UDM Pro SE
doesn't bind 64738 itself, so the WAN:443 shadow trap that killed the
old storage forward doesn't apply.

Re-evaluate if: (a) voice CVEs change the calculus, (b) someone moves
overseas and is the dominant talker (kookaburra route would then be
shorter for them), or (c) we ever want browser-based access (a
mumble-web client would need Tunnel+HTTPS for the WebSocket — separate
stack, additive, doesn't replace this).

## What gets built

### `mumble/` stack on bilby

- `mumble/compose.yaml` — single service.
  - Image: `mumblevoice/mumble-server:latest` (the official maintained
    image; env-based murmur.ini, sqlite at `/data`, drop-in friendly).
  - Ports: `64738:64738/tcp` + `64738:64738/udp` published on the
    host. Not `network_mode: host` — Murmur doesn't need device or
    multicast access, plain port publishing is the simpler shape and
    consistent with what we use elsewhere when host net isn't
    required.
  - Volumes: named volume `mumble-data:/data` (sqlite DB + auto-
    generated cert/key).
  - Networks: `dockernet` (no current cross-stack consumers; cheap to
    include for symmetry / future log shipping).
  - `restart: unless-stopped`, `autoheal: "true"` label.
  - Standard `podhaus.stack-content-hash` label per
    `tools/lint-stack-content-hash.py`.
- `mumble/stack.toml`
  - `tags = ["podhaus"]`, `files_on_host = true`,
    `run_directory = "/etc/komodo/repo/mumble"`.
  - No `deploy = true` (lint forbids it on podhaus stacks).
  - `environment` block wires:
    - `TZ=[[TZ]]`
    - `MUMBLE_SUPERUSER_PASSWORD=[[OP__KOMODO__MUMBLE__SUPERUSER_PASSWORD]]`
    - `MUMBLE_CONFIG_serverpassword=[[OP__KOMODO__MUMBLE__SERVER_PASSWORD]]`
      (the image maps `MUMBLE_CONFIG_<key>` directly into
      `murmur.ini`)
    - `MUMBLE_CONFIG_welcometext=<short greeting>`
    - `MUMBLE_CONFIG_registerName=pod.haus voice`
    - `MUMBLE_CONFIG_users=20` (cap, way over 5 family + headroom)
    - `MUMBLE_CONFIG_bandwidth=72000` (per-user kbps; ample for
      Opus high-quality)
- 1Password item `MUMBLE` in the Homelab vault with fields
  `SUPERUSER_PASSWORD` (root admin for `SuperUser` account) and
  `SERVER_PASSWORD` (the shared join password we'll hand to family).
  Both fields → `OP__KOMODO__MUMBLE__*` via komodo-op auto-sync.
  Bootstrap order: create the 1P item BEFORE the push so komodo-op
  has synced the var by the time Stage 2 deploys.

### `cloudflare-ddns/` stack reinstated (single instance on bilby)

Pattern was previously decommissioned at `49676d8` because the relay
made WAN IP irrelevant for `storage.pod.haus`. Voice brings the
need back. Use the same shape that already worked:

- `cloudflare-ddns/compose.yaml` — `favonia/cloudflare-ddns:latest`,
  `user: "1000:1000"`, `read_only: true`, `cap_drop: [all]`,
  `no-new-privileges:true`. Env:
  - `DOMAINS: voice.pod.haus` (only this name; explicitly NOT
    `storage.pod.haus` which is a static reserved IP and is
    TF-owned). Add additional names here as future non-HTTP services
    arrive.
  - `PROXIED: "false"` (grey-cloud — TF declares the record with
    matching `proxied = false`).
  - `IP6_PROVIDER: none` (IPv4 only; we don't manage AAAA).
  - `UPDATE_CRON: "@every 5m"`.
  - `CLOUDFLARE_API_TOKEN: ${CLOUDFLARE_API_TOKEN}` (sourced from
    the existing `OP__KOMODO__CLOUDFLARE_API_TOKEN__CREDENTIAL`
    var; already in komodo-op).
- `cloudflare-ddns/stack.toml` — `tags = ["podhaus"]`,
  `files_on_host = true`, env block wires `TZ` +
  `CLOUDFLARE_API_TOKEN`. (Matches the prior shape recovered from
  `49676d8^`.)
- Verify the CF API token in 1P still has DNS-edit scope on
  `pod.haus` zone (it did before; it should still). If not, mint a
  replacement via the existing token UI flow and update the 1P item.

### Terraform additions

- `terraform/dns_voice_pod_haus.tf` (new file, per the
  one-file-per-DNS-name convention):
  - `cloudflare_dns_record.voice_a` — A, `voice.pod.haus`, grey-cloud
    (`proxied = false`, ttl 300), `lifecycle.ignore_changes = [content]`
    (DDNS owns the value, TF owns existence). Mirror the `settings { …
    ignore_changes }` shape from `dns_storage.tf` to suppress
    cosmetic drift.
- `terraform/unifi.tf` (or `dns_unifi_split_horizon.tf` — pick the
  one that already declares `unifi_*` resources; `unifi.tf` doesn't
  exist today, so it'll either be a new file or an addition to the
  existing UniFi DNS file). Add:
  - `unifi_port_forward.mumble_udp` — WAN udp/64738 → bilby
    (10.0.0.119) udp/64738.
  - `unifi_port_forward.mumble_tcp` — WAN tcp/64738 → bilby
    (10.0.0.119) tcp/64738.
  - Resource shape from the prior `unifi_port_forward.minio_caddy_https`
    pattern at commit `24008f0` (now deleted but recoverable).
  - Validate the provider's UDP / dual-protocol support before
    applying — the prior forward was TCP-only; if `protocol = "udp"`
    or `protocol = "tcp_udp"` isn't supported in our pinned
    `ubiquiti-community/unifi` version, fall back to two single-
    protocol resources (which is the shape above).

### Backup

Add the `mumble-data` named volume to backrest's source list so the
SQLite DB + server cert survive a bilby rebuild. Conventional bind
path in backup's compose.shared volume mapping. Verify a first
snapshot lands after the stack stabilises.

### Gatus

Add a TCP-only endpoint to `gatus/conf/config.yaml`:

```yaml
  - name: Mumble
    url: "tcp://voice.pod.haus:64738"
    interval: 1m
    conditions:
      - "[CONNECTED] == true"
```

This proves: DDNS is current, UDM forward is intact, Murmur is up,
and the host firewall isn't dropping. It does NOT prove UDP works —
voice quality has to be verified by ear on first connect (and after
any networking change). UDP is harder to synthetically probe; the TCP
control channel coming up is a strong proxy for the deploy working.

## Order of operations

1. Create the `MUMBLE` 1P item with both passwords. Wait for komodo-op
   to surface `OP__KOMODO__MUMBLE__*` (visible in Komodo UI).
2. Write `mumble/{compose.yaml,stack.toml}`. Push. Stage 2 deploys
   it; container comes up but is unreachable from WAN (no forward
   yet).
3. Write `cloudflare-ddns/{compose.yaml,stack.toml}`. Push. Container
   comes up and (with no existing `voice.pod.haus` record yet) won't
   succeed at updating — that's fine for one cycle; TF will create
   the record next and DDNS will then own its content.
4. Apply Terraform: DNS record + UDM port-forwards in a single plan.
   Confirm `dig voice.pod.haus` returns the home WAN IP within
   ~5–10min (initial DDNS tick).
5. Test from off-LAN (phone on cellular, or any non-Tailscale device):
   Mumble client → `voice.pod.haus`, accept self-signed cert, enter
   server password. Confirm voice works both directions.
6. Add Gatus endpoint, push.
7. Add `mumble-data` to backrest sources, push. Verify the next
   scheduled snapshot picked it up.

## Out of scope (notes for later, not now)

- **mumble-web browser client.** Separate stack, HTTP+WebSocket
  surface behind Cloudflare Tunnel + Access. Lets non-installers join
  via browser. Worth doing if family balks at installing the desktop
  client.
- **Certificate-pinned per-user identity.** Mumble supports
  per-user certs (no shared password). Skipped for now — server
  password is enough for 5 trusted people.
- **Channel structure / ACLs.** Default channel is fine for a
  family-sized server. Configure later via the desktop client's
  SuperUser admin.
- **Mobile push for "someone joined".** Mumble doesn't natively do
  notifications. Could be added via a Gatus-style watcher hitting the
  TCP port and counting users via the optional ICE/RPC interface, but
  not worth the surface.

## Reminders

- Mumble's TLS cert is self-signed by Murmur on first start. Clients
  will prompt to trust it once. Don't try to terminate TLS at Caddy —
  Mumble does its own TLS as part of the protocol.
- `voice.pod.haus` is the FIRST and only public DNS name pointing at
  the home WAN IP after this lands. Future "I need to expose another
  non-HTTP service" cases extend `DOMAINS:` in cloudflare-ddns and
  add a TF record alongside.
- Per AGENTS.md hard rules: no `deploy = true`, content-hash labels
  consumed correctly (pre-commit lint will catch), bind mounts use
  absolute host paths (mumble uses a named volume so this is moot
  here).
