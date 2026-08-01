# Pinelake migration

Bring the second household Mac mini (`home.pinelake.haus`, Apple M1, macOS)
under Komodo and podhaus management without losing Plex identity, Syncthing
state, or the data on its attached TerraMaster volume.

## Status

No pinelake server, linked repo, or stack is declared in this repo yet. The
only landed infrastructure is the existing Cloudflare DNS and Access
scaffolding in `terraform/dns_pinelake_haus.tf` and `terraform/access.tf`.

The host inventory was captured on 2026-05-13. Re-run the inventory checks
before migration because native applications, macOS, and disk usage may have
changed since then.

## Workstreams

1. [Inventory](inventory.md): revalidate the host snapshot immediately before
   making changes.
2. [Host bootstrap](host-bootstrap.md): resize Colima, create dockernet, install
   outbound Komodo Periphery, make boot behaviour explicit, and put Tailscale
   on a daemon-managed path.
3. [Flood](flood.md): replace the bare `docker run` container with a managed
   stack.
4. [Syncthing](syncthing.md): back up the native service first, then decide
   whether containerisation clears the Colima networking proof.
5. [Plex](plex.md): keep native initially, close the backup gap, and decide
   whether containerisation is worth losing VideoToolbox. This is the
   highest-risk stream.
6. [Cloudflare tunnel and Terraform](cloudflare-tunnel.md): move the host's
   tunnel ingress from local YAML into the consolidated Terraform root.
7. [Platform stacks](platform-stacks.md): add logging, Autoheal, Backrest, and
   Ofelia for pinelake.
8. [Monitoring](monitoring.md): add Gatus service checks and backup heartbeats.
9. [Network resiliency](network-resiliency.md): prove the tailnet fallback and
   decide whether any subnet routing is worth adding.

## Decisions needed before migration

1. **Plex location:** keep the native app, containerise in place after a
   staging proof, or move it to bilby. Keeping it native on Pinelake is the
   recommended first state.
2. **TerraMaster attachment:** confirm it stays attached to pinelake.
3. **Plex remote access:** keep Plex's own relay, add tailnet access, or add a
   `plex.pinelake.haus` Cloudflare route. Relay plus tailnet is the preferred
   starting point.
4. **Tunnel name:** keep the historical `torrent-pinelake` name or recreate it
   as `pinelake`. Keeping it avoids a cosmetic credential rotation.
5. **Access policy:** keep the three current Nathan-only applications or add
   a monitoring-specific service-token bypass. Add Family only if a pinelake
   service is intentionally shared.
6. **Cloudflared runtime:** keep the native LaunchDaemon and switch it to
   remotely managed config, or move it into Colima. Keeping the native daemon
   changes fewer things during migration.
7. **Syncthing runtime:** keep the native LaunchAgent, or containerise only
   after proving Colima's TCP, UDP, discovery, and loopback forwarding.
8. **Backup target:** use a local restic repository on TerraMaster with an
   OneDrive mirror, or build routing to the QNAP Jump repository. The local
   repository plus mirror has fewer dependencies.

Two platform decisions are already closed. Pinelake must use the current v2
outbound Komodo model, with no inbound port 8120, and replace the App Store
Tailscale client with a daemon-managed node on the podhaus management tailnet.

## Credentials and keys

- `Plex Token (pinelake)` in 1Password, copied from the existing native Plex
  preferences.
- A separate pinelake restic repository password.
- A separate pinelake rclone token and refresh-token chain.
- A Periphery private key on pinelake plus its committed public key under
  `komodo/keys/`. This follows Kangaroo and Kookaburra; it isn't a Komodo
  Variable.

Pinelake backup heartbeats reuse the general-purpose Gatus heartbeat token.
The Cloudflare Homelab service token already exists in Terraform, but its
client credentials still need a Terraform-managed 1Password item before Gatus
can use them for Pinelake HTTP probes.

## Safety rules

- Back up Plex and Syncthing before stopping their native services.
- Never start containerised Plex until the preferences init has verified the
  expected `MachineIdentifier`.
- Keep Syncthing's device identity and database together.
- Use directory bind mounts and absolute host paths.
- Keep secrets in 1Password and non-secret stack variables in TOML.
- Omit `deploy = true`; the push procedure is the deploy authority.
- Run Terraform only from the consolidated `terraform/` root.
