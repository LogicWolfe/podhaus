# Network resiliency

Pinelake has Cloudflare, Tailscale, and LAN paths today, but its Tailscale
node is on a separate tailnet from podhaus. This workstream moves the host
onto the podhaus management tailnet and proves that Cloudflare and tailnet
access fail independently.

## Current state

| Path | Endpoint | Constraint |
|---|---|---|
| Cloudflare tunnel | `home`, `sync`, and `torrent.pinelake.haus` | Native cloudflared, locally managed ingress |
| Existing Tailscale | `100.124.202.28` on `tailcfb5f.ts.net` | App Store IPNExtension, no watchdog, not the podhaus tailnet |
| LAN direct | `192.168.1.128:<port>` | In-house only, ISP router rather than UniFi |

The public IPv4 and IPv6 addresses recorded in `inventory.md` are audit
observations, not stable configuration inputs. Do not copy them into Komodo,
Gatus, or Terraform.

## Target state

- A supported unattended macOS Tailscale installation enrols with the
  Terraform-managed `tag:podnet` auth key and reconnects before user login.
- Pinelake Periphery dials `bilby-podnet.tail9ceb.ts.net:9120` by MagicDNS.
- Cloudflare continues to expose the intentional browser endpoints.
- Tailnet names provide an operator fallback without public port forwards.
- LAN services remain on `192.168.1.0/24`; podhaus does not pretend Pinelake
  has UniFi split-horizon DNS.

## Work

1. Complete the Tailscale cutover in [Host bootstrap](host-bootstrap.md).
   Treat the old `100.124.202.28` identity as disposable and verify the new
   node carries `tag:podnet`.
2. Confirm a Colima container can resolve and reach
   `bilby-podnet.tail9ceb.ts.net`. This gates outbound Periphery.
3. From bilby Gatus's network namespace, prove the reverse path to an
   intentional Pinelake test listener or `tailscale serve` endpoint by
   MagicDNS name. The daemon-wide Docker DNS configuration should make this
   work without `network_mode: host` or a sidecar.
4. Add Cloudflare-path service probes and a direct Pinelake Periphery state
   check as described in [Monitoring](monitoring.md).
5. Optionally add tailnet-path probes. A green tailnet check beside a failed
   Cloudflare check distinguishes an edge or connector fault from a backend
   fault.
6. Check the ISP gateway for accidental UPnP or port-forward exposure of Plex
   `32400` and Syncthing `22000`. The target state has no direct internet
   exposure for either port.
7. If Plex needs an operator fallback, use `tailscale serve` after the Plex
   exposure decision. Do not add another overlay network.

## Explicit non-goals

- No Headscale or ZeroTier second overlay.
- No Pinelake subnet router or exit node. Its `192.168.1.0/24` LAN collides
  with too many client networks.
- No UniFi gateway migration in this project.
- No second ISP unless remote access during a household WAN outage becomes a
  real requirement.

## Verification

- `tailscale status` on Pinelake shows the podhaus tailnet and `tag:podnet`.
- Bilby reaches Pinelake by MagicDNS and Pinelake reaches bilby the same way.
- Stopping cloudflared breaks only the Cloudflare probes; tailnet access stays
  available.
- Stopping tailscaled breaks only the management fallback; Cloudflare service
  access stays available.
- An external scan finds no unintended Plex or Syncthing listener.

## Deferred choices

- Whether household members need a documented tailnet Plex fallback.
- Whether parallel tailnet Gatus probes add enough signal to keep.
- Whether an external monitor of Gatus itself is worth another dependency.
