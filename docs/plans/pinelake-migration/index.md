# Pinelake migration

Bring the second-household Mac mini under Komodo without losing Plex identity,
Syncthing state, or attached TerraMaster data.

## Status

No Pinelake server, linked repo, or stack exists yet. Re-run the 2026-05-13
[inventory](inventory.md) before changing the host.

The Numbat migration changed the network target. Old Cloudflare Tunnel and
Tailscale sections in the workstream notes are superseded. Pinelake will use
narrow outbound connections to Numbat:

- Periphery to `core-connect.pod.haus`, authenticated by Komodo Noise keys.
- Alloy to `logs-ingest.pod.haus`, authenticated by per-host mTLS and the
  ClickStack ingestion key.
- Named rathole services only for browser or SSH endpoints that are intentionally
  exposed. Pomerium and Pocket ID apply the Nathan-only policy.
- No Tailscale node, subnet route, bridged network, or Pinelake cloudflared
  runtime. Cloudflare remains authoritative DNS; Pinelake service records are
  DNS-only.

## Workstreams

1. Revalidate the [inventory](inventory.md).
2. [Bootstrap](host-bootstrap.md) Colima, dockernet, outbound Periphery, host
   keys, and reboot behaviour using Numbat's outbound contract.
3. Bring [Flood](flood.md) and [Syncthing](syncthing.md) under Komodo without
   changing identity or data.
4. Keep [Plex](plex.md) native initially, close its backup gap, and preserve its
   `MachineIdentifier`.
5. Add [platform stacks](platform-stacks.md), including Alloy through Numbat,
   then add [monitoring](monitoring.md).
6. Replace the old Tunnel/Tailscale workstreams with the Numbat route and DNS
   changes above.

## Decisions still needed

- Keep Plex native on Pinelake or move it after a separate VideoToolbox proof.
  Native is the starting state.
- Confirm the TerraMaster remains attached.
- Keep Syncthing native or containerise only after Colima TCP, UDP, discovery,
  and loopback forwarding are proven.
- Choose the backup repository location. A local TerraMaster repository with an
  independent OneDrive mirror has the fewest network dependencies.

## Credentials and safety

Pinelake needs a Komodo Periphery keypair, a log-ingest client certificate, and
service-specific rathole tokens only for routes actually exposed. Terraform and
1Password own the public keys, DNS, PKI, and secret handoffs.

Back up Plex and Syncthing before stopping native services. Never start a moved
Plex instance until the expected `MachineIdentifier` is verified. Preserve
Syncthing's device identity and database together. Use directory binds,
absolute host paths, the consolidated Terraform root, and the existing Komodo
push procedure.
