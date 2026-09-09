# Bandicoot service migration

## Goal

bilby runs only what needs its LAN devices, its NAS path or its role as
primary; fractal runs no active jobs; bandicoot carries the CPU- and
disk-heavy services plus, in its own phase, the Komodo control plane — with
memory headroom left on both bilby and bandicoot.

## Why bandicoot, and what it is not for

| Bandicoot gains | Bandicoot costs |
|---|---|
| 10 cores (bilby 8) | 1 GbE over a USB adapter on a dock (bilby is wired to the NAS) |
| 839 GB free NVMe (bilby 34 GB free of 160) | Same 15 GiB RAM as bilby — headroom must be planned, not assumed |
| Battery; gateway and kangaroo are on a UPS, so it stays *useful* through a power blip | A laptop: lid, sleep and USB autosuspend are pinned by Ansible, but the USB NIC is the one part with no redundancy |

So: CPU/disk-heavy and NAS-light work moves; LAN-device, host-network and
NAS-bandwidth-heavy work stays on bilby.

## Measured state (2026-09-09)

| Host | CPU | RAM in use | Disk | Containers |
|---|---|---|---|---|
| bilby | 8 | 7 of 15 GiB, load 1.0 | 160 GB at 79% | 47 |
| fractal | 32 vCPU | 1 of 15 GiB, idle | 1 TB + 251 GB LUKS home, 2% | 7 (docs, caddy, relay, logging, autoheal, Periphery, Forgejo runner) |
| bandicoot | 10 | 8 of 15 GiB (≈3 is GNOME + an agent session) | 857 GB at 3% | 7 (host stacks) |

bilby memory, peak since start (cgroup `memory.peak`, MiB): flood 6933, plex
5548, clickhouse 4096 (its cap), backrest 3167, brinno-downloader 2869 (cap
3072), paperless 2061, komodo-postgres 1844, music-assistant 1009,
home-assistant 793, fenwick-web-agent 755 (cap 2048), minio 701, hyperdx 683
(cap 1024), nathanbaxter-dev 666, fenwick 642. Steady CPU: clickhouse 17.6%,
everything else idle.

bilby disk: `docker system df` reports 88 GB of images and 45 GB of build
cache, all reclaimable. The disk pressure is a prune, not a migration.

## The remapping

| Service | From → To | Why | Hard dependencies to carry |
|---|---|---|---|
| Forgejo Actions runner | fractal → bandicoot | fractal keeps no active jobs; runner only needs Docker and cores | registration token fetched just-in-time from Forgejo by the role; Docker socket group |
| ClickStack (clickhouse, hyperdx, otel, mongo) | bilby → bandicoot | 21 GB local state and growing; ~6.5 GB of capped RAM; the only sustained CPU load; lives on with the UPS'd network during a blip | `/var/lib/clickstack` (rsync); mongo-dump cron (needs an Ofelia on bandicoot); Backrest overlay; ingest and UI upstreams (below) |
| Fenwick family (fenwick, signal-cli, web-agent, brinno-downloader) | bilby → bandicoot | the only burst-CPU work (HEVC, YOLO; 3 CPU + 3 GB, plus a 2 GB browser sandbox); state 25 MB | `fenwick-net`/`fenwick-webagent-net` (host_vars networks); `/var/lib/fenwick`, `/var/lib/signal-cli`, `/var/lib/brinno-downloader`; `/mnt/pouch` for the archive; the `fenwick` linked repo re-homed; Backrest |
| Paperless (+ tika, gotenberg, postgres, redis) | bilby → bandicoot | OCR is CPU-bound; 2 GB peak; 180 MB local state | `/var/lib/paperless-*`; `/mnt/jump/paperless` (documents, consume); Backrest; the `paperless-mail-init` build |
| Komodo Core (+ postgres, ferretdb, komodo-op) | bilby → bandicoot | control plane off the biggest worker; UPS'd network makes the battery a real availability win; Core beside the working checkout again, on the machine Nathan develops on | see "Control plane" — this is a control-node move, not a stack move |
| Small dev-shaped extras (nathanbaxter-dev, bugsink, umami, yiayia-stories, pets) | bilby → bandicoot, **only if** bilby still wants room after the above | individually negligible | local state dirs; Backrest |

**Stays on bilby, deliberately:** Plex, Music Assistant, Home Assistant,
ESPHome (host networking, mDNS, LAN devices, dbus); Flood and StreamFab
(Pouch-heavy, want bilby's NAS path; Flood's 6.9 GB is torrent page cache);
MinIO (holds Terraform state — moving it makes bandicoot a bootstrap
dependency of Terraform); Forgejo (small, but its backup-recover job is
coupled to Jump and bilby's Backrest); Pocket ID, 1Password Connect, Gatus,
Caddy, Backrest, Ofelia, the relay.

**Memory after the move.** bilby sheds ≈14 GB of peaks and keeps its three
spiky consumers (flood, plex, backrest ≈ 15.6 GB of peaks between them — the
shape behind the 2026-08-08 OOM). bandicoot takes ≈14 GB of peaks on 15 GiB:
fine in practice (clickhouse idles at 1.4 GB, Fenwick bursts are short and
rarely coincide with OCR), and every moved service keeps or gains a
`mem_limit`, GNOME stays resident by decision, so re-measure before the Fenwick
family commits.

## Ingress: moved services keep bilby's front door

The documented pattern for a moved service (docs/hosts.html, "Adding another
host") is one published LAN port on the new host and one Caddyfile upstream
on bilby. That is what this plan does; no Pomerium, rathole or DNS change is
needed for ClickStack, Fenwick or Paperless.

| Front door (unchanged) | Today | After |
|---|---|---|
| `logs-ingest.pod.haus` (mTLS, bilby Caddy) | `reverse_proxy clickstack-otel:4318` on dockernet | `reverse_proxy 10.0.0.90:4318` |
| `hyperdx.pod.haus` (bilby Caddy) | `hyperdx:8080` on dockernet | `10.0.0.90:8080` |
| kangaroo's Alloy | OTLP straight to `10.0.0.119:4318` | `10.0.0.90:4318` (logging/kangaroo config) |
| bilby's Alloy | `clickstack-otel:4318` on dockernet | `10.0.0.90:4318` (logging/bilby config) |
| Fenwick, Paperless web | bilby Caddy → dockernet names | bilby Caddy → `10.0.0.90:<port>` |

bilby's firewalld `public` zone already accepts everything from
`10.0.0.0/24`, and bandicoot runs the same zone, so published ports are
reachable LAN-wide without a zone edit. Gatus checks that go through the
front door are unchanged; checks that name a dockernet container move with
the stack.

## Bandicoot prerequisites (all Ansible/Komodo, no manual step)

- **NAS path, identical to bilby.** `storage_binds` gains ownership of the
  NFS fstab entries: each `storage_binds_mounts` entry renders its fstab line
  with bilby's exact options (`nfsvers=4.1,rw,nolock,soft,timeo=600,retrans=5,noatime,_netdev,nofail,x-systemd.automount`)
  and the role installs `nfs-utils`. bilby's hand-written lines (from the
  2026-05-23 incident) become role-owned as a no-op diff; bandicoot declares
  `/mnt/jump` and `/mnt/pouch`, the four rate-limit drop-in dirs, and joins
  `storage_binds_hosts`. Monitoring stays what bilby has: the recovery
  timer, sentinels and the immutable-bit tripwire — no new Gatus check
  (Nathan's decision). kangaroo exports both shares to `*`, verified from
  bandicoot.
- **Ofelia on bandicoot** (`ofelia/bandicoot`, the pinelake pattern) so
  label-driven jobs on moved containers keep running.
- **Backrest overlay** (`backup/bandicoot`) on bilby's pattern: restic repo
  on `/mnt/jump/backups`, per-service read-only binds added as each service
  arrives, Gatus push endpoint per host.
- Docker networks for Fenwick declared in `host_vars/bandicoot.yml`
  (`podhaus_extra_networks`, copied from bilby's), removed from bilby's when
  the family has moved.
- SELinux is enforcing here: every bind-mounting service carries
  `security_opt: [label:disable]` in its bandicoot form (the pattern every
  bandicoot overlay already follows).

## Per-service moves

### Forgejo runner (fractal → bandicoot)

- `playbooks/bandicoot.yml` gains `forgejo_runner` (tag `forgejo-runner`);
  `playbooks/fractal.yml` loses it. `podhaus_forgejo_internal_address` moves
  to bandicoot's host_vars.
- fractal: stop and remove the runner container and `/opt/forgejo-runner`,
  delete the fractal runner in Forgejo (repository runners API, same
  1Password token the role uses). This is the one imperative teardown; it is
  a one-way removal, so no role code.
- Verify: Forgejo lists a `bandicoot` runner idle; a push to fenwick runs on
  it; fractal's container list is docs/caddy/relay/logging/autoheal/Periphery
  only.

### ClickStack (bilby → bandicoot)

- Stack config: `server = "bandicoot"`, `linked_repo = "podhaus-bandicoot"`,
  `run_directory = "clickstack"`; `PODHAUS_REPO` pinned in the stack's
  environment to the linked-repo path on bandicoot
  (`/opt/komodo-periphery/etc-komodo/repos/podhaus-bandicoot`) so the
  config.d and scripts binds resolve. `hyperdx` publishes `8080` on the LAN
  beside otel's `4318`. `label:disable` on the bind-mounting services.
- Data: stop the stack on bilby, `rsync -aHAX /var/lib/clickstack/` to
  bandicoot (21 GB at 1 GbE), keep ownership, deploy on bandicoot. Downtime
  is the copy; Alloy on every host retries, so the gap is a delay, not loss
  (approved).
- Upstreams: the four rows in the ingress table.
- Cron: `clickstack-mongo-dump` label is on the mongo container; bandicoot's
  Ofelia runs it. Backrest overlay carries `/var/lib/clickstack/mongo-dumps`.
- Verify: `logs-ingest.pod.haus` accepts a shipped record from bandicoot,
  bilby and kangaroo (rows with `host` = each, after the move); HyperDX UI
  through `hyperdx.pod.haus`; the mongo dump appears on bandicoot's schedule;
  ClickHouse row count before/after the copy matches.

### Fenwick family (bilby → bandicoot)

- Networks first (host_vars, docker role, run both playbooks).
- `fenwick` linked repo: `server = "bandicoot"` (the clone re-homes on
  bandicoot's Periphery); the four stack.toml files in the fenwick repo:
  `server = "bandicoot"`. Brinno keeps `/mnt/pouch` (NAS path prerequisite)
  and gains the Pouch sentinel in `storage_binds_extra_sentinels`.
- Data: `/var/lib/fenwick`, `/var/lib/signal-cli`,
  `/var/lib/brinno-downloader` rsync'd with ownership. signal-cli's identity
  is in that state dir, so this is a stop-copy-start, not a parallel run —
  two live registrations of one Signal number is the failure to avoid.
- Backrest: the three dirs move from `backup/bilby` to `backup/bandicoot`.
- Verify: the bot answers on Signal; a Brinno archive lands on Pouch; Gatus
  `timelapse_brinno` heartbeat keeps arriving; the runner (now on the same
  host) builds the images.

### Paperless (bilby → bandicoot)

- Stack config as for ClickStack (`files_on_host` → linked repo, path pin,
  `label:disable`); `/mnt/jump/paperless` sentinels and the
  `.podhaus-share-mounted` marker check the compose already does.
- Data: `/var/lib/paperless-pgdata` and `/var/lib/paperless-data` rsync'd
  stopped; documents stay on Jump.
- Backrest: paperless binds move to `backup/bandicoot`.
- Verify: login, a document consumed from the Jump consume folder, the
  nightly Backrest snapshot from bandicoot.

### Control plane (Komodo Core → bandicoot)

Bigger than a stack move: the repo binds Core, the Ansible/Terraform control
node (`/opt/komodo/keys` with every Periphery private key,
`podhaus_komodo_core_url` on loopback) and Nathan's working checkout to one
host, and `komodo-sync` overlays that checkout into Core's deploy tree.
Moving Core means bandicoot becomes the control node; splitting them breaks
`komodo-sync`.

- What moves: `komodo_core_host` role membership, `komodo/ferretdb.compose.yaml`
  stack via `komodo-start`, the deploy tree, `komodo-op`, `/opt/komodo/keys`,
  the `podhaus-deploy` repo resource, Postgres data (3.4 GB) and FerretDB.
  Ansible and Terraform then run from bandicoot.
- Ingress: `komodo.pod.haus`, `core-connect.pod.haus` (every outbound
  Periphery dials it) and the GitHub webhook listener re-point — either bilby
  Caddy upstreams to `10.0.0.90` as for ClickStack (keeps the front door on
  bilby, so a bilby outage still takes the control plane's door with it), or
  routes moved to bandicoot's own rathole/Caddy (the front door survives
  bilby). The second is the one that delivers the availability goal.
- bilby's Periphery becomes an outbound one like every other host.
- bandicoot becomes a bootstrap dependency of the fleet; the USB NIC is the
  named risk, mitigated by the autosuspend pin and the UniFi reservation.

Done last, as its own phase, after the stack moves have proven bandicoot
stable — none of the stack moves depend on it.

## Order, by dependency

1. Prerequisites: NAS path (storage_binds extension, both hosts), Ofelia on
   bandicoot, Backrest overlay skeleton.
2. Runner off fractal (no state; fastest fractal win).
3. ClickStack (biggest bilby win). Measure bandicoot.
4. Fenwick family. Measure.
5. Paperless.
6. bilby `docker system prune` (images + build cache).
7. Control plane — after Nathan's decisions below.
8. Extras only if the measurements ask for them.

## Decisions that are Nathan's

| Decision | Recommendation | Trade-off |
|---|---|---|
| bandicoot to `multi-user.target` (no GNOME/GDM) | **Decided: keep GNOME.** Nathan wants the laptop usable as one; cull only when a move needs the 1–2 GB | No local GUI on the laptop; SSH only |
| Control-plane front door | Routes on bandicoot's own relay (survives bilby) | More Terraform/relay work than bilby upstreams |
| bilby's Periphery after Core moves | Outbound, like every other host | None material; it is the fleet pattern |
| Move the small extras | No, unless bilby measures tight after 3–5 | Extra moves for negligible gain |

## What was done

- ✅ NAS path: `storage_binds` renders the NFS fstab entries and installs the
  client; bilby adopted its hand-written lines (`changed=0` after); bandicoot
  mounts Jump and Pouch with sentinels, tripwire and the recovery timer.
  `ofelia/bandicoot` runs. (8e7909b)
- ✅ Runner: `bandicoot` registered idle in Forgejo; fractal's runner torn
  down and deregistered; fractal runs docs/caddy/relay/logging/autoheal/
  Periphery only. (2534886)
- ✅ ClickStack on bandicoot: 830 M rows carried over by a stopped-state
  rsync; fresh rows from every host within minutes; `watch.pod.haus` and
  `logs-ingest.pod.haus` proxied from bilby; Gatus heartbeats query
  `10.0.0.90:8123`; Ofelia registered the mongo-dump job. bilby's pre-move
  copy and the stack's images were deleted after verification (bilby disk
  79% → 61%). (7c90fa7)
- ✅ `backup/bandicoot`: restic repo on `/mnt/jump/backups-bandicoot`,
  the mongo dumps as its first plan, Gatus heartbeat and container probe;
  container healthy, Gatus green. (0bc718e)
- ✅ Runner proven: fenwick CI run 26 (deno, webui, web-agent,
  brinno-downloader, promote) went green on the `bandicoot` runner and
  advanced the `deploy` branch.
- ✅ Paperless re-homed (44b34cc): state copied stopped, stack, Caddy, Gatus
  and Backrest plan moved; healthy on bandicoot, documents on Jump visible,
  mail-init converged, `paperless.pod.haus` answers through Pomerium, Gatus
  green.
- ⛔ Fenwick family: **blocked on a decision.** The bot reaches
  1Password Connect (`op-connect-api`) and Bugsink by dockernet name and
  neither publishes a LAN port, so a move needs one of: bilby publishing
  Connect (token-authenticated) and Bugsink on the LAN, on the same
  published-port pattern as Gatus's `:8080`; or the Fenwick family staying
  on bilby. Exposing a secrets API on the LAN is Nathan's call. Interim:
  the bot's own telemetry export was re-pointed at `10.0.0.90:4318`
  (fenwick 46fdc1f) because the collector left bilby's dockernet.
- Not done, deliberately: bilby's `docker system prune`. Pruning the build
  cache changes the next fenwick/pets push from a container-level no-op to
  a rebuild; that trade-off is Nathan's.

The plan is deleted when everything above is folded into `docs/hosts.html`,
`docs/monitoring.html` and `docs/host-provisioning.md`.
