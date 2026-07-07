# skycroeser.net — WordPress.com → self-hosted Publii

> **Infra note:** the MinIO/S3 deploy target for Publii exists and is
> proven — public at `https://<bucket>.storage.pod.haus` (MinIO behind
> Caddy + LE wildcard, **not** Cloudflare-proxied; external clients
> reach Caddy via the kookaburra DigitalOcean rathole relay). See
> [/terraform.html](../terraform.html) and
> [/hosts.html#kookaburra](../hosts.html#kookaburra) for the
> as-built architecture. The earlier sections of this plan that
> assumed a Cloudflare-proxied S3 path are superseded. Remaining
> skycroeser.net-specific work (bucket + scoped key per site,
> Publii config, content migration) is unchanged.

Migrate Sky's academic website from WordPress.com to self-hosted **Publii**
(static-site output) served from the podhaus fleet behind Cloudflare
Tunnel. Authoring stays on Sky's Linux laptop; podhaus only ever serves
static HTML.

This is research + decisions + an implementation plan. **Nothing has
been built yet — planning only.** No stack, no Cloudflare resource, no
DNS change exists for this. Deliberately deferred; see *Status*.

## Status

**LIVE — cutover done (2026-07-07).** The site is built and serving at
<https://skycroeser.net> (Publii static output → `skycroeser-net` MinIO
bucket, Caddy reverse-proxies it, Cloudflare Tunnel ingress). Phase 6
domain cutover is complete: DNS + tunnel ingress (`dns_skycroeser_net.tf`,
`tunnel.tf`), the Caddy site block, and the WordPress legacy-URL redirects
are all in place and live-validated. The `sky.pod.haus` staging mirror has
been **retired** (module + tunnel ingress + Caddy host removed). Publii's
Site URL is set to the real domain, so canonical/og:url/sitemap/feed all
emit `skycroeser.net`.

**Remaining — Publii-side polish (Sky's side, non-blocking):** the
`skycroeser-validation-gaps` items still open — **G1** rebuild the nav
menu (Publii's WP importer dropped it), **G6** remove Terminal-theme
footer credit cruft, **G7** tag pages absent from sitemap. G2/G3/G4
(URL/slug/prefix preservation) are handled by the live Caddy redirect
block; G5 (soft-404) is fixed. See
[skycroeser-validation-gaps](skycroeser-validation-gaps.md).

Everything below is the original planning/decision record, retained for
context; the as-built serving architecture lives in the Caddyfile +
`terraform/` comments and [/terraform.html](../terraform.html).

---

## Context

Current site: <https://skycroeser.net/> (WordPress.com hosted).

- Personal academic site (Internet Studies, Curtin University).
- Static pages: Research ethics, Teaching, Publications, New research
  students.
- Blog with categorised posts and an extensive tag list (years of
  content).
- WordPress.com `category/uncategorized/` is used as the "Blog"
  landing.
- RSS feed at `/feed/`.
- Tag URLs at `/tag/tagname/`.
- Post URLs at `/YYYY/MM/DD/slug/`.
- Creative Commons BY-NC-SA 3.0 licensed.

**Sky's profile**: non-developer, Linux laptop, comfortable with
browser-based tools and basic file management. Writes posts herself, not
via command line. The authoring workflow must stay GUI-only on her side
— no terminal, no git, no Komodo.

## Hard requirements

- Self-hosted, open source.
- **No AI integration anywhere** — non-negotiable (this is what ruled
  out Grav 2.0, which now ships an MCP server).
- Minimalist; explicitly inspired by Low Tech Magazine
  (<https://solar.lowtechmagazine.com/>).
- Mirror existing functionality: static pages, blog, tags, search.
- Preserve existing URLs where possible — years of inbound links and
  academic citations point at the WordPress date-based paths.

---

## Decision: Publii + Terminal theme

**Why Publii**

- True static-site output (just HTML) — no PHP runtime, no database, no
  admin endpoint on the server. This is the whole reason it fits
  podhaus cleanly: it collapses to "serve a directory," exactly the
  `docs-server` shape already in the fleet.
- Desktop GPL v3 Electron app, runs locally on her Linux laptop
  (requires the `libsecret-1-0` package). `.deb`, `.rpm`, AppImage.
- WordPress-like authoring UX without WordPress's bloat; zero AI
  integration and none on the roadmap.
- Built-in WXR (WordPress export) importer.
- Content (markdown + assets) is portable — if Publii dies, the content
  survives.

**Why Terminal theme**

- Aesthetic alignment with Low Tech Magazine's "back to basics"
  philosophy; text-first, minimalist.
- Premium theme, covered by the unlimited-domain licence; modifiable
  per Publii's terms.

**Rejected**

- WriteFreely — too "stream of writing," doesn't fit her
  static-page-heavy structure.
- Ghost self-hosted — pivoting toward AI / newsletter / membership.
- Grav 2.0 — ships an MCP server for AI agents; violates "no AI."
- Hugo / Pelican / Eleventy raw — no GUI; terminal+git workflow she
  won't maintain.
- Magazine / photography Publii themes — wrong shape for text-first
  academic content.

---

## Architecture

```
Sky's Linux laptop
  Publii desktop app  ──writes/builds locally──▶  static HTML output
        │
        │  S3 API push on publish ──▶ NEW public S3-API tunnel ingress
        ▼                              (s3.pod.haus → minio:9000)
podhaus / bilby (Komodo-managed)
  MinIO (existing) ── bucket: skycroeser-net (versioned, anon-read)
        ▲
        │  reverse_proxy minio:9000  (dockernet)
  skycroeser stack: Caddy + repo Caddyfile (redirects + path rewrites)
        │            NO volume, NO SFTP — pure config-as-code
        ▼
  Cloudflare Tunnel ──public (bypass-everyone Access policy)──▶
        ▲                  sky.pod.haus   (initial build)
        │                  skycroeser.net (after Phase 6 cutover)
  umami stack (separate):                                      site visitor
    umami (Node app) ──▶ umami-postgres (dedicated postgres:16)   browsers
        │                                                            │
        └── public ── stats.pod.haus → stats.skycroeser.net ◀── /script.js + /api/send
  Gatus monitors site · MinIO /var/lib/minio already in nightly Backrest
```

The static site itself has no PHP, no database, no dynamic runtime, and
**no server-side mutable state** — Caddy reverse-proxies versioned MinIO
objects; the Caddyfile is config-as-code in the repo. **Umami** is the
one dynamic piece: a small Node app + its own Postgres, in a separate
stack, providing privacy-friendly (cookieless, no consent banner)
analytics. "Public" here means a more-specific Access app with a
bypass-everyone policy overriding the `*.pod.haus` wildcard (§1) — not
the absence of an Access app. Initial hostnames are `sky.pod.haus` /
`stats.pod.haus`; the `*.skycroeser.net` names land in Phase 6. The
Umami dashboard is guarded by Umami's own login.

---

## Server-side integration (podhaus specifics)

This is where the generic Publii plan meets podhaus conventions.

> **Build order (decided).** The initial build targets
> **`sky.pod.haus`**, served **publicly** (no auth) as a working demo
> on infrastructure podhaus already owns. The **skycroeser.net domain
> cutover is a separate, secondary operation** (§2, Phase 6) — it does
> not block the initial build and is not part of it. Everything in §1,
> §3, §4, §5 applies to the `sky.pod.haus` build; §2 is the deferred
> cutover.

### 1. Public exposure on `sky.pod.haus` — override the wildcard, don't bypass the module

The naive read ("public site ⇒ skip the `pod_haus_service` module") is
wrong here, and the module already supports exactly this case. The
`*.pod.haus` zone is gated by one wildcard Access app
(`pod_haus_wildcard`, Family-allow). Per `terraform/access.tf`,
**a more-specific Access application overrides the wildcard** for its
hostname. So a public `sky.pod.haus` is achieved *with* the module, by
attaching a public **bypass-everyone** policy instead of the default
locked chain — precedent already in the repo:
`komodo_webhook_bypass` and `unifi_bypass` are
`decision = "bypass", include = [{ everyone = {} }]` policies.

Concretely:

- Add a shared reusable policy in `terraform/access.tf`, e.g.
  `public_bypass` — `decision = "bypass"`, `include = [{ everyone = {} }]`
  (mirrors `unifi_bypass`; reusable so Umami's public host can share
  it).
- Add a `module "sky"` block in `terraform/services_pod_haus.tf`
  using the **pod.haus defaults** but with
  `access_policy_ids = [cloudflare_zero_trust_access_policy.public_bypass.id]`
  (the module's documented override input). This creates a
  more-specific `sky.pod.haus` Access app whose only policy is
  bypass-everyone — fully public, overriding the wildcard's Family
  gate. DNS CNAME + tunnel ingress are created by the module as usual;
  its `ingress_rule` auto-joins `pod_haus_module_ingress` in
  `tunnel.tf`.
- `backend = "http://skycroeser:80"` (the Caddy container, §3).
- `../tf plan`, review, `../tf apply` **only on explicit
  authorization**.

No new zone, no bespoke ingress, no hand-written `access_application`
for the initial build — it's a one-block module addition plus one
reusable policy.

### 2. Domain cutover to skycroeser.net (SECONDARY — deferred, not in initial build)

Only `pod.haus` exists in `terraform/variables.tf` (`local.zones`).
Moving the live domain onto this stack is a **separate operation run
after the `sky.pod.haus` demo is validated** (Phase 6). Likely shape:

- Add `skycroeser.net` to `local.zones` (new/imported `cloudflare_zone`),
  in its own `dns_skycroeser.tf`, not `dns_pod_haus.tf`.
- Proxied `CNAME` (apex via CNAME-flattening, plus `www`) →
  `<tunnel-id>.cfargotunnel.com`. cloudflared serves any hostname
  regardless of zone, so the **existing pod.haus tunnel carries it** —
  add a public ingress rule (`hostname = "skycroeser.net"`, no Access)
  to the tunnel config, before the catch-all. The same Caddy backend
  serves both `sky.pod.haus` and `skycroeser.net` (host-agnostic
  reverse-proxy to MinIO); only the redirect rules in §"URL
  preservation" become load-bearing once real WordPress inbound links
  resolve here.
- **Read the provider resource doc before writing zone/DNS resources**
  (hard rule — schemas drift between minor versions).
- Domain transfer/registrar is out of scope for podhaus; only the zone
  + records are. If the domain stays WordPress.com-managed it must be
  delegated or transferred out first (open question #3). **This is the
  one true blocker for cutover — irrelevant to the initial
  `sky.pod.haus` build.**

### 3. Serving: Caddy reverse-proxy → MinIO (DECIDED — replaces SFTP/volume)

**Decision**: deploy Publii's static output as objects in the
**existing MinIO** instance and put a thin **Caddy** stack in front for
edge concerns (legacy redirects + pretty-URL → object-path rewrites).
This supersedes the earlier SFTP-sidecar / site-volume design entirely.
Why it's strictly better here:

- MinIO already runs in the fleet (`minio/`, single-node, on
  `dockernet`) — **no new storage service** to deploy or maintain.
- The `skycroeser` stack becomes **pure config-as-code**: just Caddy +
  a repo-tracked `Caddyfile`, **zero mutable volume state**. This fully
  resolves the config-as-code tension the SFTP design carried — there
  is no "disposable cache volume" to reason about anymore; the bytes
  live as versioned MinIO objects.
- Bucket **versioning gives atomic deploy + rollback**, free; an
  in-progress Publii sync never shows a half-deployed site.
- **Backup is inherited**: `minio/compose.yaml` documents that
  `/var/lib/minio` is "backed up nightly by Backrest". The
  `skycroeser-net` bucket lives under that path, so site backup needs
  **no new Backrest bind** — confirmed from the repo, not assumed.
- No SFTP server, no extra attack surface, Publii UX unchanged
  ("click publish, it's live").

`skycroeser/` stack files:

- `skycroeser/compose.yaml` — a `caddy:*` container, `dockernet`,
  `security_opt: label:disable` (Fedora Asahi pattern, same as every
  bilby stack), autoheal label, healthcheck on `/`. `reverse_proxy
  minio:9000` (container name over dockernet — never a static IP, per
  networking rules).
- `skycroeser/Caddyfile` (or `conf/`) — **config-as-code in the repo**,
  directory-bind-mounted (not a single-file bind — hard rule). Holds
  the redirects + rewrites (see §"Caddy configuration").
- `skycroeser/stack.toml` — `server = "podhaus"` (bilby),
  `files_on_host = true`,
  `run_directory = "/etc/komodo/repo/skycroeser"`. **No init container
  → no `ignore_services`.** Rides **Stage 2** of `podhaus-push-deploy`
  automatically (`BatchDeployStackIfChanged "*"`); Cloudflare module is
  a separate `tf apply`.

> Caddy (not nginx) here: with a MinIO backend the stack is a
> *reverse-proxy with rewrites*, not a file-server, so the
> `docs-server`/nginx parity argument no longer applies — Caddy
> expresses the redirect + path-rewrite logic far more cleanly. This is
> a deliberate departure from the fleet's one static-serving precedent.

### 4. Publish: Publii → MinIO over S3 (DECIDED — replaces SFTP upload)

Publii's **S3** deploy target writes the built site straight into a
dedicated bucket. No SFTP sidecar, no Git-deploy, no server-side
upload process.

**MinIO side (one-time, via `mcli` on bilby or the console):**

1. Create bucket `skycroeser-net`.
2. Anonymous **read-only** policy on *this bucket only* (existing
   buckets — incl. the Terraform-state bucket — stay private).
3. Enable **object versioning** (rollback for bad deploys via `mc` /
   console).
4. Create a **scoped service account / access-key pair** with
   read+write **limited to `skycroeser-net`** — **never** the MinIO
   root credentials. Store the keypair in 1Password **Homelab**; it is
   Sky's-laptop client config, so it does not need to become a Komodo
   Variable (no stack consumes it server-side).

**Publii side (Sky's laptop, Server settings → S3):**

| Field | Value |
|---|---|
| Endpoint | the **tunnel-exposed S3 API URL** — see blocker below |
| Access key / secret | the scoped `skycroeser-net` service account |
| Bucket | `skycroeser-net` |
| Region | `us-east-1` (placeholder; MinIO ignores it, Publii requires a value) |
| Object ACL | `public-read` |
| Force path-style URLs | **YES** — MinIO is path-style (`endpoint/bucket/object`); virtual-host-style breaks subtly |

Test the connection from Publii before any real upload.
`files.publii.json` (deploy-state manifest) now lives in the bucket —
same gotcha as before, but reset via `mc rm` not filesystem delete.

> **BLOCKER — the S3 API is not reachable from Sky's laptop today.**
> Per `minio/compose.yaml`, MinIO's S3 API (`:9000`) is published
> **loopback-only** (`127.0.0.1:9000`, for bilby's host `mcli`) and the
> **tunnel only exposes the *console* (`:9001`) at `minio.pod.haus`** —
> the S3 API is not in the tunnel at all. Publii runs off-LAN on Sky's
> laptop and cannot reach `minio:9000` (dockernet) or `127.0.0.1:9000`
> (bilby loopback). So the MinIO design **requires a new public S3-API
> ingress**: a `module "<name>"` (e.g. `s3.pod.haus` or
> `skycroeser-s3.pod.haus`) → `http://minio:9000`, using the
> §1 **bypass-everyone** override (the scoped service-account key is
> the real authentication; Cloudflare Access is not the gate here).
> Scope the tunnel hostname to S3 only; do **not** widen the existing
> console ingress. This is the one genuinely new piece of work the
> MinIO switch introduces — it is not in Nathan's original notes.
> Decide the exact hostname at build time.

### 4a. Public S3 API — access-control & threat model (DECIDED: expose the whole API)

> **RETRACTED / SUPERSEDED (2026-05-19).** This section's
> **edge `/minio/admin/` WAF/Caddy 403 block was never a ratified
> decision** — it was a defence-in-depth proposal in this draft that
> conflicts with the enshrined **from-anywhere Terraform hard rule**
> (an admin 403 breaks the consolidated `terraform/` root, and **no TF root is
> exempt**). It has been removed. The real, sole access-control
> boundary for the public MinIO endpoint is **MinIO's own SigV4**
> (root/admin creds, held only in 1Password + the chezmoi Terraform
> env); unauthenticated calls — including `/minio/admin/` — get MinIO
> `AccessDenied`. The whole `storage.pod.haus` architecture is also
> no longer Cloudflare-proxied. **As-built source of truth:**
> [/terraform.html](../terraform.html). Do not re-derive an edge
> admin block from the text below.

**Decision**: expose the entire MinIO S3 API at the new public
hostname. The framing that makes this sound rather than reckless:
**MinIO's S3 API is designed to be internet-facing — exactly like AWS
S3 itself.** The security boundary is *not* network reachability; it is
**per-request AWS SigV4 signing + per-bucket policy**, enforced by
MinIO on every call. "On the internet" ≠ "unprotected" — an
unauthenticated request to any non-anonymous bucket returns
`AccessDenied`. We are not inventing a control plane; we are accepting
the standard S3 trust model and hardening around it. This is
proportionate for a personal site, not fortress-building — but because
the *same* MinIO also holds **`terraform-state` (Cloudflare API tokens
in plaintext tfstate)**, the model below is mandatory, not optional.

**Layered controls (defence in depth):**

1. **Edge (Cloudflare, proxied/orange-cloud).** Origin IP hidden, TLS
   terminated at CF, baseline DDoS. **WAF rule blocking `URI path
   starts-with /minio/admin/` → 403** on this hostname: the MinIO
   **admin API is served on the same `:9000` port**, so a public S3
   ingress also exposes admin endpoints. Edge-blocking the admin path
   prefix means the admin API is *never* internet-reachable even with
   valid root creds; admin stays console/loopback/dockernet-only. WAF
   path-filters without touching SigV4 (never inspects the signed
   body). **No rate-limit rule** (revised 2026-05-19): response-scoped
   counting — needed so a legit bulk Publii publish (hundreds of rapid
   PUTs from one IP) isn't throttled — is a paid-plan feature. On the
   Free plan any per-IP request-count limit is either too tight (breaks
   uploads) or too loose to matter, and SigV4 can't be brute-forced, so
   it adds no real protection. Deliberately omitted; MinIO per-request
   auth is the control. Token needs `Zone : WAF : Edit` (the
   rulesets-engine perm — *not* legacy "Firewall Services").
2. **Auth (MinIO, load-bearing).** Every operation on a non-anonymous
   bucket requires SigV4 with valid keys. `terraform-state` and all
   other buckets are **default-deny without credentials** — a public
   endpoint does not change that.
3. **Least privilege.** Publii uses a **scoped service account**:
   `s3:GetObject` / `s3:PutObject` / `s3:DeleteObject` on
   `arn:aws:s3:::skycroeser-net/*` and `s3:ListBucket` on
   `arn:aws:s3:::skycroeser-net` — and nothing else. No admin policy,
   no other bucket, **never the root keys**. Root credentials live
   only in 1Password → the `minio` stack env; **zero clients** use
   them.
4. **Bucket-policy minimalism.** `skycroeser-net` anonymous policy is
   **`s3:GetObject` only** (Caddy/public reads need it — it's a public
   website). **No anonymous `s3:ListBucket`** — visitors and scanners
   cannot enumerate objects (no fishing for unlinked drafts). Every
   other bucket has **no anonymous policy at all**.
5. **Blast-radius containment.** Worst case — the Publii scoped key
   leaks — the damage ceiling is the *public website bucket*
   (defacement), fully recoverable from object versioning + nightly
   Backrest + Sky's laptop master. The key **cannot read or write
   `terraform-state`** or call admin.
6. **Secret hygiene.** Scoped key stored in 1Password Homelab,
   rotatable on suspicion; high-entropy root password used by no
   client. *(Optional, recommended once live, not a blocker:* enable
   MinIO audit logging to the existing logging pipeline so
   auth-failure spikes and any `terraform-state` access are visible.
   Deferred to keep scope tight per personal-scale pragmatism.)*

**Why not gate it with Cloudflare Access instead of bypass-everyone:**
Publii's S3 client sends AWS SigV4 — it cannot attach
`CF-Access-Client-Id/Secret` headers, and Sky publishes from a
dynamic-IP home laptop (no IP allowlist, no mTLS). A CF Access service
token or login gate would simply **break uploads**. So the Access app
is bypass-everyone *by necessity*, and MinIO SigV4 + the WAF rules
*are* the access control. This is a deliberate, documented trade-off,
not an oversight.

**Pre-`tf apply` verification gate (prove it before it's public):**

Stand the ingress up, then from off-LAN confirm **all** of:

- [ ] `GET https://<s3-host>/terraform-state/podhaus.tfstate`
      unauthenticated → `AccessDenied` (not 200).
- [ ] `GET https://<s3-host>/skycroeser-net/` unauthenticated →
      no object listing (ListBucket denied); a known object path → 200.
- [ ] The Publii scoped key against `terraform-state` (any verb) →
      `AccessDenied`.
- [ ] `https://<s3-host>/minio/admin/...` → 403 at the WAF (blocked
      before MinIO).
- [ ] Console still only at `minio.pod.haus` behind Access; the new
      hostname serves `:9000` only, not `:9001`.
- [ ] Root keys present in **no** client config (Publii, laptop, repo).

Treat any failed check as a hard stop — do not leave the ingress
applied until every line passes.

### 5. Monitoring & backup

- **Gatus**: public endpoint check for the live site
  (`https://sky.pod.haus/` initially, `https://skycroeser.net/` post-
  cutover) in `gatus/conf/config.yaml` — unauthenticated, no service
  token. Optionally also check the S3-API ingress
  (`/minio/health/live`).
- **Backup**: **nothing new to configure.** The `skycroeser-net`
  bucket sits under `/var/lib/minio`, already in the nightly Backrest
  set (per `minio/compose.yaml`). Bucket versioning is the first line
  of rollback; Backrest is the off-box copy. Sky's laptop Publii site
  directory under git (Phase 3) remains the upstream source of truth.

---

## Analytics — Umami (shared instance)

Visitor analytics via **Umami** (self-hosted, open source, cookieless,
GDPR-friendly — no consent banner; the self-hosted OSS image ships no
AI). **One shared `umami/` stack** serves every podhaus-hosted site;
each site only registers a website (→ UUID) and injects a snippet.

**Rollout order: nathanbaxter.com first as the verification site, Sky
second.** Everything below except the per-site snippet is built and
shared; for Sky, only the `stats.skycroeser.net` tracker host + the
Publii plugin remain (see "Sky rollout — pending").

### Stack shape — built

`umami/compose.yaml` + `umami/stack.toml`:

- `umami` — `docker.io/umamisoftware/umami:3.2.0`. v3 is the current
  major; GHCR only ships v3 as an unpinned `latest`, so we pin the
  arm64 `3.2.0` on Docker Hub's official `umamisoftware` org instead of
  riding a moving tag. v3 is Postgres-only (no `DATABASE_TYPE`); tracker
  at `/script.js`, ingest at `/api/send`, liveness at `/api/heartbeat`;
  migrations auto-run on start. `dockernet`, `autoheal: "true"`,
  `curl`-based healthcheck, `depends_on` umami-postgres `service_healthy`.
- `umami-postgres` — dedicated `postgres:16` (NOT shared with
  `komodo-postgres` — control-plane DB — or `paperless-postgres` —
  app-private; the podhaus pattern is one DB container per app).
  Host-bind datadir `/var/lib/umami-pgdata` on local NVMe (the Jump
  `all_squash` breaks the postgres chown), `pg_isready` healthcheck.
- `stack.toml`: `server = "podhaus"`, `files_on_host = true`,
  `run_directory = "/etc/komodo/repo/umami"`. No init/one-shot service →
  no `ignore_services`; no build → no `run_build`. Rides Stage 2 of
  `podhaus-push-deploy`.

### Secrets (1Password → komodo-op contract)

Homelab item `Umami` with top-level fields `postgres_password` +
`app_secret` (URL-safe alphanumeric — a `@`/`/` in the password breaks
`DATABASE_URL`). `komodo-op` syncs the whole Homelab vault every 1m →
`OP__KOMODO__UMAMI__POSTGRES_PASSWORD` / `OP__KOMODO__UMAMI__APP_SECRET`.
`umami/stack.toml` references both; `DATABASE_URL` is assembled inline in
compose. Keep custom fields **top-level, not in a section** (matches the
Paperless items komodo-op already maps cleanly).

### Auth — lock the host, open two subroutes

The dashboard is **never publicly reachable on any hostname.** Two
hostname roles front the one container:

- **`stats.pod.haus` — the dashboard.** Default locked module chain
  (Homelab service-token bypass → Family allow), so viewing analytics is
  gated by Cloudflare Access. `module "stats"` in
  `services_pod_haus.tf`, `backend = "http://umami:3000"`. No public
  route here at all.
- **`stats.<site>` — per-site tracker host** (same-site with the content
  domain to dodge third-party-cookie / adblock heuristics). Locked to
  Family at the host level, with the two collection routes punched
  public via path-scoped Cloudflare Access **bypass** apps — the same
  most-specific-app-wins mechanism as the Komodo webhook bypass:
  - `stats.<site>/script.js` → public bypass (the tracker script)
  - `stats.<site>/api/send` → public bypass (the event endpoint)

  Everything else on the tracker host (dashboard, admin API) stays
  Family-gated. nathanbaxter.com's three apps + DNS live in
  `terraform/umami_analytics.tf`.

Because the dashboard reaches the browser only through Cloudflare
Access, **Umami's own login sits behind the edge gate, not in front of
the public internet** — it's defense-in-depth, not the boundary.

**Day-to-day viewing has no Umami login prompt: each `stats.<site>`
root redirects to that site's Umami Share view.** Umami's
`/share/<shareId>/<domain>` path is unauthenticated (it self-fetches a
read-only scoped token), and a Cloudflare dynamic-redirect rule
(`http_request_dynamic_redirect`, match `path eq "/"` only — so
`/script.js` + `/api/send` + the share page are untouched) sends the
bare tracker-host root there. Net flow for a Family member (Nathan or
Sky): visit `stats.nathanbaxter.com` → redirect to
`/share/<id>/nathanbaxter.com` → one Cloudflare Access login (their own
identity) → read-only overview (visitors, pages, referrers, events), no
Umami credential. The redirect ruleset lives in
`terraform/umami_analytics.tf`. **`stats.pod.haus` is deliberately NOT
redirected — it stays the admin dashboard** (Umami login, Nathan-only,
1P), used only for management (registering sites, settings). **shareId +
website UUID are Umami DB state** (set via API, backed up in pgdata; a
from-scratch rebuild without restore regenerates them and would need the
snippet UUID + the redirect's share URL refreshed — same property the
hardcoded website UUID already has).

### Backup — live-datadir restic snapshot (NOT pg_dump)

`umami-postgres` holds analytics history that is not reproducible, so it
**is** backed up — reusing the fleet's existing Postgres pattern, which
is **not** `pg_dump`: paperless and komodo both restic-snapshot the live
Postgres datadir read-only and rely on WAL crash-recovery on restore.
So: `backup/bilby/compose.yaml` binds `/var/lib/umami-pgdata` read-only,
and `config.json.tmpl` adds a `umami` plan pointing at `/userdata/umami`
(daily, bucketed retention, `skipIfUnchanged`). Rides the nightly restic
repo + OneDrive off-site sync automatically. No dump container.

### Gatus

Internal probe `http://umami:3000/api/heartbeat` (group Analytics) — the
public `stats.*` hosts are Access-locked except the two collection
routes, so an external `/api/heartbeat` probe would 302. Returns 200
when the app + Postgres are up.

### nathanbaxter.com snippet — the test site

nathanbaxter.com is an Astro static site (`LogicWolfe/nathanbaxter` →
`nathanbaxter-deploy` builds + mirrors to the `nathanbaxter-com` bucket),
not Publii — so no plugin. After Umami is live: register
`nathanbaxter.com` in the dashboard → UUID; add the Umami `<script>` to
the site `<head>` (`BaseHead.astro`), `src=https://stats.nathanbaxter.com/script.js`,
`data-website-id=<uuid>`, production-only; commit + push → the deploy
stack rebuilds. Verify events land in the dashboard.

### Sky rollout — server side DONE (2026-07-07), snippet pending

- ✅ `stats.skycroeser.net` tracker host: DNS + three Access apps +
  root → share-view redirect (`terraform/umami_analytics.tf`) + tunnel
  ingress entry — applied and verified (script public, root redirects,
  dashboard Access-gated, /api/send open).
- ✅ `skycroeser.net` registered in Umami: website UUID
  `c6ae1c0e-be58-4dac-ab9b-11d1a6002b6c`, share URL
  `https://stats.skycroeser.net/share/akYfaxpJqfylsF7D/skycroeser.net`.
- ⬜ Publii side (GUI-only): add the snippet to the site `<head>`
  (Umami plugin or custom-head):
  `<script defer src="https://stats.skycroeser.net/script.js" data-website-id="c6ae1c0e-be58-4dac-ab9b-11d1a6002b6c"></script>`
  then rebuild + publish. Verify events land at the share URL.

---

## URL preservation strategy

Publii does **not** support date-based URLs — only `/post-slug/` (or
`.html`). The slug is generated from the post title in **both**
systems, so a single regex captures the entire archive. With the MinIO
backend, the Caddyfile does two jobs in order: **(1) legacy redirects**
(WordPress paths → Publii slugs), then **(2) pretty-URL → bucket-object
rewrites** (`/about/` → `/skycroeser-net/about/index.html`), then proxy
to MinIO.

## Caddy configuration

Lives in `skycroeser/Caddyfile` (directory bind, config-as-code).
Redirects run *before* rewrites so they behave identically regardless
of backend. Exact rewrite syntax is **Caddy v2** and may need tuning
against the precise object paths Publii produces — pin and verify the
Caddy image tag.

```caddy
sky.pod.haus, skycroeser.net {
    encode gzip zstd

    # (1) WordPress legacy redirects — run first
    @wp_dated path_regexp wp ^/\d{4}/\d{2}/\d{2}/(.+?)/?$
    redir @wp_dated /{re.wp.1}/ 301
    redir /feed/ /feed.xml 301
    redir /feed  /feed.xml 301
    redir /category/uncategorized/ / 301
    redir /category/uncategorized  / 301

    # (2) pretty URLs → bucket object paths
    @dir path_regexp dir ^(/.*?)/$
    rewrite @dir /skycroeser-net{re.dir.1}/index.html
    rewrite / /skycroeser-net/index.html
    # real files (/feed.xml, /assets/...) still need the bucket prefix
    @notrewritten not path /skycroeser-net/*
    rewrite @notrewritten /skycroeser-net{uri}

    reverse_proxy minio:9000
}
```

`sky.pod.haus` is in the site address block from day one;
`skycroeser.net` is harmless until Phase 6 DNS points at the tunnel.

**URL shapes to test before go-live** (each must resolve correctly):

- `/` → `skycroeser-net/index.html`
- `/about/` → `skycroeser-net/about/index.html`
- `/about` (no slash) → 301 to `/about/` or serves the page
- `/feed.xml` → served directly (after the `/feed` redirect doesn't
  swallow it — verify ordering)
- `/assets/css/style.css` → served directly
- `/tag/feminism/` → tag page (confirm Publii tag prefix = `tag`)
- `/2020/01/20/some-post/` → 301 → `/some-post/`
- `/category/uncategorized/` → 301 → `/`

Plus: diff Publii's auto-generated slugs against the WordPress
originals and hand-fix mismatches (Phase 2); confirm Publii's tag URL
prefix is `tag`.

---

## Migration procedure

### Phase 1 — Local dry run (Sky)

1. Install Publii on Sky's laptop: install `libsecret-1-0` if absent;
   download the `.deb` (or AppImage) from
   <https://getpublii.com/download/>.
2. WordPress.com dashboard → Tools → Export → Export All; save the
   `.xml` (WXR) from the emailed link.
3. In Publii: create a new site, install + activate the Terminal theme.
4. Tools → WP Import → select the WXR.
5. Import decisions:
   - **Used taxonomy for posts**: **Tags** (her categories are
     essentially just "Uncategorized").
   - **Authors**: assign all to her as the main author.
6. Tools → Regenerate Thumbnails.
7. Preview locally and verify: static pages (Research ethics, Teaching,
   Publications, New research students); tag import (spot-check the
   extensive list); featured images (known Publii weak spot — flag
   missing); post content (especially embedded WordPress.com media
   URLs).

### Phase 2 — Slug verification (Sky, Nathan can assist)

1. Extract all post slugs from the Publii site directory.
2. Compare against the URL list from the live WordPress site.
3. For each mismatch, edit the Publii post and set the slug to match
   the WordPress original. (Publii's slug regenerate button does **not**
   auto-fire on title edits — desirable here; use it deliberately.)

### Phase 3 — Theme customisation & version control (Sky)

1. Create `themes/terminal-override/` in the Publii site directory.
2. **Initialise a git repo over the entire Publii site directory** —
   this is the durable system of record (content + overrides + config).
3. Customise in escalating order: theme settings panel → Custom CSS box
   → override folder for `.hbs`/larger CSS.
4. "Powered by Publii" footer: override the relevant template to
   remove/replace; optionally the free **Advanced Head Tag Manager**
   plugin to drop the `<meta name="generator">`. Consider keeping a
   small attribution — TidyCustoms is a small team.

### Phase 4 — Initial build & demo on `sky.pod.haus` (Nathan)

The complete working site, publicly reachable, on infra podhaus
already owns. No skycroeser.net dependency.

1. MinIO: create the `skycroeser-net` bucket (anon `GetObject` only,
   no anon list, this bucket only), enable versioning, create the
   least-priv scoped service account per *§4a*; keypair in 1Password
   Homelab. Confirm other buckets have no anon policy.
2. Create the `skycroeser/` Caddy stack (`compose.yaml` + `stack.toml`
   + repo `Caddyfile`) per *§3* — Caddy reverse-proxying `minio:9000`,
   no volume, no SFTP.
3. Caddyfile holds the legacy redirects + bucket-path rewrites per
   *Caddy configuration* — redirects are harmless no-ops on
   `sky.pod.haus` (no dated inbound links yet) and ready for cutover.
4. Create the `umami/` stack (umami + dedicated `umami-postgres`) per
   *Analytics — Umami*; secrets via 1Password → komodo-op.
5. Cloudflare: add the shared `public_bypass` policy, then
   `module "sky"`, `module "stats"`, **and the new S3-API ingress
   module** (`s3.pod.haus` → `minio:9000`, bypass-everyone) plus the
   **§4a WAF rule** (`/minio/admin/` block; no rate-limit — Free plan) per *§1* /
   *§4* / *§4a* / *Umami → Cloudflare*. `../tf plan`, review,
   `../tf apply` **only with explicit authorization**. Then run the
   **§4a verification gate** before considering the ingress live. No
   new zone.
6. Add Gatus monitors (`sky.pod.haus`, `stats.pod.haus/api/heartbeat`)
   and the umami-postgres `pg_dump` Backrest bind. **Site backup needs
   no new bind — the bucket is already under the nightly MinIO
   Backrest set** (*§5*).
7. Configure Publii's Server menu on Sky's laptop; configure the Umami
   plugin (host `stats.pod.haus`, website UUID). Publish.
8. Validate end-to-end on `sky.pod.haus`: content, tags, search,
   feed, redirect-rule spot checks, Umami events landing. **This is
   the demo.**

### Phase 5 — Pre-cutover content refresh (Nathan + Sky)

1. Final WXR re-export from WordPress.com (captures anything posted
   since the dry run).
2. Re-run the import, or apply just the delta of new posts manually.
3. Final Publii build + upload; re-validate on `sky.pod.haus`.

### Phase 6 — Domain cutover to skycroeser.net (SECONDARY, separate op)

Run only after the demo is signed off and open question #3 (domain
control) is resolved. Independent of Phases 4–5.

1. Bring skycroeser.net under Cloudflare as a new zone per *§2* (read
   the provider docs first); add the public tunnel ingress rule for
   `skycroeser.net` (+ `www`) and optionally `stats.skycroeser.net`.
2. Lower the skycroeser.net DNS TTL ~24h ahead.
3. Cut DNS: skycroeser.net → the Cloudflare Tunnel (proxied CNAME),
   public (bypass-everyone), no Family gate.
4. Verify a sample of old WordPress URLs return `301 → 200` at the new
   locations; verify `/feed.xml`, tags, static pages. The redirect
   rules become load-bearing here.
5. Repoint the Umami website + Publii plugin host to
   `stats.skycroeser.net` if adopting the same-site host; rebuild +
   publish.
6. Submit the updated sitemap to Google Search Console if SEO
   continuity matters to her.
7. Keep the WordPress.com site live but unlinked ~30 days as a safety
   net. `sky.pod.haus` can stay as a permanent staging mirror.

---

## Open questions for Sky

1. **Comments** — current site has WordPress comments; static sites
   have none natively. Options: drop entirely · email-based (Low Tech
   Magazine style: readers email, she appends manually) · self-host
   Isso/Commento/Remark42 (another podhaus stack — only if she actually
   wants threaded comments).
2. **Subscribers** — "Join 83 other subscribers" (WordPress.com email
   subs). Preserving means exporting and re-importing into a separate
   tool (self-hosted Listmonk? Buttondown?). Decide whether it's worth
   keeping at all.
3. **Domain control** — does she own/control skycroeser.net DNS, or is
   it WordPress.com-managed? This **gates the entire Cloudflare zone
   step** (*§2*). If WP.com-managed, it must be delegated/transferred
   out first.
4. **Featured image policy** — if some don't import cleanly: manually
   re-add, or drop the feature (Terminal is text-first and may not
   surface featured images prominently anyway).

## Decisions needed from Nathan (before build)

Upload mechanism, SFTP exposure, and nginx-vs-Caddy are **resolved** by
the MinIO switch (Publii S3 → bucket, Caddy reverse-proxy). Remaining:

- **S3-API ingress hostname** — name for the new public MinIO-S3 tunnel
  route (e.g. `s3.pod.haus` vs `skycroeser-s3.pod.haus`). Exposing the
  *whole* S3 API is **decided**; the security model is §4a (not an open
  question — just pick the hostname).
- Caddy v2 rewrite syntax: validate against the actual object paths
  Publii emits before go-live (pin the image tag).
- Plain HTTP Caddy→MinIO over dockernet (no internal TLS) — fine, but
  confirm.

## Nathan's server-side checklist

**Initial build (sky.pod.haus, public):**

- [ ] MinIO: `skycroeser-net` bucket; anon **`s3:GetObject` only**
      (no anon `ListBucket`), this bucket only; versioning on; scoped
      service account (GetObject/PutObject/DeleteObject on
      `skycroeser-net/*` + ListBucket on the bucket, nothing else);
      keypair in 1Password Homelab. Verify all other buckets have no
      anon policy.
- [ ] Cloudflare WAF on the S3 hostname: block `path starts-with
      /minio/admin/` → 403 (§4a). No rate-limit (Free plan).
- [ ] §4a pre-`tf apply` verification gate — every checkbox passes
      from off-LAN before leaving the ingress applied.
- [ ] `skycroeser/` stack: Caddy + repo `Caddyfile`, `reverse_proxy
      minio:9000`, dockernet, label:disable, autoheal. No volume, no
      SFTP.
- [ ] `Caddyfile`: legacy redirects + bucket-path rewrites
      (config-as-code).
- [ ] `umami/` stack: umami + dedicated `umami-postgres` (postgres:16,
      local NVMe). Umami secrets → 1Password Homelab → `komodo-op` →
      `[[…]]`.
- [ ] Shared `public_bypass` Access policy (bypass / everyone) in
      `access.tf`.
- [ ] `module "sky"` + `module "stats"` + **S3-API ingress module
      (`minio:9000`)** with `access_policy_ids` override (read provider
      docs first; `tf apply` only on authorization). **No new zone.**
- [ ] Gatus monitors: `sky.pod.haus`, `stats.pod.haus/api/heartbeat`.
- [ ] Backrest: `umami-postgres` `pg_dump` bind. **Site bucket already
      covered** by the existing `/var/lib/minio` nightly bind.

**Phase 6 (skycroeser.net cutover, deferred):**

- [ ] `skycroeser.net` Cloudflare zone + public DNS + tunnel ingress
      (+ optional `stats.skycroeser.net`).
- [ ] DNS cutover plan (TTL drop → switch → verify redirects).

## Sky's authoring-side checklist

- [ ] Install Publii (+ `libsecret-1-0`).
- [ ] Export WXR from WordPress.com.
- [ ] Run import dry run; verify content.
- [ ] Slug verification pass.
- [ ] Customise Terminal theme; **git-init the site directory**.
- [ ] Decide comments approach.
- [ ] Decide subscriber-list migration.

## Future considerations

- **Site directory in git** (Sky's laptop) is the real durable
  artifact — content, overrides, config under version control. Strongly
  recommended; server-side files stay disposable.
- **ActivityPub** — Publii has no native support; Sky is on Mastodon
  (kolektiva.social). Not critical; a future bridge service could
  syndicate posts.
- **Search** — Publii ships client-side JSON search; fine for this
  archive size. Revisit if it gets sluggish.
