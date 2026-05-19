# nathanbaxter.com — Publii site (clean, server-side plan)

## Status

**BUILT & VERIFIED (2026-05-19) — one open issue (external-VPN
publish, see below).** This section is the as-built record; the plan
body underneath is retained as rationale.

Done & verified:
- `minio/terraform/` root applied from-anywhere via
  `https://storage.pod.haus` — bucket `nathanbaxter-com` (versioning,
  anon `GetObject`-only policy), least-priv Publii IAM
  user/policy/service-account. Commits: `f183dfa` (root + the
  `minio/tf`→`minio/terraform` rename sweep).
- chezmoi `f3f5775`: `TF_VAR_minio_user/password`
  (`op://Homelab/MinIO Root`) added to the rendered
  `~/.config/fish/conf.d/podhaus-tf.fish`; `chezmoi apply` done.
- Caddy serves `nathanbaxter.com`/`www` from the bucket (commit
  `5b2529a`): mutually-exclusive `handle` blocks map clean URLs →
  `<dir>/index.html` keys, missing → bucket `404.html`, `www`→apex
  301. HTTP-origin behind the tunnel (Cloudflare owns TLS).
- Cloudflare web DNS + tunnel ingress applied (commit `3657a5f`,
  gated/reviewed: `Plan: 2 add, 1 change, 0 destroy`, **mail records
  untouched** — Fastmail MX/DKIM/SRV + Postmark verified intact):
  proxied apex + `www` CNAME → pod_haus tunnel; two bespoke public
  (no-Access) ingress entries → `http://caddy:80`.
- 1Password Homelab item **`Publii nathanbaxter.com S3`** created
  from the TF outputs (endpoint, bucket, region, addressing note,
  site URL, access key, secret key) — the single credential to read.
- Gatus monitors `https://nathanbaxter.com/` (commit `e1256d0`).
- LAN split-horizon `nathanbaxter-com.storage.pod.haus → bilby`
  (commit `a62444e`) so on-LAN Publii hits Caddy directly (no
  WAN/hairpin).
- Verified end-to-end on the real public hostname: `/`, `/about[/]`,
  asset, 404-fallback, `www`→apex 301, valid Cloudflare TLS;
  scoped-key Publii-exact (`@aws-sdk/client-s3` v3, vhost)
  PUT/GET/DELETE round-trip OK; scoped key **denied** on
  `terraform-state` (least-priv holds); mail DNS unchanged. Bucket
  holds a tidy holding `index.html` + `404.html` (Publii overwrites
  on first publish).

Known minor (not blocking): missing URLs serve the Publii 404 page
with HTTP **200** (classic S3-static behaviour); refine to a real 404
status later if SEO matters.

**Remaining user step (laptop, ~5 min):** install Publii, clean site,
site URL `https://nathanbaxter.com`, Server→S3 from the 1Password
item (**virtual-host; do NOT force path style**), Publish.

Nothing is pushed — all local commits on `main`; deployed via
Komodo/Terraform directly. A `git push` fires the
`podhaus-push-deploy` webhook (user's call when to sync the remote).

## OPEN ISSUE — external publish over a VPN fails (MTU / TLS handshake)

**Severity: blocks the actual use case.** Sky must be able to publish
from anywhere, *including a coffee-shop VPN*. Confirmed 2026-05-19:
Publii from a laptop **with a VPN active** fails with *"Client network
socket disconnected before secure TLS connection was established"*;
**VPN off, it works**. The LAN split-horizon fixes only the *home*
case — a remote client on a VPN still hits the WAN port-forward →
Caddy and fails.

Diagnosis (evidence-backed, 2026-05-19 — packet capture from bilby
over the WAN hairpin):
- **The cert is already ECDSA P-256** (LE `E8` ECDSA chain), *not*
  RSA. An earlier draft of this section claimed "LE RSA leaf +
  intermediate ≈ 3–4 KB" and proposed switching to ECDSA — both were
  **wrong**: ECDSA is already in place and is not an available lever.
- The handshake is large because client and server negotiate the
  **`X25519MLKEM768` post-quantum hybrid KEM**. Measured payload:
  **ClientHello ≈ 1580 B, server flight ≈ 3631 B**. Controlled
  measurement with the PQ hybrid disabled client-side (`curl --curves
  X25519`) drops these to **517 B / 2543 B** — i.e. ML-KEM-768 adds
  **~1.1 KB in each direction**. The cert chain is a minor contributor.
- Mechanism: a VPN/Wi-Fi path whose effective MTU is reduced by tunnel
  encapsulation, **with ICMP frag-needed blackholed** (near-universal
  on UDP VPNs / public Wi-Fi), silently drops the full-size DF
  segments carrying this oversized handshake; they retransmit
  identically → socket dies before TLS completes (the exact error).
  Small packets (SYN, Publii "test connection") survive, so it reports
  "connected" then fails on the flight. VPN-off works (path MTU ≥
  negotiated MSS). The WAN path itself is proven healthy for
  normal-MTU clients (small request → `HTTP/2 200`).
- **Not yet reproduced under a real constrained path** — the exact
  trigger MTU and confirmation the fix fully closes it are open.
  bilby's hairpin is 1500-MTU so it cannot reproduce the failure; a
  real VPN client (Sky-side or a throwaway VPN container) is the
  decisive repro and the fix-verification harness.

**Candidate fixes (server-side — we can't change Sky's VPN), to
execute next:**
1. **TCP MSS clamping at the UniFi gateway (primary, most general).**
   Clamp WAN MSS to PMTU (or a fixed low value, e.g. ~1360). Sizes
   *both directions'* segments to cross a reduced-MTU VPN even with
   PMTUD broken — the only lever that is both direction- and
   client-agnostic, so it covers the 1.6 KB ClientHello *and* the
   3.6 KB server flight for any client/VPN. UniFi has a "Clamp TCP
   MSS" setting; read the UniFi doc before changing.
2. **Disable the PQ hybrid in Caddy's TLS (complementary,
   server-side, no client change).** Removing `X25519MLKEM768` from
   Caddy's offered key-exchange groups shrinks the dominant server
   flight ~3.6 → ~2.5 KB with zero Sky-side change (honors the
   zero-client-software constraint). *Replaces the earlier, wrong
   "ECDSA cert" lever.* Not sufficient alone — the client's ~1.6 KB
   ClientHello is client-controlled and unaffected — so pair with #1.
3. Fallbacks if 1+2 insufficient: lower Caddy/host MTU; or a
   host-level `nft`/`iptables` `TCPMSS --clamp-mss-to-pmtu` on the
   port-forward path.

Recommended: **gateway WAN MSS clamp (primary) + disable PQ hybrid in
Caddy (complementary)**, then verify with a real VPN client. Until
fixed, the
documented workaround is "publish with VPN off" (acceptable short
term; NOT acceptable as the final state — Sky needs VPN-on to work).
Honors `[[project_sky_publii_zero_client]]` (no client-side change).

## Context & goal

The platform is built and proven (`minio-public-caddy.md`):
`storage.pod.haus` is a public S3 endpoint and Publii's exact SDK
round-trips through it. This plan does **everything server-side** so
the **only remaining action is on your laptop**: read one 1Password
item, paste it into a clean Publii S3 config, publish — site live at
`https://nathanbaxter.com`. nathanbaxter.com is the clean test case:
**no migration, no WordPress redirects** — fresh Publii output.

## End-state architecture

```
Publii (your laptop) ──S3 PUT, vhost──▶ https://storage.pod.haus
                                         (= nathanbaxter-com.storage.pod.haus)
                                         → UniFi PF → Caddy:443 → MinIO bucket

Public visitor ──https://nathanbaxter.com──▶ Cloudflare (proxied; TLS,
   cache, DDoS — fine, it's static GETs, no SigV4) → pod_haus tunnel
   → Caddy:80 (index-doc rewrites) → MinIO bucket nathanbaxter-com
   (anonymous GetObject)
```

Two distinct paths: the **upload API** (Publii → S3, must bypass the
Cloudflare proxy — that's the existing storage.pod.haus) and the
**public website** (visitors → static HTML, *uses* the Cloudflare
proxy normally).

## Workstreams (all server-side)

### 1. MinIO provisioning — new Terraform root `minio/terraform/`

Use the **`aminueza/minio`** provider (config-as-code; **read its
resource docs before writing HCL** — new provider, hard rule).

- `backend.tf`: S3 backend, `terraform-state` bucket, key
  `minio.tfstate`, endpoint `https://storage.pod.haus` (object ops —
  from-anywhere fine), same `skip_*`/`use_lockfile`/`encrypt=false`
  shape as `cloudflare/backend.tf`.
- `providers.tf`: `aminueza/minio` → **`storage.pod.haus`** (TLS,
  `minio_ssl = true`), user/pass from `var.minio_user`/
  `var.minio_password` = **MinIO root** (resolved from 1Password via
  the chezmoi Terraform env, same as every other root's creds). This
  root is **from-anywhere like all the others** — no bilby pin, no
  exception. Caddy serves the full MinIO API (S3 + admin); the access
  control is MinIO SigV4 (root creds gate the admin calls; there is
  **no** `/minio/admin/` edge block — it was retracted precisely
  because it would break this). Per the decision: provider uses root
  (Terraform conceptually needs full reach; a scoped admin cred buys
  pain, not a real boundary, since IAM-management is escalation-capable).
- `main.tf`:
  - `minio_s3_bucket "nathanbaxter_com"` → bucket `nathanbaxter-com`.
  - `minio_s3_bucket_versioning` → enabled (rollback for bad
    publishes).
  - `minio_s3_bucket_policy` → anonymous **`s3:GetObject` on
    `nathanbaxter-com/*` only** (Caddy serves objects anonymously);
    **no anon `ListBucket`** (no public enumeration of unlinked
    files).
  - `minio_iam_policy "publii_nathanbaxter_com"` → least-priv:
    `GetObject/PutObject/DeleteObject` on `nathanbaxter-com/*` +
    `ListBucket` on the bucket (Publii needs list for its
    `files.publii.json` deploy delta). Nothing else; no admin.
  - `minio_iam_user` + attachment + `minio_iam_service_account`
    (`target_user` = that user) → `output "publii_access_key"` /
    `"publii_secret_key"` (sensitive).
- `minio/terraform/.gitignore`: ignore `.terraform.lock.hcl` + `.terraform/`
  (same self-lock policy as cloudflare/).
- **Accepted caveat:** the SA secret lands in `minio.tfstate`
  (unencrypted terraform-state bucket — same risk class as the CF
  token in `cloudflare.tfstate`; bounded by the least-priv scope —
  worst case = the public website bucket, recoverable from
  versioning + Backrest + a re-publish).
- Run from bilby: `cd minio/terraform && terraform init && terraform apply`.

### 2. chezmoi — MinIO-root creds in the env shim

Add to `private_podhaus-tf.fish.tmpl` (same `onepasswordRead "…"
"my"` pattern as the existing lines):

```
set -gx TF_VAR_minio_user     {{ onepasswordRead "op://Homelab/MinIO Root/username" "my" }}
set -gx TF_VAR_minio_password {{ onepasswordRead "op://Homelab/MinIO Root/credential" "my" }}
```

Commit the chezmoi repo; `chezmoi apply`. (Consumed by the `minio/terraform/`
root, which runs from anywhere like the `cloudflare/` root; harmless
elsewhere.)

### 3. Caddy — serve nathanbaxter.com from the bucket

**The public site is `https://nathanbaxter.com`, Cloudflare-proxied**
(DNS `proxied = true`; Cloudflare Universal SSL terminates TLS at the
edge). The `http://` below is **only the internal cloudflared→Caddy
hop over dockernet** — identical to every other pod.haus tunnel
service (`http://gatus:8080`, `http://docs-server:80`, …): the tunnel
transport is already encrypted and TLS is terminated at the edge, so
re-encrypting inside dockernet is pointless and not the fleet pattern.
The `http://` site address is also the deliberate signal that **Caddy
must not ACME this name** — it can't get a cert behind the tunnel and
Cloudflare owns the public cert. (`https://caddy` would be wrong.)

Add this **HTTP-origin** site to `caddy/Caddyfile`:

```
http://nathanbaxter.com, http://www.nathanbaxter.com {
	@www host www.nathanbaxter.com
	redir @www https://nathanbaxter.com{uri} permanent

	# pretty URLs → bucket object paths (Publii emits index.html /
	# 404.html / feed.xml / assets/…). Clean site, no WP redirects.
	@dir path_regexp dir ^(/.*?)/?$
	rewrite / /nathanbaxter-com/index.html
	rewrite @dir /nathanbaxter-com{re.dir.1}/index.html
	@file path *.*
	rewrite @file /nathanbaxter-com{path}
	handle_errors {
		rewrite * /nathanbaxter-com/404.html
		reverse_proxy minio:9000
	}
	reverse_proxy minio:9000
}
```

Exact rewrite rules to be validated against real Publii output during
verification (principle: prefix bucket, dir→`/index.html`, real files
pass through, 404→`404.html`). cloudflared reaches it as
`http://caddy:80` over dockernet — Caddy listens `:80` from this site;
**no compose host-port change** (inter-container, dockernet). Redeploy
`caddy`.

### 4. Cloudflare TF — website DNS + tunnel ingress (public, no Access)

**Strictly additive to the nathanbaxter.com zone — mail untouched.**

- `cloudflare/dns_nathanbaxter_com.tf` (append): proxied apex
  `nathanbaxter.com` CNAME → `local.tunnels.pod_haus` (CNAME
  flattening) + `www` CNAME → same, `proxied = true`. Leave every
  existing MX / `*._domainkey` / `mail.` / `pm-bounces` / SRV / TXT
  record exactly as-is.
- `cloudflare/tunnel.tf`: add bespoke entries to the `config.ingress`
  `concat(...)` **before** the `http_status:404` catch-all (these are
  NOT pod.haus / NOT the `pod_haus_service` module — no Access app;
  it's a public site):
  ```
  { hostname = "nathanbaxter.com",     service = "http://caddy:80", path = null, origin_request = null },
  { hostname = "www.nathanbaxter.com", service = "http://caddy:80", path = null, origin_request = null },
  ```
- `cd cloudflare && terraform plan` — **review: only the two web
  records + two ingress entries added; zero changes to mail records**
  — then `terraform apply` (gated; this is the one step worth a human
  glance because it's the live-email domain).

### 5. Populate the 1Password item (server-side, from TF outputs)

After the `minio/terraform/` apply, create the single item you'll read:

```
op item create --vault Homelab --title 'Publii nathanbaxter.com S3' --category 'API Credential' \
  'endpoint[text]=https://storage.pod.haus' \
  'bucket[text]=nathanbaxter-com' \
  'region[text]=us-east-1' \
  'addressing[text]=virtual-host (do NOT force path style)' \
  'site url[text]=https://nathanbaxter.com' \
  "access key id[text]=$(terraform -chdir=minio/terraform output -raw publii_access_key)" \
  "secret access key[password]=$(terraform -chdir=minio/terraform output -raw publii_secret_key)"
```

(One server-side command. This is the credential you read on the
laptop.)

### 6. Verification (server-side, no laptop)

- Seed placeholders via `mcli` (root): put `index.html` + `404.html`
  into `nathanbaxter-com`.
- `curl https://nathanbaxter.com/` → 200 placeholder (proves CF →
  tunnel → Caddy → MinIO + index rewrite); `curl
  https://nathanbaxter.com/nope` → the 404 page; `curl` a bare
  bucket-ish listing → denied (no anon ListBucket).
- Authenticated **vhost** PUT/GET with the **scoped Publii key**
  (Node `@aws-sdk/client-s3` v3, like the platform proof) to
  `nathanbaxter-com.storage.pod.haus` → round-trips; same key on
  `terraform-state` → AccessDenied.
- `dig MX nathanbaxter.com` + DKIM/SRV unchanged (mail intact).
- Gatus: add `https://nathanbaxter.com/` check (status 200).
- Remove placeholders (Publii overwrites on first publish anyway).

## Out of scope — your laptop (~5 min, the only thing left)

Install Publii (+ `libsecret`); create a **clean** site (no import);
set Publii's site domain to `https://nathanbaxter.com`; Server
settings → **S3**, filling endpoint / bucket / region / keys from the
one 1Password item, **virtual-host addressing (do not enable force
path style)**; Test connection; Publish. Live.

## Risks / decisions

- **Live-email domain.** The DNS apply must be additive only (apex +
  www web records). Plan output reviewed for zero changes to MX/DKIM/
  SRV/Fastmail/Postmark before apply. This is why this plan is
  review-gated rather than auto-run.
- **MinIO admin API is internet-reachable, SigV4-gated** (not
  edge-blocked — that would break the from-anywhere `minio/terraform/` root;
  no TF root is exempt). The boundary is MinIO's root SigV4; creds
  live only in 1Password + the chezmoi Terraform env. Eyes-open,
  agreed posture (see minio-public-caddy.md).
- **SA secret in `minio.tfstate`** (unencrypted) — accepted, bounded
  by the Publii key's least-priv data scope; same model as
  `cloudflare.tfstate`.
- **Caddy must not ACME nathanbaxter.com** — the `http://` site
  address ensures CF edge owns TLS; verify Caddy logs show no ACME
  order for it.
- Provider-doc hard rule: read `aminueza/minio` + `cloudflare_dns_record`
  docs before writing HCL.
- The website is intentionally Cloudflare-proxied (cache/DDoS for
  public static content) — orthogonal to the S3 API path, which
  cannot be proxied.
