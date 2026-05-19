# MinIO public access via Caddy + UniFi (not Cloudflare)

## Status

**COMPLETE (2026-05-19).** Built and verified end-to-end. This is the
authoritative as-built record; it supersedes the Cloudflare-proxied
`storage.pod.haus` approach (`11a84cd`, torn down) and the planning in
`tf-runner-decommission.md` / `skycroeser-net-migration.md` (those
predate this architecture — read this doc for what actually exists).

**Verified:**
- `terraform init -reconfigure` + `plan` + `apply` against
  `https://storage.pod.haus` — **zero drift**, no `SignatureDoesNotMatch`
  (Caddy preserves the SigV4-signed `Accept-Encoding`/`Host`; the
  original Cloudflare-proxy blocker is gone).
- **Publii proven**: authenticated virtual-host PUT/GET via Publii's
  exact client (`@aws-sdk/client-s3` v3, no `forcePathStyle`,
  `endpoint=https://storage.pod.haus`) round-tripped through the real
  public path (`<bucket>.storage.pod.haus` → port-forward → Caddy LE
  wildcard → MinIO `MINIO_DOMAIN`).
- The full MinIO API (S3 + admin) is served; access control is
  MinIO's own SigV4 — unauthenticated `/minio/admin/` → MinIO
  `AccessDenied`. **Deliberately NOT edge-blocked**: an admin 403
  would break the from-anywhere `minio/terraform/` root, and no TF root is
  exempt from the from-anywhere rule. `terraform-state` not
  anonymously listable; valid public LE cert (apex + wildcard);
  cloudflare-ddns holding the A record; Gatus check added.
- Stock `terraform` from any machine (creds from the chezmoi-rendered
  `~/.config/fish/conf.d/podhaus-tf.fish`); `tf` runner deleted.

**KNOWN OPEN ISSUE (2026-05-19): external clients on a low-MTU VPN
fail the TLS handshake** to `storage.pod.haus` (large LE-RSA cert
flight + PMTUD blackhole → "socket disconnected before secure TLS
connection was established"). Affects *any* external TLS client over
a constrained VPN — Publii from a coffee shop *and* `terraform` run
remotely over a VPN. Server is healthy; fix is server-side (UniFi WAN
**MSS clamp** + **ECDSA cert** in Caddy). Full diagnosis + candidate
fixes + status: see the "OPEN ISSUE" section of
[nathanbaxter-com-publii.md](nathanbaxter-com-publii.md). Workaround
until fixed: publish/terraform with VPN off.

Original plan retained below as the rationale of record.

## Why this shape — and explicitly NOT Cloudflare or Tailscale Funnel

This rationale is the durable record (the "why" for the MinIO docs):

- **Cloudflare's HTTP proxy is unusable for the S3 API.** Its edge
  rewrites the `Accept-Encoding` request header (it manages
  compression) — and Terraform's `aws-sdk-go-v2` **signs**
  `Accept-Encoding`, so MinIO recomputes a different SigV4 signature →
  `SignatureDoesNotMatch`. Empirically confirmed (TF_LOG trace; `mcli`
  works through the same proxy precisely because it doesn't sign that
  header). Cloudflare also refuses to let any rule preserve
  `Accept-Encoding` (API error 20087 — it's a reserved managed
  header). Unfixable at the Cloudflare layer.
- **Cloudflare free Universal SSL is single-level** (`*.pod.haus`,
  not `*.x.pod.haus`). Publii's `@aws-sdk/client-s3` v3 forces
  **virtual-hosted** addressing (`<bucket>.host`) with no
  `forcePathStyle` option, so it needs a wildcard cert one level
  deeper than Cloudflare's free cert provides. Paid ACM only.
- **Tailscale Funnel can't host a custom domain.** Its ingress is
  `*.ts.net`-only; even raw `--tcp` still routes by the TLS SNI at a
  shared ingress (docs: "Funnel only works over TLS" + "only ts.net
  names"; issue #14625's "magic ports" symptom confirms the ingress
  is SNI-aware even when not terminating). CNAME doesn't help — the
  client emits the custom-domain SNI, which is unroutable. Building
  against an explicitly unsupported path is precarious anyway.
- **No free *managed* relay does persistent + custom-domain +
  reliable** — that trio is the universal paywall line (Pinggy,
  zrok, ngrok). A free-forever VM (Oracle Always Free) would work but
  adds a box; rejected in favour of the home connection since the IP
  is **contractually static** (business line).

**Conclusion:** own our own TLS with a free Let's Encrypt **wildcard**
(`*.storage.pod.haus`, DNS-01 via the existing Cloudflare token) on a
Caddy reverse proxy on bilby, reached by a **UniFi port-forward** —
Cloudflare stays authoritative DNS only (grey-cloud), never in the S3
data path. One uniform endpoint serves every S3 client (Publii
virtual-host *and* Terraform path-style), no header mangling, zero
client software for Sky.

## Target architecture

```
Sky's Publii / Terraform / any S3 client  (public internet, nothing installed)
        │  https://storage.pod.haus  (path-style: Terraform)
        │  https://skycroeser-net.storage.pod.haus  (vhost: Publii)
        ▼
Cloudflare DNS (grey-cloud / DNS-only, NOT proxied)
   storage.pod.haus      A      <WAN IP>   (DDNS-maintained)
   *.storage.pod.haus    CNAME  storage.pod.haus
        ▼
Home WAN  ──UniFi port-forward 443→bilby:443 (TF-managed)──▶
        ▼
bilby: Caddy  (LE SAN cert: storage.pod.haus + *.storage.pod.haus,
               DNS-01 via Cloudflare token; full S3+admin API,
               MinIO SigV4 is the access control)
        │  reverse_proxy (Host + Accept-Encoding untouched)
        ▼
MinIO :9000  (MINIO_DOMAIN=storage.pod.haus → vhost + path-style both)
```

LAN/bilby clients reach Caddy directly via UniFi split-horizon DNS
(`storage.pod.haus` → bilby LAN IP), avoiding NAT hairpin.

## Work items

### 1. MinIO
- `minio/stack.toml`: add `MINIO_DOMAIN=storage.pod.haus` to the env
  block. (Internal/loopback path-style users — Backrest, the TF
  backend over loopback — keep working: `MINIO_DOMAIN` only changes
  vhost parsing for Hosts under that domain; `127.0.0.1`/`minio:9000`
  are unaffected.) Redeploy MinIO.

### 2. Caddy stack (`caddy/`) — new
- `caddy/compose.yaml`: `caddy:2` (with the Cloudflare DNS plugin —
  custom build or `caddy-dns/cloudflare` image), `dockernet`,
  publishes host `:443` (and `:80` not needed — DNS-01), `label:disable`
  (Fedora Asahi), autoheal, healthcheck. Bind-mount `caddy/Caddyfile`
  (directory bind) + named volumes for cert/data.
- `caddy/Caddyfile`:
  - site `storage.pod.haus, *.storage.pod.haus`
  - `tls` with `dns cloudflare {env.CLOUDFLARE_API_TOKEN}` (DNS-01;
    issues the SAN wildcard automatically, auto-renews)
  - `reverse_proxy minio:9000` (Caddy forwards Host + Accept-Encoding
    unchanged — the whole point). The **full** MinIO API (S3 + admin)
    is served; access control is MinIO SigV4. **No `/minio/admin/`
    edge 403** — it would break the from-anywhere `minio/terraform/` root
    (no TF root is exempt; see AGENTS.md). Unauthenticated admin calls
    get MinIO `AccessDenied`; root creds live only in 1Password + the
    chezmoi Terraform env.
- `caddy/stack.toml`: `server=podhaus`, `files_on_host=true`,
  `run_directory=/etc/komodo/repo/caddy`. `CLOUDFLARE_API_TOKEN` via
  `[[OP__KOMODO__CLOUDFLARE_API_TOKEN__*]]` (1Password → komodo-op;
  add the item/field if not already synced).

### 3. Cloudflare Terraform — tear down proxied path, add grey-cloud DNS
- Remove `module "storage"` (services_pod_haus.tf), its
  `module.storage.ingress_rule` (tunnel.tf), `cloudflare_ruleset`
  `storage_firewall` + `storage_cache` (waf.tf), and
  `cloudflare_zero_trust_access_policy.public_bypass` (access.tf) if
  orphaned after.
- New `dns_storage.tf`:
  - `cloudflare_dns_record` `storage.pod.haus` — `A`, `proxied=false`
    (grey-cloud), content = current WAN IP, **`lifecycle {
    ignore_changes = [content] }`** (DDNS owns the value; TF owns
    existence). Comment the boundary explicitly.
  - `cloudflare_dns_record` `*.storage.pod.haus` — `CNAME` →
    `storage.pod.haus`, `proxied=false`.
- UniFi split-horizon: add `unifi_dns_record` `storage.pod.haus` →
  bilby LAN IP (pattern in `dns_unifi_split_horizon.tf`).

### 4. UniFi port-forward (Terraform)
- `cloudflare/` root also holds the unifi provider. Add a
  `unifi_port_forward` (WAN tcp 443 → bilby LAN IP:443). Read the
  `ubiquiti-community/unifi` provider docs for the resource schema
  first (hard rule).

### 5. Cloudflare-DDNS stack (`cloudflare-ddns/`) — new
- `favonia/cloudflare-ddns` (confirm current best minimal image at
  build), updates **only** the `storage.pod.haus` A record. CF token
  from 1Password via komodo-op. compose + stack.toml, standard fleet
  pattern. This survives a house move (fleet-side, not gateway).

### 6. Backend + providers (finish the runner decommission)
- `cloudflare/backend.tf`: revert temp loopback → `s3 =
  "https://storage.pod.haus"` (final).
- `cloudflare/providers.tf`: unifi `api_url=https://unifi.pod.haus`
  (already edited; verify), no `allow_insecure`.
- Delete the `tf` runner; sweep its references (AGENTS.md key-files +
  L166 + the gating note wording → `terraform`; cloudflare/README.md;
  docs/terraform.html; docs/networking.html;
  docs/disaster-recovery.html; hosts.html add a Terraform row;
  alligator-bilby-migration "superseded" note). `git rm --cached
  cloudflare/.terraform.lock.hcl` (gitignored already).

### 7. Gatus
- `gatus/conf/config.yaml`: public check on `https://storage.pod.haus`
  (cert + reachability) — converts a silent WAN-IP/path break into an
  immediate alert (the "don't rely on it silently" safeguard; IP is
  static but this removes the hidden dependency, esp. across the
  planned house move).

## Execution order (avoids breaking the working state)

Terraform runs on bilby via the **loopback backend** (works today) to
make all the changes; the backend is flipped to the public endpoint
**last**, then verified.

1. Caddy stack up; verify it obtains the LE SAN wildcard (DNS-01) and
   `curl`s through to MinIO from bilby (via split-horizon / direct).
2. `MINIO_DOMAIN` on MinIO; redeploy; confirm internal path-style
   (Backrest, loopback) still works + vhost parsing works.
3. `tf apply` (loopback backend): UniFi port-forward + split-horizon
   DNS + grey-cloud `storage.*` records + tear down proxied
   module.storage/tunnel/WAF.
4. Deploy cloudflare-ddns; confirm it holds the A record.
5. Flip `backend.tf` → `https://storage.pod.haus`; `terraform init
   -reconfigure`; **`terraform plan` zero-drift** (the acceptance
   gate — proves SigV4 works through Caddy).
6. Delete `tf` runner + doc sweep; Gatus check; commit (podhaus).
7. **Verify:** from bilby and (record for the user to test) off-LAN —
   `terraform plan` clean; an `mcli`/aws-js virtual-host PUT to
   `skycroeser-net.storage.pod.haus` succeeds; unauthenticated
   `/minio/admin/` → MinIO `AccessDenied` (cred-gated, not a Caddy
   403) while an authenticated `minio/terraform/` reaches it from anywhere;
   `terraform-state` private.

## Acceptance

`terraform apply` works against `https://storage.pod.haus` from bilby
(and is portable to any machine with chezmoi creds); a virtual-host S3
client (Publii-equivalent) can PUT/GET `*.storage.pod.haus`;
MinIO admin API reachable but SigV4-gated (unauth → `AccessDenied`);
`terraform-state` not publicly listable; Gatus green; DNS A record
DDNS-maintained with TF `ignore_changes`.

## Risks / notes

- First public WAN exposure on the fleet (accepted). The MinIO API
  (S3 + admin) is internet-reachable; the control is **MinIO SigV4**
  (root/admin creds only in 1Password + the chezmoi Terraform env).
  Deliberately **not** edge-blocked — an admin 403 would break the
  from-anywhere `minio/terraform/` root and no TF root is exempt. Keep
  Caddy/MinIO patched.
- Caddy must forward `Host` + `Accept-Encoding` unmodified (default
  `reverse_proxy` behaviour — verify; do **not** add `encode` on the
  proxied site).
- TF/DDNS dual-ownership of the A record resolved via
  `lifecycle.ignore_changes=[content]` — must be present or `tf
  apply` silently reverts the IP.
- `MINIO_DOMAIN` is global to MinIO; verify console (`minio.pod.haus`
  :9001) and internal path-style unaffected before tearing the old
  path down.
