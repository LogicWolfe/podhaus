# Replacing rathole with wstunnel

**Status:** Intended, not started. No code written. This plan exists to
record the evaluation so the decision does not have to be re-derived, and
to name the conditions that should trigger the work.

Every outbound tunnel in the fleet is rathole today: five clients
(`relay/{bilby,kangaroo,fractal,voltaire,pinelake}`) dialing one server
(`relay/numbat`). The transport works and nothing is broken. The problem
is that upstream has stopped moving, and the way we consume it means we
are pinned to a 2023 binary without having chosen to be.

## Why replace it

rathole is not abandoned — the repository moved from `rapiz1/rathole` to
`rathole-org/rathole` and still takes the occasional commit — but it has
been drifting for two years:

- Last **stable** release is v0.5.0, 2023-10-01.
- Four commits landed on the default branch in the following 24 months,
  all packaging or CI.
- Dependencies have not been touched since February 2024.
- 95 open issues and pull requests; the oldest open PR dates from
  June 2024.

Everything since v0.5.0 ships under a rolling `dev-latest` prerelease tag.

**Consequence we did not intend:** `relay/Dockerfile` fetches
`https://github.com/rathole-org/rathole/releases/latest/download/${asset}`.
GitHub's `/latest/` redirect excludes prereleases, so it resolves to
v0.5.0 on every rebuild. All five hosts run the October 2023 binary, on a
February 2024 dependency tree, while the Dockerfile reads as though it
tracks upstream. This contradicts the "use the current stable release by
default" rule in `AGENTS.md`, silently.

We are deliberately **not** patching the Dockerfile to pin a newer
`dev-latest` asset. Cutting over to wstunnel is the upgrade path; a pin
would be work thrown away and would put untested prerelease builds under
the whole fleet's ingress in the meantime.

## What a replacement has to do

These are structural requirements, derived from
`relay/numbat/server.toml.tmpl` as it stands. A candidate that misses any
of them is not a candidate.

- **Outbound-only from origin hosts.** voltaire and pinelake have no
  inbound path at all; fractal is a WSL guest behind NAT.
- **Per-service bind addresses.** Numbat has two public IPs precisely
  because two different services need `:443` and `:22`:
  `public_tls` binds `relay.numbat.pod.haus:443` while `forgejo_ssh`
  binds `app.numbat.pod.haus:22`, and nine further services bind
  `127.0.0.1` ports (`8443`, `2201`–`2205`, `8444`–`8446`) so only
  Pomerium and the SSH dispatcher can reach them. A tunnel with one
  global bind address cannot express this without pushing the
  distinction into nftables.
- **Raw TCP passthrough.** Numbat must never hold plaintext. Public TLS
  terminates at bilby's Caddy `:4444`; protected routes carry Pomerium's
  client certificate to a `:4443` mTLS origin on bilby, fractal,
  voltaire, or pinelake.
- **Server-side declaration of what may be exposed.** A compromised
  client must not be able to publish a new listener on numbat.
- **Small footprint.** Numbat is 1 vCPU / 1536 MB and has OOMed twice.
- **arm64 and x86_64**, since bilby and pinelake are Apple Silicon.

## Candidates

| | rathole (current) | **wstunnel** | chisel | frp |
|---|---|---|---|---|
| Language | Rust | Rust | Go | Go |
| Last stable | v0.5.0, 2023-10-01 | v10.7.0, 2026-08-28 | v1.12.0, 2026-08-29 | v0.71.0, 2026-08-14 |
| Open issues | 95 | 32 | 244 | 50 |
| Per-service bind address | yes | yes | yes | **no — global** |
| Server-side authorization | per-service tokens | default-deny rules, hot reload | per-user regex, hot reload | port ranges only |
| Auth | Noise static keys | mTLS or bearer token | fingerprint + credentials | token or mTLS |
| Multiplexing | per-service connections | per-service connections | **all over one SSH connection** | per-proxy |

**frp is disqualified.** `ProxyBindAddr` in `pkg/config/v1/server.go` is
server-global and TCP proxies carry only `RemotePort`, so it cannot put
`public_tls` on the relay IP and `forgejo_ssh` on the application IP. It
would force `0.0.0.0` binding plus an nftables dispatch layer — a
regression on a host whose known failure mode is a ruleset that fails to
load.

**chisel clears the structural bar but ranks below wstunnel.** Its
`R:<local-interface>:<local-port>:<remote-host>:<remote-port>` form
supports bind addresses and its authfile maps each user to a list of
permitted reverse forwards with hot reload. Against it: 244 open issues,
and every tunnel rides a single SSH-over-websocket connection, so all
public HTTPS shares a congestion window with Forgejo SSH and five host
SSH sessions. rathole gives each service its own connection today and
that property is worth keeping.

**gost v3 was deprioritised rather than finished.** It is actively
maintained but is a general-purpose proxy toolkit; the surface area is
the wrong direction for numbat.

**wstunnel is the pick.** Rust, actively released, 32 open issues. Its
`-R {tcp,udp}://[BIND:]PORT:HOST:PORT` form carries a bind address per
tunnel. Its `--restrict-config` YAML is **default-deny** — the server
declares `!ReverseTunnel` allow rules matched on path prefix or
authorization header, and reloads them without a restart, which is a
stronger version of what per-service tokens give us now. It supports
mTLS with certificate auto-reload, and it can carry UDP reverse tunnels,
which rathole cannot.

## What wstunnel does not solve

**Client IP addresses.** wstunnel supports PROXY protocol only on
*forward* tunnels. In `wstunnel/src/tunnel/mod.rs` the enum is:

```rust
pub enum LocalProtocol {
    Tcp { proxy_protocol: bool },
    Stdio { proxy_protocol: bool },
    HttpProxy { ..., proxy_protocol: bool },
    ReverseTcp,                    // no such field
    ReverseUdp { timeout: ... },
```

`ReverseTcp` is the `-R` path and the only direction podhaus uses. Of the
four candidates only frp emits PROXY protocol on a reverse tunnel, and
frp is disqualified on bind addresses.

So the fleet's blindness to public client IPs — Caddy sees the tunnel's
local socket for every request arriving on `:4444` — is **independent of
this migration** and must be solved separately, by terminating in front
of the tunnel on numbat with something that injects a PROXY header, and
adding a matching `trusted_proxies` to Caddy. `caddy/` contains no
`trusted_proxies` or `proxy_protocol` directive today.

## Shape of the migration, when it happens

- Nine services move from `[server.services.<name>]` TOML blocks to
  wstunnel `-R` arguments plus a `restrictions.yaml` on numbat.
- Auth changes from nine Noise-transport tokens to mTLS client
  certificates, which the fleet's existing edge PKI in `terraform/` can
  issue. The per-service token variables in 1Password retire with it.
- `relay/Dockerfile` stops scraping a GitHub release asset; wstunnel
  publishes multi-arch images.
- `relay/entrypoint.sh` and `relay/tests/test_entrypoint_env.py` are
  built around `envsubst` rendering tokens into a TOML template; both are
  rewritten or removed.

**Cut over one client at a time, bilby first.** Bilby is the only host
with an independent inbound path (LAN SSH), so a failed cutover there is
recoverable without break-glass. voltaire and pinelake go last: rathole
is their only inbound path, and the fallback is Tailscale recovery.

## When to do it

Not on its own merits. wstunnel is a moderate improvement over rathole,
not a large one, and the migration touches six stacks on five hosts with
two of them reachable by nothing else. Take it when something else forces
the relay layer open:

- a CVE lands in rathole's 2024 dependency tree;
- a service needs a UDP tunnel;
- the public client-IP work opens numbat's ingress path anyway;
- rathole breaks on a future host architecture or base image.
