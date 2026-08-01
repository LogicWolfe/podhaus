# Pinelake Cloudflare tunnel and Terraform

Move pinelake's tunnel ingress from `/etc/cloudflared/config.yml` into the
consolidated Terraform root while keeping the native cloudflared LaunchDaemon.

## Current state

- Tunnel UUID: `fec5ca76-b634-4185-bdb2-f85c38b1b570`
- Tunnel name: `torrent-pinelake`
- DNS: `home`, `sync`, and `torrent` CNAMEs are already managed in
  `terraform/dns_pinelake_haus.tf`
- Access: three Nathan-only applications already exist in
  `terraform/access.tf`
- Ingress: local YAML on pinelake is still authoritative
- Terraform has no
  `cloudflare_zero_trust_tunnel_cloudflared_config.pinelake` resource

The 2026-05-13 host snapshot recorded these routes:

```yaml
ingress:
  - hostname: home.pinelake.haus
    service: ssh://localhost:22
  - hostname: torrent.pinelake.haus
    service: http://127.0.0.1:3000
  - hostname: sync.pinelake.haus
    service: http://127.0.0.1:8384
    originRequest:
      httpHostHeader: localhost
  - service: http_status:404
```

Re-read the live YAML before applying. Treat it as authoritative if it differs
from this dated snapshot.

## Target state

Terraform owns the tunnel config with `source = "cloudflare"`. The native
LaunchDaemon runs the named tunnel without `--config`, so cloudflared fetches
ingress from Cloudflare on connect. The old YAML is archived for rollback but
isn't active.

Keep the existing DNS records and Access applications inline for this change.
The current `pod_haus_service` module hard-codes the `pod.haus` suffix, and
three pinelake resources don't justify copying the module. Generalise the
module later only if another zone needs enough service instances to pay for
the abstraction.

## Implementation

1. Re-read Cloudflare provider documentation for
   `cloudflare_zero_trust_tunnel_cloudflared_config` at the repository's
   pinned provider version.
2. Add `cloudflare_zero_trust_tunnel_cloudflared_config.pinelake` to
   `terraform/tunnel.tf`. Use the live routes, preserve the Syncthing Host
   override, and keep the catch-all last.
3. Run `terraform plan`. The plan must add only the remote tunnel config; the
   existing CNAMEs and Access applications must remain unchanged.
4. Apply while pinelake still runs with `--config`. This records the remote
   config without changing the active path.
5. On pinelake, replace the config-driven command with an explicit connector
   command that still names tunnel
   `fec5ca76-b634-4185-bdb2-f85c38b1b570` and its existing credentials file,
   but does not load ingress from `config.yml`. Removing `--config` without
   supplying the tunnel identity would leave `tunnel run` with nothing to run.
6. Restart cloudflared and verify all three hostnames.
7. Rename the local YAML to `config.yml.archive`. Don't delete it until the
   remote path has soaked and rollback has been tested.

Keep backend addresses unchanged during the authority switch. Flood and any
later containerised Syncthing should publish loopback-only Mac ports so native
cloudflared can continue to use `127.0.0.1`. Do not replace these backends with
Docker service names or bilby's `172.18.0.1` pattern.

## Access-policy decision

The current applications allow Nathan only. That is valid for interactive use
but doesn't let Gatus probe through Access. Choose one of these before adding
public-path monitoring:

- Add the existing Homelab service-token bypass ahead of Nathan's allow policy.
- Keep the applications Nathan-only and monitor the services over LAN or
  tailnet instead.

Don't add Family access unless a pinelake service is meant to be household
shared.

## Verification

- `terraform plan` is clean after apply.
- `home.pinelake.haus` still opens SSH through Access.
- `torrent.pinelake.haus` serves Flood.
- `sync.pinelake.haus` serves Syncthing without a Host-header rejection.
- Stopping or renaming the archived local YAML doesn't affect a reconnect.
- A rollback that restores `--config` returns control to the local file.
