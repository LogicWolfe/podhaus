# Immich, and the host resource monitoring it depends on

**Status:** Not started. Nothing in this plan has been built.

Immich is a **content sharing platform, not a content archive**. Originals
are deliberately not backed up; only Postgres is. This is expected to
change later, and the storage layout below does not foreclose it.

Two parts, in this order. Monitoring is first because it is independent,
it protects the fleet regardless of what happens next, and without it a
full Pouch surfaces as Immich mysteriously failing rather than as an
alert.

---

# Part 1 — Host resource monitoring

## What exists today

Verified, not assumed:

- **No host resource metrics anywhere.** ClickStack's metrics source is
  live and ingesting, but everything in it is `alloy_*` self-metrics,
  `esphome_*`, `gatus_*`, and Go runtime counters. No `node_*`, no
  `system_*` — no disk, memory, or CPU for any host.
- **No disk check in this repo at all.** No `df`, no filesystem
  exporter, no Gatus endpoint, no ofelia job.
- **The NAS threshold is effectively decorative.** `/etc/config/uLinux.conf`
  on kangaroo sets `Disk Free Size Alert = 3072` (MB) with
  `Disk Free Size Alert Enable = TRUE` — it fires at **3 GB free on a
  21.5 TB volume**, i.e. 99.986% full. The same file's `[Alert]` section
  has `Alert Mail = ,` — an empty recipient list. A working mail path
  exists (`ssmtp` against Mailgun as `kangaroo@pod.haus`), it is just not
  wired to this. QNAP Notification Center is installed; its rules live in
  a MariaDB instance that was not inspected.

Current capacity for reference: Pouch 21.5 TB, 8.1 TB used, **38%**.
Jump 381.6 GB, 203.7 GB used, **53%**. bilby 7.6 GB memory available with
memory PSI flat at zero.

## Collection

Every host already runs Alloy (`logging/{bilby,kangaroo,numbat,fractal,voltaire,pinelake}`)
and already scrapes and ships Prometheus metrics through the existing
mTLS pipeline to `logs-ingest.pod.haus`. Nothing new is needed to carry
the data.

Add `prometheus.exporter.unix` to each host's `config.alloy` with a
**narrow collector set — `filesystem` and `meminfo` only**. The exporter
defaults to a large collector list; numbat is 1 vCPU / 1536 MB with two
prior OOMs and must not pay for collectors nobody reads.

Because the six Alloy configs are per-host rather than shared, this is
six small edits. Keep the exporter block textually identical across
hosts so drift is visible in a diff.

## Alerting

**Gatus queries ClickHouse.** A Gatus endpoint per check, POSTing SQL to
ClickHouse's HTTP interface on dockernet and conditioning on the returned
number.

This reuses the alert path that demonstrably works — the email chain, the
`*alerts` anchor, the same dashboard as everything else — rather than
standing up a second one. The cost is coupling Gatus to the ClickStack
schema, and a ClickStack outage showing as failing checks, which is the
correct behaviour anyway.

The alternative, native HyperDX alerts, is deliberately **not** taken
here. It is cleaner conceptually, but it is an alerting surface that has
never fired in anger in this fleet, and it needs a webhook destination
configured. Closing that gap properly is its own piece of work — see the
open item in the 2026-08-09 postmortem, whose closing line is "metrics
exist, nothing pages". **Adding host metrics without alerts would repeat
that exact mistake**, which is why collection and alerting are one unit
of work here and not two.

## Thresholds

- **Disk: 85% per mount.** On Pouch that leaves roughly 3 TB of runway
  from the alert to full, which is enough to notice and act.
- **Memory: sustained exhaustion of *available*, not "used".** bilby
  carries 8.4 GB of page cache; any naive "used" check red-lines
  permanently. Alert on `MemAvailable` falling below ~10% of total for a
  sustained window, and prefer memory PSI over a point-in-time ratio if
  the exporter surfaces it.

Also correct the QTS threshold to something meaningful and give it a
recipient, as a second, independent path that survives ClickStack and
bilby both being down.

## Done when

A filled disk or exhausted memory on any of the six hosts produces an
email, and a test that artificially crosses the threshold produces one.
Not when the metrics are visible in a dashboard.

---

# Part 2 — Immich

Target version **v3.1.0** (released 2026-07-29).

## Shape

Machine learning is on fractal from day one — there is no ML-disabled
first step.

**bilby** — `immich-server` running the **api** worker only
(`IMMICH_WORKERS_INCLUDE=api`), Postgres, Valkey, and a small **CPU
machine-learning container**.

**fractal** — `immich-server` running the **microservices** worker only
(`IMMICH_WORKERS_EXCLUDE=api`), plus
`immich-machine-learning:v3.1.0-cuda` on the RTX 5090.

### Why the whole worker moves, and why there is no tunnel

The Immich server image runs one of two workers. **api** is the HTTP
server: web UI, mobile app, uploads, share links. **microservices** is
the background job runner: EXIF extraction, thumbnails, video
transcoding, CLIP embeddings, face detection, OCR. The api worker writes
the original and returns 200; nothing is viewable until a microservices
worker picks the job up.

The microservices worker **pulls** — it dials Valkey for jobs and
Postgres for results, and reads and writes files on the media volume. So
running it on fractal means fractal dials out, exactly as the Forgejo CI
runner already dials out to bilby at `10.0.0.119`. Nothing reaches into
fractal, and **no reverse tunnel is needed**. This is simpler than
splitting off only the ML container, which would have required bilby to
originate a call into WSL NAT.

The file access is also why fractal needs NFS: the worker reads originals
and writes thumbnails and transcodes. The ML container itself never
touches storage — it receives image bytes over HTTP.

### Why bilby still needs a machine-learning container

**Text search runs on the api worker.** `search.service.ts` encodes the
user's query with CLIP on the API request path (behind an embedding
cache) before doing the vector search. bilby can never reach fractal's
ML service, so without a local one, search would be permanently broken
rather than merely degraded while fractal is down.

Text encoding is a small transformer and is cheap on CPU; the expensive
work — image embeddings, face detection, OCR — stays in the
microservices worker on fractal with the GPU. Set
`MACHINE_LEARNING_PRELOAD__CLIP__TEXTUAL` on bilby's container so the one
model it actually serves is warm, and preload nothing on fractal so
`MACHINE_LEARNING_MODEL_TTL` (default 300 s) can unload idle models.

Consequence: **two config files differing in exactly one field**,
`machineLearning.urls`, each pointing at its own host's ML container.
Keep them otherwise byte-identical.

### Database and cache reachability

fractal reaches Postgres and Valkey over the LAN, so both must bind on
bilby's LAN address rather than dockernet only. bilby's firewalld
`public` zone trusts all of `10.0.0.0/24`, and fractal's traffic NATs out
as `10.0.0.70`, indistinguishable from anything else on the LAN — so
**Valkey needs `requirepass`** (`REDIS_PASSWORD`) rather than relying on
network position. Postgres already authenticates.

## Storage

`/mnt/pouch/immich` mounted as `IMMICH_MEDIA_LOCATION`, the **whole root**
on Pouch.

Do not split `upload/` from `library/`. Immich *moves* files between them
during storage-template migration; a cross-device split turns every move
into a copy.

Drop `/mnt/pouch/immich/.podhaus-share-mounted` before first deploy and
healthcheck against it, per the NFS-bind rule.

## NFS on fractal

fractal currently has **no NFS at all** — no `/mnt/pouch`, and no
`/etc/fstab` file whatsoever. All of the following is new work:

- `/etc/fstab` entry for Pouch with `x-systemd.automount`.
- `StartLimit*=0` drop-ins on the automount unit so a failed mount stays
  retryable rather than latching failed (this is the 2026-05-30 failure).
- `chattr +i` on bare `/mnt/pouch` so a container start with NFS absent
  fails loudly instead of writing to local disk. This is the
  **prevention**; the sentinel healthcheck is only detection, since an
  unhealthy container still runs and still writes.
- Extend `ansible/roles/nfs_binds/` to fractal so stopped containers
  restart once the export is healthy. This matters more on fractal than
  on bilby because fractal does not auto-recover on reboot.

**Benchmark NFS throughput from the WSL guest before trusting the GPU
win.** A 5090 that transcodes fast is moot if the mount is the
bottleneck, and this number is currently unknown.

## Failure behaviour

fractal offline means uploads land and stay unviewable until it returns;
the queue builds and drains. This is accepted.

Recovery is a nightly ofelia sweep on bilby: ping-guard, clear failed
jobs, then `PUT /api/jobs/{smartSearch,faceDetection,ocr,metadataExtraction,thumbnailGeneration,videoConversion}`
with `{"command":"start","force":false}`.

**Verify at implementation time whether the sweep is still needed in this
shape.** v3.1.0's config has `machineLearning.availabilityChecks`
(enabled, 30 s interval, 2 s timeout). If Immich skips rather than fails
ML jobs when the service is unreachable, the failure mode is gentler than
assumed and the sweep may only need to re-queue, not clear failures.

## Identity

Pocket ID OIDC, registered in `terraform/pocket_id.tf`, including the
mobile callback `app.immich:///oauth-callback`.

- `oauth.enabled: true`, `oauth.autoRegister: true` — anyone with a
  Pocket ID login gets an account automatically.
- `passwordLogin.enabled: false` — no local passwords, so no password
  endpoint to brute-force.
- `IMMICH_ALLOW_SETUP=false` — disables `/auth/admin-sign-up` and the
  restore endpoints after the first admin exists.
- **No storage quota.** `storageQuotaClaim` and `defaultStorageQuota` are
  deliberately left unset — Part 1's disk alerting is the control, not
  per-user accounting.

`IMMICH_CONFIG_FILE` makes the admin settings UI read-only. That is the
right trade for config-as-code, but it is a one-way feel worth knowing
before the first login.

## Ingress

- `lens.pod.haus` and `lens.indigopod.au`, both DNS-only A records to
  `numbat_relay_ipv4` in `terraform/services_pod_haus.tf`. The same label
  on both domains, deliberately — one name to remember, and Indigo's
  links differ from the family ones only by the domain they carry.
- Two Caddy `:4444` site blocks. No Pomerium route — this is public by
  design, because share links go to people without accounts.
- `X-Robots-Tag: noindex, nofollow` on both. **Leave Immich's shipped
  `robots.txt` alone** — it deliberately allows `/share/` and `/s/` so
  social previews render, and those OpenGraph thumbnails in a message are
  a wanted feature.
- Leave `server.externalDomain` empty so a copied link inherits whichever
  host was browsed, and Indigo's links carry her domain.

### Client IPs

Caddy sees the rathole client (`172.18.0.16` on dockernet) as the source
of every request on `:4444`; there is no `trusted_proxies` anywhere in
`caddy/`. Immich will therefore attribute every share-link view to the
tunnel.

This is accepted and does **not** block Immich — with `passwordLogin`
disabled there is no endpoint where a per-IP limit would matter, and
enumeration of share links is explicitly not a threat we are defending
against. The loss is forensic: "who viewed this album" is unanswerable.

`IMMICH_TRUSTED_PROXIES` exists and is the knob to set later, but it is
inert until something upstream injects a real client address. See
[`wstunnel-migration.md`](wstunnel-migration.md) — the PROXY-protocol
work is a good candidate to bundle with that cutover rather than do
twice.

**Open, and worth answering before go-live:** whether Pocket ID does
per-IP login throttling. If it does, every login on the internet shares
one bucket, which makes the throttle either inert or a self-inflicted
lockout. Pre-existing on an already-public IdP, not created by Immich,
but Immich delegates all its authentication to it.

## Backups

- **Originals: none, deliberately.** See the scope note at the top.
- **Postgres: yes**, via a Backrest `pg_dump` hook on bilby shaped like
  the existing `forgejo-backup-control` hook in
  `backup/bilby/config.json.tmpl`.
- Deliberately **not** Immich's own nightly database dump job — that
  executes on a microservices worker, which is on fractal, which is
  intermittent.

## Monitoring

- Gatus endpoint for the api worker.
- A **queue-depth check** is worth adding given fractal's intermittency:
  a queue that grows without draining is the signal that fractal has been
  away too long, and it is the one failure this design tolerates by
  construction and therefore will not otherwise notice.

## Settled decisions

- One family instance at `lens.pod.haus`, with `lens.indigopod.au` as a
  second hostname for Indigo's share links. `lens` covers stills and
  video without favouring either, and survives being spoken aloud or
  written on paper — her friends get links verbally or on a note, so
  dictatability was the deciding criterion.
- Audio is out of scope — Immich does not support it
  (immich-app/immich#374, closed as not planned), which is what collapsed
  the two-instance question.
- Slug entropy does not matter; memorable, dictatable links are wanted.
  The single requirement is no indexed public presence.
- Always-on, no ritual before gaming: no scale-to-zero poller, no
  preloaded models on fractal, `job.videoConversion.concurrency: 1`.

## Open questions

1. **NFS throughput from the WSL guest** — unmeasured, and it gates
   whether the GPU transcode win is real.
2. **Whether `availabilityChecks` changes the failure semantics** enough
   to simplify the nightly sweep.
