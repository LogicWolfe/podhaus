# Pomerium edge migration

Status: cut over on 2026-08-01, awaiting Nathan's independent verification.
Nothing on the old edge may be shut down before that verification.

## Live architecture

Numbat is a BinaryLane Perth Rocky Linux 10 VM on the smallest Standard plan.
It has no route into the home network. Bilby and other targets connect outward
with named rathole services.

| Address | TCP 22 | TCP 80 | TCP 443 | TCP 2333 |
|---|---|---|---|---|
| `103.1.184.88` | Forgejo SSH | Pomerium redirect and ACME | Pomerium | Closed |
| `103.4.235.175` | Pomerium native SSH | Closed | Public TLS rathole | rathole control |

Protected browser names resolve to the application address. Pomerium
authenticates with Pocket ID, then uses a loopback-only rathole service and
client mTLS to reach Caddy's private `:4443` listener. Raw and public endpoints
use the relay address and Caddy's public-only `:4444` listener.

Cloudflare remains authoritative DNS and the CDN for public websites and their
Umami ingestion paths. Protected services and raw protocols are DNS-only.

Numbat Periphery connects outward through `core-connect.pod.haus` with Komodo
Noise authentication. Alloy sends through `logs-ingest.pod.haus`, where Caddy
requires Numbat's client certificate and ClickStack requires its ingestion key.
Neither path uses Tailscale.

Host SSH uses Pomerium on `ssh.pod.haus:22`, with routes for Bilby, Numbat, and
Voltaire. Forgejo remains ordinary `git@git.pod.haus` SSH on the other address.
The repository owns only Voltaire's gateway-side resources; its rathole
client and SSH CA trust stay machine-local.

## Identity and exceptions

Pomerium's default policy allows the two family Pocket ID identities. Syncthing
and the development service are Nathan-only.

| Surface | Public exception | Application boundary |
|---|---|---|
| MinIO S3 and Pouch | Raw TLS through Caddy | SigV4 |
| Forgejo SSH | Raw TCP | SSH key |
| Forgejo LFS | Exact public Pomerium regex | Forgejo LFS token |
| Paperless API | `paperless-api.pod.haus/api/*` plus scoped gateway token | Paperless API token |
| HyperDX MCP | `watch.pod.haus/api/mcp` plus scoped gateway token | HyperDX API key |
| Komodo webhook | `komodo.pod.haus/listener/github/*` | GitHub HMAC |
| Pocket ID and UniFi | Public Caddy hosts | Native login |
| Periphery and log ingestion | Public Caddy hosts | Noise or mTLS plus ingestion key |

Forgejo, Komodo, MinIO Console, and Gatus keep native Pocket ID where supported,
so users may see a second OIDC login. Fenwick verifies Pomerium's signed
identity assertion, including its signature, issuer, audience, expiry, and
email. Other protected services retain their existing application login.

## Retained rollback

Kookaburra, Cloudflare Tunnel and Access, the old rathole paths, Tailscale, and
Numbat's temporary key-only port 2222 remain live. Terraform still owns all of
them. Migrated DNS points at Numbat, so rollback is a DNS change and does not
touch application state. Fenwick also needs its Pomerium identity commit
reverted while Cloudflare Access is primary.

The Komodo handoff and a full Numbat reboot passed. Six minutes after boot the
1 GB node had 403 MiB available, no swap or OOM activity, and no container
restarts, so the smallest plan remains the right size.

## Before retirement

- Nathan verifies Pocket ID login, logout, Family and Nathan-only policies from
  an off-LAN device.
- Verify Forgejo HTTPS, SSH, clone, push, and LFS; Paperless iOS; S3 path-style
  and virtual-host access; WebSockets; and native SSH to Bilby, Numbat, and
  Voltaire.
- Finish the machine-local Voltaire rathole client and Pomerium CA trust.
- Run a no-op Terraform plan from outside the LAN through
  `storage.pod.haus`.

After those checks and Nathan's explicit approval, remove the old DNS rollback
values, Kookaburra, migrated Tunnel and Access resources, the old Tailscale
management path, Cloudflare browser SSH, obsolete secrets, and port 2222.
Update the Pinelake plan to use this proven outbound gateway contract.

Bilby's flat `dockernet` trust domain remains separate
[technical debt](../tech-debt.md).
