# Replacing rathole with wstunnel

**Goal:** every outbound tunnel into Numbat runs on current wstunnel, each
client authenticated by its own certificate and limited by Numbat to the
listeners it owns, with rathole, its tokens and its Noise keypair gone.
Nathan's MacBook joins first, as the pilot, and gains `mac.docs.pod.haus`.

## Why now

rathole has not had a stable release since v0.5.0 (October 2023), and the
relay image's download of GitHub's `latest` release resolves to that build on
every host. Nathan's standing preference is current releases, with upgrade
breakage dealt with as it appears; rathole cannot honour it. The MacBook's docs
route needs a new tunnel client anyway, and starting it on wstunnel avoids
adding an eighth rathole client to migrate later.

wstunnel v11.0.0 (2026-09-19) is current. Its upstream image
`ghcr.io/erebe/wstunnel:latest` is multi-arch (amd64, arm64) on Debian with a
shell, and Homebrew carries the binary for the Mac.

Of the alternatives evaluated in September, frp cannot bind services to
different addresses and chisel multiplexes every tunnel over one connection;
those findings stand.

## What exists today

Seven rathole clients dial one server on Numbat (`relay/numbat`,
`relay.numbat.pod.haus:2333`, Noise transport, host networking). Fifteen TCP
services, each with its own token from Terraform:

| Service | Numbat listener | Client | Origin on the client |
|---|---|---|---|
| `public_tls` | `relay.numbat.pod.haus:443` | bilby | `caddy:4444` |
| `forgejo_ssh` | `app.numbat.pod.haus:22` | bilby | `forgejo:2222` |
| `protected_http` | `127.0.0.1:8443` | bilby | `caddy:4443` |
| `bilby_ssh` | `127.0.0.1:2201` | bilby | `172.18.0.1:22` |
| `voltaire_ssh` / `voltaire_http` | `127.0.0.1:2202` / `8445` | voltaire | sshd / `voltaire-caddy:4443` |
| `kangaroo_ssh` | `127.0.0.1:2203` | kangaroo | `127.0.0.1:22` (host network) |
| `fractal_ssh` / `fractal_http` | `127.0.0.1:2204` / `8444` | fractal | sshd / `fractal-caddy:4443` |
| `pinelake_ssh` / `pinelake_http` | `127.0.0.1:2205` / `8446` | pinelake | `host.docker.internal:22` / `pinelake-caddy:4443` |
| `bandicoot_ssh` / `bandicoot_http` | `127.0.0.1:2206` / `8447` | bandicoot | sshd / `bandicoot-caddy:4443` |
| `quokka_ssh` / `quokka_http` | `127.0.0.1:2207` / `8448` | quokka | sshd / `quokka-caddy:4443` |

Pomerium reaches the loopback listeners for its HTTP and SSH routes; public
HTTPS and Forgejo SSH are served straight from the public listeners. Nothing
on Numbat names a tunnel except those addresses, so a tunnel that binds the
same listener is a drop-in replacement for the consumers.

## Design

### Certificates: a relay CA in Terraform

Terraform mints a new **relay CA** beside the origin and log-ingest CAs in
`terraform/pomerium.tf`, with the same shapes:

- a server certificate for `relay.numbat.pod.haus` (`server_auth`);
- one client certificate per tunnel client, common name = the inventory host
  name (`bilby`, `bandicoot`, `fractal`, `quokka`, `voltaire`, `pinelake`,
  `kangaroo`, `nb-macbook-air`), `client_auth`.

They are published base64-encoded to a new Homelab item, `Numbat Tunnel`
(`ca_cert_b64`, `server_cert_b64`, `server_key_b64`, and
`<host>_cert_b64` / `<host>_key_b64`). Komodo stacks read them as
`OP__KOMODO__NUMBAT_TUNNEL__*` variables; the Mac reads them through
`op-vault dev` at apply, now that it is a Podhaus operator.

**Server identity is pinned to the relay CA.** wstunnel's client verifies the
server only against system roots, but its TLS library honours
`SSL_CERT_FILE`. Every client sets `SSL_CERT_FILE` to a file holding only the
relay CA and runs with `--tls-verify-certificate`, so it accepts Numbat's
certificate and nothing else. This replaces the Noise transport's pinned
public key; neither side needs a public certificate or a root-store change.

### Server: what each client may open

wstunnel's server, started with `--tls-client-ca-certs`, accepts only clients
holding a relay-CA certificate, and requires each connection's upgrade path to
equal its certificate's common name (verified in v11's
`tunnel/server/server.rs`). Its restrictions file is default-deny; one rule per
client matches `!PathPrefix "^<host>$"` and allows exactly that client's
reverse tunnels by port and bind address. A stolen client certificate can
open only its own host's listeners, and a new listener needs a commit to the
restrictions file, which the server reloads without restarting. This is
stronger than today, where any holder of the Noise public key and a token
can claim that token's service.

The server is a new Komodo stack, `tunnel/numbat` (`numbat-tunnel`), on
host networking as rathole is, listening on `relay.numbat.pod.haus:2334`. It
runs as root with every capability dropped except `NET_BIND_SERVICE`, which
the `:443` and `:22` listeners need. Port 2334 opens in the `numbat_edge`
nftables template beside 2333.

### Clients

Each Linux and pinelake client is a stack `tunnel/<host>` replacing
`relay/<host>`, on the same networks so the same origin names resolve. It runs
the upstream image with a short shell prelude that writes the certificate,
key and CA from the stack's variables to files, then execs:

```
wstunnel client --tls-verify-certificate \
  --tls-certificate <cert> --tls-private-key <key> \
  -R tcp://127.0.0.1:2207:172.18.0.1:22 -R tcp://127.0.0.1:8448:quokka-caddy:4443 \
  wss://relay.numbat.pod.haus:2334
```

The image tag is `latest`, matching the preference for current releases;
there is no image to build and no download to track. kangaroo keeps host
networking for its QTS sshd.

### The MacBook pilot

Chezmoi owns the Mac's side, with no root:

- Homebrew installs `wstunnel` and `caddy`.
- A **docs origin**: Caddy as a LaunchAgent on `127.0.0.1:4443`, presenting
  the Pomerium origin server certificate and requiring Pomerium's client
  certificate, proxying `mac.docs.pod.haus` to the local docs server
  (`127.0.0.1:8765`). Same contract as every other docs origin.
- A **tunnel client** LaunchAgent: `-R tcp://127.0.0.1:8449:127.0.0.1:4443`
  with the `nb-macbook-air` certificate.
- Certificates rendered from 1Password into `~/.config/podhaus-tunnel/`,
  mode 0600, inside FileVault.

Numbat gains the Pomerium route `mac.docs.pod.haus → https://127.0.0.1:8449`
on the docs routes' policy, and Terraform the matching Cloudflare record. When
the laptop sleeps or leaves the network the route answers with Pomerium's
upstream error; nothing monitors it.

## Order of work

Each step ends verified before the next starts. Steps 1–3 change nothing that
serves traffic today.

1. **Terraform:** the relay CA and certificates, the `Numbat Tunnel` item,
   and the `mac.docs.pod.haus` record. Verify with `terraform plan` showing
   only additions, then the Komodo variables appearing.
2. **Numbat server:** the `numbat_edge` firewall rule for 2334 (applied from
   bandicoot with `--tags edge`, check-diff first), then the `numbat-tunnel`
   stack. Verify the server is listening and rejects a client without a
   certificate.
3. **Mac pilot:** the chezmoi pieces and the Pomerium route. Verify
   `https://mac.docs.pod.haus` serves this repository's docs through Pomerium,
   and that the Mac's certificate cannot open any other listener.
4. **Clients, one at a time:** for each, remove its services from rathole's
   `server.toml.tmpl` and its relay stack, add its wstunnel rules and stack,
   deploy, and verify its SSH route through Pomerium and its HTTP routes. The
   order puts hosts with a second way in first:
   quokka, bandicoot, fractal (each reachable on the home LAN), kangaroo
   (LAN), bilby (LAN; carries public HTTPS, Forgejo SSH and every protected
   route, so it goes when the pattern is proven), then voltaire and pinelake,
   whose tunnel is their only way in. Their fallback is the Tailscale recovery
   path, checked to work before each starts.
5. **Removal:** the rathole server stack, `relay/` (Dockerfile, entrypoint,
   tests), the token resources and `Numbat Rathole` item, the `Rathole Relay`
   Noise item, port 2333 in the firewall and the bootstrap play, and every doc
   that describes rathole. The bootstrap play brings up `numbat-tunnel` in its
   place.

A client's rollback until step 5 is to restore its rathole services and stack
from git and redeploy both server and client.

## Verification

- **Certificate binding:** a client presenting host A's certificate with
  `-R` for one of host B's ports is refused (server log names the rule that
  failed to match). Tested in step 3 with the Mac's certificate.
- **Server pinning:** a client whose `SSL_CERT_FILE` holds a different CA
  fails to connect.
- **Each cutover:** `ssh <host>.pod.haus` from off-LAN through Pomerium, and
  each of the host's HTTP routes, before and after; for bilby additionally a
  public site over `public_tls`, `git@git.pod.haus` over `forgejo_ssh`, and
  Komodo reporting every outbound Periphery `Ok` (they dial in through
  `public_tls`).
- **Contract tests** in `tunnel/tests/`: every listener a client stack
  requests appears in that client's restriction rule and nowhere else, every
  listener Pomerium names has exactly one client, and no restriction rule
  allows a bind address outside `127.0.0.1` except `public_tls` and
  `forgejo_ssh`.

## Known issues this retires

`relay/tests/test_entrypoint_env.py` fails today: the entrypoint's render list
omits the bandicoot and quokka token variables, so those two clients' tokens
may be the literal `${…}` placeholder on both ends. The migration deletes the
renderer; until bandicoot and quokka cut over, the defect stands.

## Not in scope

Public client IPs: wstunnel carries no PROXY protocol on reverse tunnels, so
bilby's Caddy still sees the tunnel's address for public requests. That is a
separate change in front of the tunnel on Numbat, unchanged by this work.
