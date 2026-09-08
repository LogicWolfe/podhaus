# Doggos Alive — from Railway to MinIO

**Goal.** `doggos.indigopod.au` is served from a versioned MinIO bucket on
bilby, Indigo publishes new versions to it herself from Blocs on her iPad,
and the Railway account is empty and closed.

## What it is today

| Fact | Evidence |
|---|---|
| Static site exported from Blocs for iPad: 11 pages, 11 MB, Bootstrap + Blocs runtime, lazy-loaded images. No server logic. | `LogicWolfe/indigo-web-server` on GitHub, `web/` |
| Hosted on Railway (project *Indigo's Stuff*, service `indigo-web-server`) as a `caddy:alpine` image built from that repo. No volume. Last deploy 2025-09-16. | Railway API; `railway.toml`, `Dockerfile` |
| DNS is a Cloudflare CNAME to `x0y6bs3z.up.railway.app`, unproxied. | `terraform/dns_pod_haus.tf` `pod_haus_external_cnames` |
| The publishing loop is Nathan: Indigo exports from Blocs, Nathan commits `web/` and pushes; Railway rebuilds. All 17 commits are his. | git log |
| A self-serve upload path was tried and abandoned in one day: SFTP + PHP, then FTP, then "streamline to simple static site with Caddy only" (2025-09-13). Railway's single TCP proxy per service made FTP passive mode and SSH awkward. | commits `59edcfe`, `3629798`, `56a18cf` |
| The Blocs *project* (the editable thing) lives only on her iPad. The repo and the site hold exports. | Blocs exports HTML; no `.bloc` file anywhere in the repo |
| Nothing monitors it. | no Gatus entry |

## The case

Moving a 11 MB static site is not worth a plan on its own. What earns it:

- **Undo for a kid.** A versioned bucket keeps every file she overwrites.
  A bad publish is `mc undo` away instead of a git archaeology session.
- **Self-serve publishing that actually works.** Blocs has a built-in
  *Publish* over SFTP on iPad (confirmed on the Blocs forum's iPad
  category and the publishing docs), and MinIO has a built-in SFTP server
  scoped by the same IAM policy as the S3 API. No FTP daemon, no PHP, no
  extra container — the two pieces the 2025 attempt fought Railway for are
  now one flag on a service podhaus already runs.
- **Same shape as the other two static sites.** Bucket, scoped deploy
  credential, Caddy block rewriting pretty URLs to bucket keys. Nothing new
  to learn to operate it.
- **Railway goes to zero.** The board is gone; this is the last project.

What it does not give: a backup of her *project*. The bucket holds exports.
If the iPad dies, the site survives but the ability to edit it goes with the
Blocs file. That is an iCloud-backup question for her iPad, outside this plan,
and worth saying to her once.

## The upload path, proven

A scratch MinIO (`RELEASE.2025-09-07`, the version bilby runs) started with
`--sftp="address=:8022" --sftp="ssh-private-key=…"`, a bucket
`doggos-indigo` with versioning, and the exact policy shape from
`terraform/minio.tf` attached to a user and a service account:

| Operation, as the scoped user | Result |
|---|---|
| Log in with the IAM user name + secret as password | OK |
| Log in as a service account (`<access-key>=svc` + secret) | OK |
| Wrong password | refused |
| `ls /` | shows only `doggos-indigo` |
| `put index.html`, `put css/…`, `mkdir css` | OK (`mkdir` leaves a zero-byte `css/` marker object; harmless) |
| Overwrite `index.html` four times | four versions in the bucket |
| `rm` | OK |
| `rename` | **unsupported** (MinIO SFTP does not do rename or append) |
| `put` at `/`, into another bucket, `mkdir` a new bucket | Access Denied |

The one thing not provable from a Linux box is Blocs' own SFTP client. It
has to be tried once from her iPad against the real host; that is the first
verification step below and the plan's kill criterion. The known risk is
`rename`: a client that uploads to a temp name and renames into place will
fail against MinIO. Blocs' "just the changes" mode works from its own
manifest, which is not that pattern, but it is unverified.

**If Blocs' client fails:** she exports to Files and uploads with an SFTP
client app (FTP Files, Documents by Readdle — both do plain puts). If that
is judged too much for her, the site still lives in the bucket and Nathan
mirrors exports with `mc mirror`, which is no worse than today.

## Where the SFTP port is reachable — a decision

| | LAN only (recommended) | Public via Numbat |
|---|---|---|
| How | `ports: 8022:8022` on the minio service; she uses `bilby.pod.haus`, port 8022. Docker-published ports bypass firewalld, but bilby has no public path except the relay, so this is LAN-reachable only. | New rathole service (`minio_sftp` → `minio:8022`) in `relay/bilby` and `relay/numbat`, a port opened on the relay address in `ansible/roles/numbat_edge`, DNS name. The `forgejo_ssh` shape. |
| Cost | one line | relay + nftables + a public password-auth SSH port to rate-limit |
| Trade-off | she can publish only at home | she can publish anywhere |

Recommendation: LAN only. A child's website publishes from the couch; a
password-authenticated SSH port on the internet is a thing to defend for no
benefit she will use. If that turns out wrong, the public path is additive.

## Components

Each row is one change; order follows dependencies. ✅ marks what is built.

| Component | Change | Where |
|---|---|---|
| ✅ **Bucket + credential** — applied 2026-09-08; the deploy user logs in directly, no service account; 1Password items *Doggos Indigo Publish* (login + Blocs fields) and *MinIO SFTP Host Key* are Terraform-written. | `doggos-indigo` bucket, versioning on, anonymous `GetObject` only, deploy policy + IAM user + service account, sensitive outputs. Copy of the `skycroeser_net` block with the name swapped. Credentials go to a 1Password Homelab item *MinIO Doggos Indigo Deploy*. | `terraform/minio.tf` |
| ✅ **SFTP server** — `minio-secrets-init` + `--sftp` flags + `8022:8022` in `minio/`; host key from 1Password via `OP__KOMODO__MINIO_SFTP_HOST_KEY__PRIVATE_KEY_B64`. | `--sftp="address=:8022"` and `--sftp="ssh-private-key=/run/podhaus-secrets/sftp-host-key"` on `minio`; `ports: 8022:8022`. Host key generated once (`ssh-keygen -t ed25519`), kept in 1Password as base64, written into a secrets volume by a `minio-secrets-init` one-shot in the `caddy-secrets-init` shape (so the host key never changes and her iPad never sees a changed-key warning). `ignore_services` gains the init. | `minio/compose.yaml`, `minio/stack.toml`, 1Password item *MinIO SFTP host key* |
| **DNS** | Remove `doggos.indigo` from `pod_haus_external_cnames`; add an A record to `numbat_relay_ipv4`, unproxied, in the `yiayia_pod_haus` shape. pod.haus is not a CDN zone; no cache contract. | `terraform/dns_pod_haus.tf` |
| ✅ **Serving** — `(doggos_site)` snippet and `doggos.indigopod.au:4444` block. | `doggos.indigopod.au:4444` block: Cloudflare DNS TLS, `Cache-Control "no-cache"` (Blocs busts CSS/JS with query strings; images revalidate on ETag), styled `404.html` from the bucket with `replace_status`, `/` → `index.html`, `<dir>/` and extensionless → `<dir>/index.html`, everything else → `/doggos-indigo{path}`, `reverse_proxy minio:9000` turning `NoSuchKey` into a 404. The `sky_site` snippet minus its redirects and cache tags. | `caddy/Caddyfile` |
| ✅ **First load** — 48 objects mirrored with her credential; anonymous read 200, listing 403, other buckets denied. | `mc mirror --overwrite web/ local/doggos-indigo` from bilby using the deploy credential (proves the credential too). Then `curl` a page through the new block before DNS moves. | one-off, from the repo checkout |
| **Her publishing** | Blocs → Settings → Publish: Address `bilby.pod.haus`, Port `8022`, Protocol `SFTP`, Username `doggos-indigo-deploy`, Password from 1Password, Path `/doggos-indigo`. First publish "entire site", then "changes only". | her iPad; written up in the runbook |
| ✅ **Monitoring** — Gatus entry added. | `doggos.indigopod.au` external check in the `nathanbaxter.com` shape (200, `<<: *defaults`). | `gatus/conf/config.yaml` |
| **Backup** | Nothing to add: `/var/lib/minio` is already under the `minio` Backrest plan; versioning means her own overwrites are recoverable without it. | — |
| **Repository** | Move `indigo-web-server` to `git.pod.haus/LogicWolfe/indigo-web-server` as the record of the Railway era, archive the GitHub copy. The bucket is the live copy from then on; the repo is not updated. | Forgejo, GitHub |
| **Railway** | Delete *Indigo's Stuff*, close the account, delete the 1Password item `railway-api-token`. | Railway, 1Password |
| ✅ **Docs** — `docs/runbooks/doggos-indigo.md` written. | Runbook `docs/runbooks/doggos-indigo.md`: what it is, how she publishes (the Blocs settings above, in plain words), how to roll back a bad publish (`mc undo` / restore a version), how to rotate her password. A row in `docs/hosts.html`/`networking.html` wherever the other bucket-served sites are listed. Then delete this plan. | `docs/` |

Not doing: Cloudflare CDN (the other public sites earn it by traffic; this
one does not), FTP or FTPS (MinIO offers them; SFTP is what Blocs
recommends and the only one without TLS certificate plumbing), a custom
domain change, key-based SSH auth (Blocs is password-only).

## Verification

1. **Blocs publishes from her iPad to `bilby.pod.haus:8022`** — full site
   once, then a one-page change with "just the changes". This is the go /
   no-go for self-serve; do it before DNS moves, against the new block by
   host header.
2. **The served site matches the export**: `mc mirror` reports nothing to
   do against the repo's `web/`; a sample of pages and one image return
   200 with the right `Content-Type`; a missing path returns a real 404
   with the styled page.
3. **Undo works**: overwrite `index.html`, list its versions, restore the
   previous one, confirm the page changed back.
4. **The credential is scoped**: the deploy user cannot list or write
   any other bucket (the scratch run above, repeated against production
   once).
5. **Gatus is green**; the Railway hostname no longer resolves; the
   account is closed.

## Decisions for Nathan

1. **LAN-only SFTP** as recommended, or the public relay path.
2. **Delete the GitHub repo** after the move, or leave it archived.
3. **Close the Railway account** (the last project goes with this plan).
