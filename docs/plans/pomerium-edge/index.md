# Pomerium edge migration

## Goal

Move Kookaburra to BinaryLane Perth and make it the public gateway for podhaus.
Pomerium and Pocket ID replace Cloudflare Access. Internal hosts keep
outbound-only connections, and Tailscale leaves the steady-state design.

The current DigitalOcean, Cloudflare Tunnel, Access, and Tailscale paths remain
authoritative until cutover.

## Architecture

- Start with BinaryLane's smallest Standard plan in Perth: 1 vCPU, 1 GB RAM,
  20 GB NVMe, 1 TB transfer, and two public IPv4 addresses.
- Run Pomerium Core all-in-one on Kookaburra with Pocket ID as its identity
  provider.
- Use named outbound rathole services. Kookaburra gets no route into either
  home network.
- Keep Cloudflare for authoritative DNS and as the CDN for public websites.
- Keep the old gateway live for rollback. Pinelake isn't part of this work.

The addresses have complementary owners, so no TCP multiplexer is needed:

| Address | TCP 22 | TCP 80 | TCP 443 | TCP 2333 |
|---|---|---|---|---|
| Application IP | Forgejo rathole | Pomerium ACME and redirect | Pomerium HTTP | Closed |
| Relay IP | Pomerium native SSH | Closed | Public TLS rathole | rathole control |

Protected browser names, including `git.pod.haus`, resolve to the application
IP. Pomerium reaches a private Bilby Caddy listener through a loopback-bound
rathole service. Raw APIs, machine endpoints, Pocket ID, UniFi, and public
sites resolve to the relay IP and reach Caddy's public listener directly.

Caddy's public listener contains no protected virtual hosts. Its private
listener requires a client certificate mounted only into Pomerium, which stops
a compromise of the public rathole container becoming a Pomerium bypass. Both
paths also use rathole Noise transport and separate service tokens.

This removes HAProxy, SNI inspection, PROXY protocol, Pomerium's high SSH port,
and public recovery SSH. Pomerium receives HTTP client addresses directly.
Kookaburra itself is a Pomerium SSH route; the BinaryLane console is the
break-glass path. Bootstrap uses application-IP port 22 temporarily, then
closes host sshd there before the Forgejo relay starts.

Host SSH uses commands such as `ssh nathan@bilby@ssh.pod.haus`. Each route pins
the Pocket ID subject and allowed Unix username. Bilby and Kookaburra trust the
Pomerium user CA through committed host configuration. Voltaire's CA trust,
rathole client, and sshd configuration remain machine-local; this repo owns
only its gateway route, DNS, and 1Password secret. Forgejo stays conventional:
`git@git.pod.haus` reaches its embedded SSH server with the original key.

Periphery connects outward through `core-connect.pod.haus` and keeps Komodo's
Noise authentication. Alloy sends to `logs-ingest.pod.haus`, where Caddy
requires per-host mTLS and the ClickStack key. After both paths survive a real
reboot, remove Tailscale, MagicDNS, and the Docker DNS overrides.

Terraform provisions a supported Debian stable image and both addresses from
the existing consolidated root. Prove create, refresh, no-op, resize, replace,
and secondary-address handling on a disposable server first. Committed
nftables rules allow only the address and port pairs above. The steady-state
containers are Pomerium, rathole, Periphery, and Alloy.

Pomerium Autocert uses Let's Encrypt HTTP-01 on the application IP. Caddy keeps
DNS-01 for its certificates. Pomerium's replaceable certificate cache persists
at `/data/autocert`; Databroker remains in memory. Long-lived keys and secrets
stay in 1Password, so Kookaburra holds no irreplaceable state.

Start at 1 GB. Upgrade to 2 GB if free memory stays below 25 percent, swap or
OOM activity appears, or bursts cause memory-driven latency. Move to 4 GB and
2 vCPUs if CPU saturation remains after the memory upgrade.

The second IP may provide limited isolation when BinaryLane blackholes an
attacked address, but both addresses share one VM and uplink. Do not add
failover or duplicate services for that incidental benefit.

Bilby's flat `dockernet` trust domain remains [separate technical
debt](../tech-debt.md); this migration must not absorb that redesign.

## HTTP and identity

Cloudflare proxies and caches only:

- `nathanbaxter.com` and `www.nathanbaxter.com`
- `skycroeser.net` and `www.skycroeser.net`
- `pets.indigopod.au`
- `stats.nathanbaxter.com`, `stats.skycroeser.net`, and
  `stats.indigopod.au`, limited at Caddy to `/script.js` and `/api/send`

Every other migrated name is DNS-only. `stats.pod.haus` remains the protected
Umami dashboard. Cloudflare handles HTTP redirects for proxied sites; DNS-only
endpoints are HTTPS-only. Authenticated content and API writes aren't cached.

Pomerium applies the Family policy by default and the Nathan-only policy to
Syncthing and the development service.

| Mode | Services |
|---|---|
| Pomerium plus native Pocket ID OIDC | Forgejo, Komodo, MinIO Console, Gatus |
| Pomerium assertion accepted directly | Fenwick, keyed by Pocket ID issuer and subject |
| Pomerium as the public login | Docs, Flood, Backrest, Syncthing |
| Pomerium plus existing application login | Paperless, Home Assistant, Plex, Music Assistant, HyperDX, Bugsink, Umami, QTS |
| Application login only through public Caddy | UniFi |
| Public through Caddy | Pocket ID, Pets, and the static sites |

Forgejo keeps its Pocket ID groups, admin mapping, and SSH key claim
synchronisation. No generic auth shim is part of this project.

## Machine and protocol exceptions

There is no broad replacement for the Cloudflare Homelab service token. Each
exception is an exact hostname or path.

| Surface | Gateway rule | Application check |
|---|---|---|
| `storage.pod.haus`, `*.storage.pod.haus`, `pouch.pod.haus` | Raw TLS through public Caddy | MinIO SigV4 |
| `git.pod.haus:22` | Raw rathole TCP | Forgejo SSH key |
| Forgejo LFS | Public Pomerium route matching `^/[^/]+/[^/]+\.git/info/lfs(?:/.*)?$` | Short-lived Forgejo LFS JWT |
| `paperless-api.pod.haus/api/*` | Public Caddy route plus a Paperless gateway token | Paperless API token |
| `watch.pod.haus/api/mcp` | Public Pomerium route plus an MCP gateway token | HyperDX personal API key |
| `komodo.pod.haus/listener/github/*` | Exact public Pomerium route | Existing GitHub HMAC |
| Per-site Umami `/script.js` and `/api/send` | Cloudflare to exact public Caddy paths | Umami ingestion validation |
| `unifi.pod.haus` | Public Caddy route | UniFi credentials |
| `id.pod.haus` | Public Caddy route | Pocket ID passkey and OIDC protocol |
| `core-connect.pod.haus` | Public Caddy WSS route | Komodo Noise keys |
| `logs-ingest.pod.haus` | Public Caddy HTTPS route | Per-host mTLS and ClickStack key |

The Paperless and MCP gateway tokens are separate random secrets in 1Password
and are checked by Caddy. Their public routes can't capture the corresponding
browser traffic. The Komodo exception is also path-scoped.

The Forgejo LFS route precedes the protected catch-all and passes Bearer tokens
unchanged. Git smart HTTP stays disabled; Forgejo REST, packages, archives,
attachments, and the website remain protected.

Plex media and native clients keep Plex's own path. Music Assistant's Home
Assistant websocket stays LAN-direct. Neither flow traverses Kookaburra.

## Implementation

1. Add BinaryLane to the consolidated Terraform root and pass the disposable
   lifecycle proof. Provision both addresses, Debian, nftables, temporary setup
   SSH, and no Tailscale.
2. Deploy Pomerium, rathole, Periphery, and Alloy with explicit address binds.
   Add the Pocket ID client, policies, Autocert volume, SSH CA, and origin
   client certificate through Terraform and 1Password.
3. Split Caddy into public and protected listeners. Add the origin, raw TLS,
   Forgejo SSH, host SSH, Komodo, and log-ingest rathole paths. Prove
   Kookaburra has no routed access to either LAN.
4. Declare every browser route and machine exception in committed config.
   Update Paperless iOS and HyperDX MCP to use their scoped gateway tokens.
5. Cut Gatus to a temporary DNS-only canary and exercise every protocol. Then
   use one Terraform apply for the remaining DNS cutover. Keep the old gateway
   and rollback values intact; a short outage is acceptable.
6. After 48 hours and one Kookaburra reboot, remove DigitalOcean, migrated
   Tunnel and Access resources, browser SSH, Bilby and Kookaburra Tailscale,
   temporary bootstrap access, and obsolete 1Password items. Leave Pinelake's
   Cloudflare resources untouched.
7. Update the durable architecture, networking, hosts, monitoring, Terraform,
   backup, disaster-recovery, Pocket ID, Forgejo, and service runbooks. Then
   update the Pinelake plans to use the proven gateway contract and delete this
   plan.

## Rollback

Keep the old tunnel targets and DigitalOcean relay addresses as explicit
Terraform rollback values. Rollback restores protected names to their tunnel
CNAMEs and raw services to DigitalOcean without changing application state.

Do not remove the old relay until an off-LAN workstation can initialise the
Terraform backend at `https://storage.pod.haus`, perform a no-op plan, and
complete a harmless state write through BinaryLane.

## Verification

- External scans find only application-IP ports 22, 80, and 443, plus relay-IP
  ports 22, 443, and 2333. Host sshd isn't public after bootstrap.
- Unknown hosts, wrong-address requests, missing origin certificates, and
  invalid rathole tokens fail. Protected requests can't reach Caddy without a
  valid Pomerium session.
- Family, Nathan-only, logout, Pocket ID outage, native OIDC, and Fenwick
  assertion validation match their policies.
- Forgejo clone, push, `ssh -T`, and LFS operations work. Host SSH reaches
  Bilby, Voltaire, and Kookaburra through Pomerium on port 22.
- Paperless iOS and HyperDX MCP require both gateway and application tokens.
  Webhooks, Umami ingestion, UniFi login, and Pocket ID discovery work.
- S3 path-style and virtual-host requests, SigV4, uploads, ranges, WebSockets,
  SSE, Home Assistant, Plex, and Music Assistant pass real-client tests.
- Periphery and Alloy recover after tunnel, container, and host restarts with
  no Tailscale dependency.
- The 1 GB node passes idle, login-burst, sustained proxy, large-transfer,
  config-reload, and simultaneous Komodo-deploy measurements.
- Terraform plans to no change from two credentialled machines, including one
  outside the LAN.
