# Network resiliency

Pinelake is reachable today via three independent paths: Cloudflare
tunnel, Tailscale, and LAN-direct. This stream is about strengthening
that picture without overengineering — Tailscale + Cloudflare already
fail independently, which covers most realistic failure modes.

## Current paths

| Path | Endpoint | What's behind it | Independent of |
|---|---|---|---|
| Cloudflare tunnel | `*.pinelake.haus` (CF anycast → tunnel) | cloudflared → backend services | Tailnet (CF and TS share only ISP) |
| Tailscale | `100.124.202.28` / MagicDNS (`pinelake.<tailnet>.ts.net`) | Anything bound to `0.0.0.0` on the host | CF Access / cloudflared health |
| LAN direct | `192.168.1.128:<port>` | Same `0.0.0.0` bindings | Everything else; in-house only |

Network configuration:

- Ethernet `en0`, gigabit, `192.168.1.128/24`, gateway `192.168.1.1`
  (ISP-style, **not UniFi**)
- IPv6 SLAAC active (`2605:59c0:5499:d500::/64`); v6 ping to Cloudflare
  ~20 ms — dual-stack healthy
- WiFi `en1` powered off — good, Ethernet-only
- Public v4: `129.222.137.223`
- Tailnet `tailcfb5f.ts.net`; addresses `100.124.202.28` (v4) and
  `fd7a:115c:a1e0:ab12:4843:cd96:627c:ca1c` (v6); MTU 1280

## Failure-mode matrix

| Failure | CF path | Tailnet | LAN |
|---|---|---|---|
| `cloudflared` crashes / mis-config | **DOWN** | up | up |
| CF Access policy issue / outage | **DOWN** | up | up |
| Tailscale control plane / DERP outage | up | **DOWN** (existing direct WG sessions persist briefly) | up |
| `IPNExtension` (App Store) crashes on host | up | **DOWN** | up |
| `tailscaled` LaunchDaemon (post-migration) crashes | up | DOWN, restarted by launchd | up |
| ISP outage | **DOWN** | **DOWN** | up (LAN only — useless for remote) |
| LAN gateway reboot | DOWN | DOWN | up briefly during gateway boot |
| Plex / Syncthing / Flood crashes | service-specific (autoheal recovers) | service-specific | service-specific |

Key takeaways:

- **Cloudflare and Tailscale fail independently.** Tailscale is the
  natural fallback for "cloudflared is broken"; the converse is also
  true. Adding a third overlay (Headscale, ZeroTier, second
  cloudflared) shares ISP failure with both and adds maintenance
  surface for ~zero additional resiliency gain. **Skip.**
- The only "easy" gap is **IPNExtension lacks a watchdog** on the
  App Store build. Solved by moving to `tailscaled` LaunchDaemon
  (see [Host bootstrap](host-bootstrap.md), step 6). Post-migration,
  Tailscale gets the same launchd-managed restart behaviour as
  cloudflared.

## Recommendations

### Cheap, high-value (recommended)

1. **Move to `tailscaled` LaunchDaemon.** Covered in
   [Host bootstrap](host-bootstrap.md). Restores the watchdog,
   exposes the CLI, enables `tailscale serve`.
2. **`tailscale serve` for Plex.** One command exposes Plex at
   `https://pinelake.<tailnet>.ts.net` with a real TLS cert. Fallback
   for "Plex relay is down" or "Cloudflare Access is being weird."
   See [Plex](plex.md) → public exposure decision.
3. **Tailnet-side Gatus probes.** Probe each pinelake service over
   both the Cloudflare hostname and the tailnet name. If CF probe
   fails while tailnet is green, the service is healthy and the
   issue is on the CF path (alerting can route differently). See
   [Monitoring](monitoring.md).
4. **MagicDNS-only references in Komodo + Gatus configs.** Never pin
   raw tailnet IPs — they can rotate on auth changes. Use
   `pinelake`, `bilby`, etc. via MagicDNS.
5. **External port-scan of `129.222.137.223`** to confirm no UPnP /
   port-forward rule on the ISP gateway is silently exposing Plex
   `:32400` or Syncthing `:22000` to the public internet. The
   services are bound to `0.0.0.0`; without a forward rule they're
   only on the LAN side, but home routers occasionally surprise.

### Worth considering

6. **Health-check the tunnel from outside.** Bilby Gatus probes
   `*.pinelake.haus` over the Cloudflare path already. If both
   Cloudflare and bilby's tunnel are degraded simultaneously, Gatus
   wouldn't alert (Gatus itself is unreachable). Add a probe
   **into** Gatus from an external monitoring service (uptimerobot
   free tier, or similar) so a total CF outage is still alerted.
   Low-effort, low-cost, defense in depth.
7. **Document `tailscale serve` access patterns in the household.**
   If Plex / Flood / etc. are reachable via tailnet, household
   members need to know which path to use when the public one is
   down. A short runbook entry suffices.

### Skip / not recommended

- **Headscale or ZeroTier as a "second tunnel".** Adds two
  control-plane dependencies (Headscale server, or ZT central) and
  another LaunchDaemon. Doesn't survive ISP failure. Same scope as
  Tailscale.
- **Subnet routing or exit-node from pinelake.** `192.168.1.0/24`
  collides with the most common home-LAN range; advertising it as a
  subnet route causes routing breakage for tailnet clients on
  similar networks. Skip.
- **Failover WAN (second ISP).** Only useful if remote access during
  primary ISP outage is critical. The current pattern doesn't
  warrant it.

## ISP gateway / router

The LAN is `192.168.1.0/24` behind an ISP-style gateway (not UniFi).
Bilby's LAN is `10.0.0.0/24` UniFi. Two implications:

- **Documentation transfer**: parts of the
  [Networking](/networking.html) doc reference UniFi-specific
  behaviour (split-horizon DNS via the UniFi provider in
  `terraform/dns_unifi_split_horizon.tf`). None of that applies to pinelake until a
  UniFi gateway lands.
- **Future option**: replacing the ISP gateway with UniFi gear
  (USG/UDM + an AP) would let pinelake join the same
  `10.0.0.0/24`-style internal-DNS model bilby uses. Out of scope
  for this migration; flagged as a future improvement.

## IPv6

Pinelake has working IPv6 SLAAC and a real public prefix
(`2605:59c0:5499:d500::/64`). Cloudflare is dual-stack. Today's tunnel
ingress is IPv4-only because the macOS daemon negotiates v4 first;
v6 connectivity is verified end-to-end via ping but not exercised by
the workload. Worth flagging that pinelake's IPv6 is a free path
not currently being used — possible future utility if v4 ever has
issues.

## Acceptance criteria

- `tailscaled` LaunchDaemon running, `tailscale status` works from
  the shell
- Tailnet IP either preserved (`100.124.202.28`) or all references
  updated to the new value
- `tailscale serve --bg --https=443 http://localhost:32400` (if Plex
  decision lands here) returns Plex UI at
  `https://pinelake.<tailnet>.ts.net`
- bilby Gatus shows green probes via CF path for all `*.pinelake.haus`
  endpoints
- (Optional) bilby Gatus has tailnet-path probes for the same
  services; both green most of the time, divergence triggers alert
- (Optional) External uptime check fires on bilby Gatus being down

## Open items deferred

- External uptime monitor choice (UptimeRobot free, Healthchecks.io,
  homerolled). Low priority.
- Tailnet Gatus probes — depends on bilby Gatus being able to make
  outbound tailnet calls
- UniFi gateway swap — long-term, not part of this migration
