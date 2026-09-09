# Bandicoot service migration

## Goal

bilby runs only what needs its LAN devices, its NAS path or its role as the
public front door; fractal runs no active jobs; bandicoot carries the CPU-
and disk-heavy services **and the control plane** (Komodo Core, 1Password
Connect, komodo-op), so that a mains outage — the gateway and the NAS are on
a UPS, bandicoot has a battery — leaves the fleet manageable. Memory
headroom stays on both bilby and bandicoot.

## Why bandicoot, and what it is not for

| Bandicoot gains | Bandicoot costs |
|---|---|
| 10 cores (bilby 8) | 1 GbE over a USB adapter on a dock (bilby is wired to the NAS) |
| 839 GB free NVMe (bilby 34 GB free of 160) | Same 15 GiB RAM as bilby — headroom must be planned, not assumed |
| Battery; gateway and kangaroo are on a UPS, so it stays *useful* through a power blip | A laptop: lid, sleep and USB autosuspend are pinned by Ansible, but the USB NIC is the one part with no redundancy |

So: CPU/disk-heavy, NAS-light work and the control plane move; LAN-device,
host-network and NAS-bandwidth-heavy work stays on bilby. GNOME stays on
bandicoot by decision (Nathan uses it as a laptop); it is culled only when
a move does not fit.

## Where everything lands

| Service | Host | Status |
|---|---|---|
| Forgejo Actions runner | bandicoot | ✅ moved from fractal (2534886) |
| ClickStack (clickhouse, hyperdx, otel, mongo) | bandicoot | ✅ moved (7c90fa7); front door stays on bilby's Caddy |
| Backrest overlay `backup/bandicoot`, Ofelia `ofelia/bandicoot`, NAS path | bandicoot | ✅ (0bc718e, 8e7909b) |
| Paperless (+ tika, gotenberg, postgres, redis) | bilby | ✅ moved back from bandicoot |
| Komodo Core (+ postgres, ferretdb) | **bandicoot** | ✅ moved (432c350, 3ad7e29) |
| `onepassword` (op-connect-api, op-connect-sync, komodo-op) | **bandicoot** | ✅ moved with the existing credentials — no new Connect server |
| Fenwick family (fenwick, signal-cli, web-agent, brinno-downloader) | **bandicoot** | ✅ moved (77caca3, 97d7d2d, 57b571b) |
| Plex, Music Assistant, Home Assistant, ESPHome, Flood, StreamFab, MinIO, Forgejo, Pocket ID, Gatus, Caddy, Backrest, Ofelia, the relay, Bugsink, Umami, pets, yiayia-stories, nathanbaxter-dev | bilby | stay |

**Memory after the moves.** bandicoot today: 9.9 GB used of 15.4 with
Paperless resident (≈2 GB peak) and GNOME (≈1.4 GB shmem). Paperless leaves;
Core + Postgres (1.8 GB peak) + FerretDB, Connect + komodo-op (≈0.5 GB) and
the Fenwick family (≈1 GB idle; bursts capped at 3 GB brinno + 2 GB
web-agent) arrive. Idle lands near 12 GB; the worst case — a ClickHouse
query at its 4 GB cap during a Brinno transcode and a browser session — is
above physical RAM and lands in swap (8 GB). Mitigations: every moved
service keeps or gains a `mem_limit` (the bot gets one), and each step
re-measures before the next commits. GNOME is the reserve lever and is
Nathan's call. bilby drops to ≈4 GB idle with Paperless back.

## Ingress: moved services keep bilby's front door

The documented pattern for a moved service (docs/hosts.html, "Adding another
host") is one published LAN port on the new host and one Caddyfile upstream
on bilby. Both hosts' firewalld `public` zone accepts `10.0.0.0/24`, so
published ports are reachable LAN-wide without a zone edit. The control
plane follows the same pattern first (stage 1); moving its front door onto
bandicoot's own relay (stage 2) is a separate decision below.

---

## Step 1 — Paperless back to bilby

The exact reverse of 44b34cc; nothing new.

| Where | Change |
|---|---|
| `paperless/stack.toml` | `server = "podhaus"`, `files_on_host = true`, `run_directory = "/etc/komodo/repo/paperless"`, env `PODHAUS_REPO=[[PODHAUS_REPO]]`; drop the bandicoot comment |
| `paperless/compose.yaml` | drop the published `8000:8000` (Caddy and Gatus reach it by name on dockernet again) |
| `caddy/Caddyfile` | `@paperless` → `paperless:8000`; `paperless-api.pod.haus:4444` → `paperless:8000` |
| `gatus/conf/config.yaml` | Paperless check → `http://paperless:8000/` |
| `backup/bilby/{compose.yaml,config.json.tmpl}` | the three paperless binds and the `paperless` plan return; removed from `backup/bandicoot` |
| `ansible/inventory/host_vars/bandicoot.yml` | drop the two `/mnt/jump/paperless*` sentinels (bilby still declares them; the files on Jump stay) |
| docs | `docs/runbooks/paperless.html`, `docs/hosts.html` (bandicoot's stack list), `AGENTS.md` mention |

**State.** bilby's copies were pruned after the move, so the data comes back
from bandicoot: stop the six paperless containers on bandicoot by name, rsync
`/var/lib/paperless-pgdata` and `/var/lib/paperless-data` (≈180 MB) to bilby
as root with ownership preserved (the fleet rsync pattern, pulled from
bilby), then commit + push; `podhaus-push-deploy` deploys on bilby. After
verification, `docker rm` the six on bandicoot and delete its two state
dirs; bandicoot's Backrest overlay redeploys without the binds.

**Verify.** Login through `paperless.pod.haus`; document count unchanged;
a document dropped in the Jump consume folder is consumed; Gatus
"Paperless" green; bilby Backrest shows the `paperless` plan; bandicoot's
container list has no paperless-*.

---

## Step 2 — Control plane to bandicoot

Bigger than a stack move: Core, the deploy tree it syncs from, the fleet's
Periphery private keys, `komodo-start`/`komodo-sync`, Ansible's control
node and Terraform's runner are one unit, and all of it moves together.
bilby becomes an ordinary outbound-Periphery host with files_on_host stacks.

### 2a. Design

| Concern | Today (bilby) | After (bandicoot) |
|---|---|---|
| Core compose | `komodo/ferretdb.compose.yaml`: postgres, ferretdb, core **and bilby's inbound Periphery** | the same file minus the `periphery` service; `extra_hosts: git.pod.haus:10.0.0.119` (bilby's internal Caddy, the address bandicoot's runner already uses) instead of `host-gateway` |
| Core's sync tree `/syncs/podhaus` | bilby's Komodo-managed clone `/etc/komodo/repos/podhaus-deploy` (Repo `podhaus-deploy`, server `podhaus`) | bandicoot's existing Komodo-managed clone `/opt/komodo-periphery/etc-komodo/repos/podhaus-bandicoot` (Repo `podhaus-bandicoot`), which gains `on_pull = "git clean -fd"` like `podhaus-deploy` has. `podhaus-push-deploy` Stage 0 pulls **both** repos: bilby's tree still feeds bilby's files_on_host stacks (`PODHAUS_REPO` stays `/etc/komodo/repos/podhaus-deploy`); bandicoot's feeds the sync and bandicoot's linked-repo stacks |
| Working checkout `/syncs/podhaus-local` | `~/repos/podhaus` on bilby | `~/repos/podhaus` on bandicoot (cloned with the machine key, with the Pipenv toolchain from README so pre-commit and Ansible run there) |
| `komodo-start` | creates Repo `podhaus-deploy` on server `podhaus`; `KOMODO_FIRST_SERVER=https://periphery:8120` creates that server on a cold DB | creates the Core host's server (`bandicoot`, `address = ""`) and its tree repo (`podhaus-bandicoot`) if missing, then pulls it; `KOMODO_FIRST_SERVER*` dropped (there is no in-compose Periphery). Cold bootstrap on bandicoot is reasoned, not rehearsed — listed as a follow-up |
| Keys `/opt/komodo/keys` | bilby (every Periphery's private key) | bandicoot, same path and mode; **removed from bilby** — bilby keeps only its own `periphery.key` + `core.pub` under `/opt/komodo-periphery/keys` like every other host |
| `komodo_core_host` role | `komodo_core_hosts: [bilby]`; creates `/etc/komodo/ssl` and `/opt/komodo/keys` | `komodo_core_hosts: [bandicoot]`; the ssl task goes (it served bilby's in-compose Periphery, whose dir already exists) |
| bilby's Periphery | inbound, in Core's compose, address `https://periphery:8120` | outbound, bootstrap-managed by the `komodo_periphery` role from a new `bilby/periphery/compose.yaml`: root stays `/etc/komodo` with the `/etc/komodo/repos/podhaus-deploy:/etc/komodo/repo` alias bind so every `run_directory = /etc/komodo/repo/<stack>` is untouched; keys from `/opt/komodo-periphery/keys`; `PERIPHERY_CORE_ADDRESSES: ws://bandicoot.pod.haus:9120` (LAN, direct, like kangaroo); `PERIPHERY_CONNECT_AS: podhaus`. servers.toml `podhaus` → `address = ""`. The role's readiness check looks for a server named after the inventory host, so it gains `podhaus_periphery_server_name` (default `inventory_hostname`; bilby sets `podhaus`) |
| bandicoot's Periphery | dials `wss://core-connect.pod.haus` | dials `ws://bandicoot.pod.haus:9120` — Core is on the same host, so the internet path is no longer a dependency; gains `extra_hosts: git.pod.haus:10.0.0.119` for the Fenwick linked repo (step 3) |
| kangaroo's Periphery | `ws://10.0.0.119:9120` | `ws://10.0.0.90:9120` (`kangaroo/periphery/compose.yaml`, applied the way `kangaroo_bootstrap` applies it) |
| fractal, voltaire, pinelake, numbat | `wss://core-connect.pod.haus` | unchanged; the front door re-points (below) |
| Front door, stage 1 | bilby Caddy `@komodo komodo-core:9120`; `core-connect.pod.haus` → `komodo-core:9120`; Pomerium routes and the GitHub webhook URL | bilby Caddy → `10.0.0.90:9120` for both; Core publishes 9120 on bandicoot's LAN address; nothing else changes |
| Gatus | 17 checks POST `http://komodo-core:9120/read` | `http://10.0.0.90:9120/read` |
| `onepassword` stack | files_on_host on bilby | `server = "bandicoot"`, `linked_repo = "podhaus-bandicoot"`, `run_directory = "onepassword"`; same env (the credentials file and Connect token Komodo variables move with the DB); komodo-op reaches `komodo-core:9120` on bandicoot's dockernet; the arm64 image builds locally there as it did on bilby |
| Backrest | `backup/bilby` binds `komodo_postgres-data`, `komodo_ferretdb-state`, `onepassword_op-connect-data` + plans `komodo`, `onepassword` | move to `backup/bandicoot` |
| Komodo's own nightly DB dumps `/opt/komodo/backups` | bilby, 169 MB | copied to bandicoot's `/opt/komodo/backups` |
| Ansible control node | bilby (`ansible_connection: local`) | bandicoot (`ansible_connection: local`, `ansible_python_interpreter: /usr/bin/python3`); bilby becomes an SSH target (`ansible_host: bilby.pod.haus`). `podhaus_komodo_core_url` stays loopback |
| Terraform | run from bilby | run from bandicoot (state is in MinIO via `storage.pod.haus`; nothing host-pinned) |
| Logging | bilby's Alloy parsers for komodo-core/op/postgres/ferretdb, op-connect-* | bandicoot's Alloy carries the same parser files already; verify the chain in its `config.alloy` |
| Docs | | `docs/komodo.html`, `docs/hosts.html` (bilby and bandicoot sections, control-node statement), `docs/host-provisioning.md`, `docs/disaster-recovery.html`, `docs/secrets.html`, `AGENTS.md` (komodo-start/komodo-sync/deploy-tree paragraphs, the ansible row), `README.md` ("Bootstrap the remote hosts from bilby") |

Rejected: a second Repo resource on bandicoot solely for Core's tree
(one more clone of the same branch for no gain); renaming server `podhaus`
to `bilby` now (25 stack.toml files, Gatus bodies, docs — a later cleanup,
listed below); keeping Core's sync tree on bilby (Core cannot bind a remote
path, and it would pin the control plane to the host it is leaving).

### 2b. Cutover sequence

Core is unavailable from step 4 to step 8: no deploys, no Komodo alerts,
Connect down (the Fenwick bot's email tools fail for the window). Running
stacks are unaffected. Approved.

1. **Prepare bandicoot, no downtime.** Commit the code changes above on
   bilby's checkout but do not push yet; fetch them into bandicoot's
   `~/repos/podhaus` over SSH (a `bilby` git remote), because the new
   inventory makes bandicoot the local control node and bilby an SSH
   target — every Ansible run from here on is from bandicoot. On bandicoot:
   `playbooks/bandicoot.yml --tags komodo` creates `/opt/komodo/keys`;
   rsync `/opt/komodo/keys` and `/opt/komodo/backups` from bilby; pre-create
   the three named volumes (`komodo_postgres-data`, `komodo_ferretdb-state`,
   `onepassword_op-connect-data`).
2. **bandicoot's Periphery keeps dialling `core-connect`** until step 6 —
   re-pointing it earlier would leave the role's readiness check with no
   Core to ask.
3. **Snapshot for rollback**: on bilby, note `docker volume` sizes and keep
   the three volumes and `/opt/komodo/keys` untouched until step 10.
4. **Stop on bilby** by name: komodo-core, komodo-op, op-connect-api,
   op-connect-sync, komodo-ferretdb, komodo-postgres, komodo-periphery.
5. **Copy state**: the three volumes' `_data` directories from bilby into
   bandicoot's pre-created volumes (rsync as root, ownership preserved).
6. **Push** the prepared commits (the webhook lands on a dead Core and is
   simply lost). On bandicoot, in order: (a) bring Core up by hand with the
   compose command `komodo-start` uses (`op run --env-file komodo/compose.env
   -- docker compose -p komodo -f komodo/ferretdb.compose.yaml ... up -d`)
   so Core is answering on the copied DB; (b) `playbooks/bandicoot.yml
   --tags periphery` re-points bandicoot's Periphery to
   `ws://bandicoot.pod.haus:9120` and waits for Core to report it Ok;
   (c) `op-vault dev -- ./komodo-start` (idempotent: compose is a no-op)
   seeds the variables, ensures the tree repo, pulls it and runs the double
   sync.
7. **bilby's Periphery**: from bandicoot, `playbooks/bilby.yml --tags periphery`
   (first Ansible run from the new control node) installs the outbound
   Periphery and waits for Core to report `podhaus` Ok. Remove the stopped
   old periphery container first so the name is free.
8. **Reconcile**: `RunProcedure podhaus-push-deploy` from bandicoot. It
   pulls both trees, syncs (servers.toml, repos.toml, the `onepassword`
   server change), injects hashes, and deploys: bilby's Caddy and Gatus with
   the new upstreams, both Backrest overlays, `onepassword` on bandicoot.
   Remote Peripheries reconnect through the re-pointed `core-connect`.
   Then kangaroo's Periphery re-point.
9. **Verify** (below). Only then:
10. **Retire on bilby**: `docker rm` the stopped Core/onepassword containers,
    delete the three volumes and `/opt/komodo/keys` (private keys must not
    linger on a non-control node), `docker image rm` komodo-op:local-arm64.

**Rollback** (any point before 10): stop what is on bandicoot, start the
old containers on bilby (`docker start` by name, or `komodo-start` from
bilby's checkout at the pre-move commit), revert the Caddy/Gatus upstreams.
bilby's volumes are untouched until step 10.

### 2c. Verification

- Komodo: every server Ok (`ListServers`), including `podhaus` outbound and
  `bandicoot`; `ListStacks` all running; `onepassword` healthy on bandicoot
  and `OP__KOMODO__*` variables still refreshing (komodo-op log).
- A trivial push to podhaus deploys through the GitHub webhook (GitHub's
  recent-deliveries page shows 200); `./komodo-sync` from bandicoot's
  checkout overlays and syncs; `fenwick-push-deploy` still builds on bilby
  (until step 3).
- Gatus: all 17 Komodo-backed checks green; "Komodo" and "Komodo Alerts"
  green; Backrest (bilby, bandicoot) green.
- Ansible from bandicoot: `playbooks/bandicoot.yml` and `playbooks/bilby.yml`
  `--check --diff` clean and second run `changed=0`. Terraform from
  bandicoot: `plan` shows no diff.
- Core's nightly backup lands in bandicoot's `/opt/komodo/backups`;
  Backrest's `komodo` and `onepassword` plans run from bandicoot.
- bilby: no komodo-core/postgres/ferretdb/op-connect containers; no
  `/opt/komodo/keys`; disk and RAM re-measured.

---

## Step 3 — Fenwick family to bandicoot

After step 2: the bot reaches `op-connect-api` by dockernet name, which now
exists only on bandicoot.

| Where | Change |
|---|---|
| `ansible/inventory/host_vars/bandicoot.yml` | `podhaus_extra_networks` (fenwick-net, fenwick-webagent-net, bilby's labels); `/mnt/pouch` root sentinel already exists; run `--tags docker`. Remove from bilby's host_vars after the move (networks removed by hand on bilby: the role only creates) |
| `komodo/sync/repos.toml` | Repo `fenwick` → `server = "bandicoot"` (fresh clone on bandicoot's Periphery; the Forgejo token comes from Core's central git_providers, and `git.pod.haus` resolves via the Periphery's `extra_hosts` from step 2) |
| fenwick repo: `stack.toml`, `brinno-downloader/stack.toml`, `web-agent/stack.toml` | `server = "bandicoot"`; tags `bilby` → `bandicoot`; comments |
| fenwick `compose.yaml` | bot publishes `8088:8088` (bilby's Caddy `@fenwick`, `fenwick-events.pod.haus:4444`, and Gatus reach it); `OTEL_EXPORTER_OTLP_ENDPOINT` back to `http://clickstack-otel:4318` (same dockernet again); `mem_limit: 1g` on the bot (peak 642 MB); comment fixes ("on bilby") |
| fenwick `brinno-downloader/stack.toml` | `BRINNO_GATUS_HEARTBEAT_URL=http://10.0.0.119:8080/...` (Gatus's LAN-published port, as ClickStack's mongo-dump uses) |
| Bugsink | stays on bilby (pets uses it). Its DSN names `bugsink:8000` on dockernet; from bandicoot the bot needs a LAN path: `bugsink/compose.yaml` publishes `8000` on bilby and `ALLOWED_HOSTS` gains `10.0.0.119`; the 1Password item `Bugsink Fenwick DSN` credential becomes `http://<key>@10.0.0.119:8000/1` (edited with the dev service account; komodo-op re-syncs within a minute). This is the published-LAN-port pattern every other cross-host hop uses — the alternative, an unauthenticated public Pomerium ingest route on `bugs.pod.haus`, is a new exposure class and is not taken |
| `caddy/Caddyfile` | `@fenwick` and `fenwick-events.pod.haus:4444` → `10.0.0.90:8088` |
| `gatus/conf/config.yaml` | `http://fenwick:8088/health` and the `/events/async` alert URL → `10.0.0.90:8088` |
| Backrest | `/var/lib/fenwick`, `/var/lib/signal-cli` binds + plan `fenwick` → `backup/bandicoot`; out of `backup/bilby` |
| Logging | bandicoot's Alloy must drop the bot's stdout as bilby's does (the bot self-reports OTLP); confirm `parsers.fenwick` is in bandicoot's chain |
| Docs | fenwick `docs/networking.html` ("pre-created on bilby"), `AGENTS.md`; podhaus `docs/hosts.html`, `docs/monitoring.html` |

**Sequence.** Networks first (host_vars + `--tags docker` on bandicoot).
Commit the podhaus changes and the fenwick changes; push podhaus first
(Caddy/Gatus now point at an empty 8088 — brief red, approved; the `fenwick`
Repo re-homes). Stop the four containers on bilby by name (signal-cli last
stopped, first copied: **one Signal registration only**); rsync
`/var/lib/fenwick`, `/var/lib/signal-cli`, `/var/lib/brinno-downloader`
(25 MB) to bandicoot; push fenwick `main` → CI on the bandicoot runner →
`deploy` advances → `fenwick-push-deploy` clones on bandicoot, builds the
three images there (the first build is a cold cache) and brings the family
up. Edit the Bugsink DSN item and redeploy `bugsink` (its compose changed)
in the podhaus push. Then `docker rm` the four on bilby, remove its two
fenwick networks and the `fenwick:local` / brinno / web-agent images, delete
the three state dirs; drop `podhaus_extra_networks` from bilby's host_vars.

**Verify.** The bot answers on Signal and its web UI loads through
`fenwick.pod.haus`; a Gatus alert test reaches Signal (the `/events/async`
path); an email tool call succeeds (Connect reachable); a Bugsink event from
the bot appears in `bugs.pod.haus`; `timelapse_brinno` heartbeat arrives;
web-agent healthy; Gatus "Fenwick" checks green; traces in HyperDX with
`ServiceName = fenwick` after the move; bandicoot RAM re-measured; bilby's
container list has no fenwick-*, signal-cli or brinno.

---

## Step 4 — Fold in and delete this plan

`docs/hosts.html`, `docs/monitoring.html`, `docs/komodo.html`,
`docs/host-provisioning.md`, `docs/disaster-recovery.html` state the new
layout; the "What was done" ledger below is folded into them and this file
is deleted.

---

## Decisions that are Nathan's

| Decision | Recommendation | Trade-off |
|---|---|---|
| **Control-plane front door, stage 2** — move `komodo.pod.haus` (family route + the public `/listener/github` route) onto bandicoot's own relay (`bandicoot_http`, port 8447) with `komodo.pod.haus` and `core-connect.pod.haus` sites in bandicoot's Caddy; `core-connect.pod.haus` becomes a public **unauthenticated websocket** Pomerium route (prefix `/ws/periphery`, `allow_websockets`, `idle_timeout: 0s`) and its DNS moves from the relay address to Pomerium's | Do it after stage 1 has been stable for a while: it is what makes the control plane survive bilby | New route class (public websocket to Core; the Noise handshake remains the real boundary); Periphery connections traverse Pomerium, so a Pomerium restart drops and reconnects every remote Periphery. Terraform (`services_pod_haus.tf`, Pomerium config), `caddy/bandicoot`, bilby Caddyfile cleanup |
| Rename Komodo server `podhaus` → `bilby` | Later, as its own change | 25 stack.toml files, Gatus bodies, repos.toml, docs; no functional gain now |
| bilby `docker system prune` (build cache) | Nathan's call | Next fenwick/pets push rebuilds instead of no-op |
| GNOME on bandicoot | **Decided: keep** | Reserve RAM lever only |
| Bugsink reachability | Applied: LAN-published port on bilby (existing pattern) | Say so if you want the Pomerium ingest route instead |

## Risks

- **USB NIC on bandicoot** is now the control plane's only link; the
  autosuspend exemption and the UniFi reservation are the mitigations, and
  the stage-1 front door on bilby means a bandicoot outage takes deploys
  and Connect down but not ingress.
- **Cold bootstrap on bandicoot** (`komodo-start` on an empty DB) is
  reasoned through, not rehearsed. Follow-up: rehearse it on a throwaway
  Core project.
- **Fenwick image builds on bandicoot** start from a cold layer cache; the
  first `fenwick-push-deploy` is slow, not broken.
- **RAM** on bandicoot in the worst-case coincidence exceeds physical
  memory (above); swap absorbs it, `mem_limit`s bound it, GNOME is the
  reserve.

## What was done

- ✅ NAS path: `storage_binds` renders the NFS fstab entries and installs the
  client; bilby adopted its hand-written lines (`changed=0` after); bandicoot
  mounts Jump and Pouch with sentinels, tripwire and the recovery timer.
  `ofelia/bandicoot` runs. (8e7909b)
- ✅ Runner: `bandicoot` registered idle in Forgejo; fractal's runner torn
  down and deregistered; fractal runs docs/caddy/relay/logging/autoheal/
  Periphery only. (2534886) Proven by fenwick CI run 26 on the bandicoot
  runner.
- ✅ ClickStack on bandicoot: 830 M rows carried over by a stopped-state
  rsync; fresh rows from every host within minutes; `watch.pod.haus` and
  `logs-ingest.pod.haus` proxied from bilby; Gatus heartbeats query
  `10.0.0.90:8123`; Ofelia registered the mongo-dump job. bilby's pre-move
  copy and the stack's images were deleted after verification (bilby disk
  79% → 61%). (7c90fa7)
- ✅ `backup/bandicoot`: restic repo on `/mnt/jump/backups-bandicoot`,
  the mongo dumps as its first plan, Gatus heartbeat and container probe;
  container healthy, Gatus green. (0bc718e)
- ✅ Paperless re-homed to bandicoot (44b34cc) and verified — superseded by
  Nathan's decision to keep it on bilby; step 1 reverses it.
- ✅ Step 1: Paperless moved back to bilby (1b1bbc8), the reverse of
  44b34cc. State (95 MB pgdata, 87 MB data) rsynced from bandicoot before
  the containers there were removed. Verified: document count unchanged
  at 1118 after the move; `paperless.pod.haus` serves a 302 to login;
  Gatus "Paperless" green again once the deploy landed; bilby's Backrest
  config lists the `paperless` plan; bandicoot's Ansible `--tags storage`
  ran clean (check, apply and a third confirmation run all `changed=0`).
  bandicoot's six paperless containers and the paperless-ngx/tika/
  gotenberg/redis/postgres images (nothing else on bandicoot used them)
  were removed after verification.
- ✅ Step 2: Komodo Core, Postgres, FerretDB and the `onepassword` stack
  (op-connect-api, op-connect-sync, komodo-op) moved from bilby to
  bandicoot (432c350, 3ad7e29). bilby's Periphery is now outbound
  (`bilby/periphery/compose.yaml`, bootstrap-managed); bandicoot is the
  Ansible/Terraform control node. State carried over by root rsync
  (postgres-data, ferretdb-state and op-connect-data volumes; the
  17-file `/opt/komodo/keys`); downtime ran from stopping bilby's
  containers to Core answering healthy on bandicoot on the copied
  database. Verified: all 7 Komodo servers report Ok (including
  kangaroo, re-pointed from bilby via its own admitted key); all 50
  stacks running except the one-shot `nathanbaxter-deploy`; 24 Gatus
  checks naming Komodo or Backrest all green; `komodo-op`'s sync log
  shows 195 variables unchanged with 0 errors; `playbooks/bandicoot.yml`
  ran clean (check and a real run both `changed=0`); Terraform `plan`
  exit code 0 (no diff). bilby's old Core/onepassword containers,
  volumes, local `komodo-op` image, `/opt/komodo/keys` and
  `/opt/komodo/backups` were removed once verification was green
  (bilby: 91G/160G disk used, 698 MB free RAM of 15.7 GB with 9.9 GB in
  buff/cache). `playbooks/bilby.yml --check --diff` came back clean
  (changed=0) but the real run was deliberately deferred — Plex was
  streaming live on bilby at cutover time — as was `./komodo-sync`,
  since it also touches the unrelated fenwick/pets procedures; both are
  a follow-up.
- Interim: the bot's telemetry export was re-pointed at `10.0.0.90:4318`
  (fenwick 46fdc1f) because the collector left bilby's dockernet; step 3
  puts it back on the dockernet name.
- Not done, deliberately: bilby's `docker system prune` (Nathan's call,
  above).
- ✅ Step 3: the Fenwick family (bot, signal-cli-rest-api,
  brinno-downloader, fenwick-web-agent) moved from bilby to bandicoot
  (podhaus 77caca3, 57b571b; fenwick 97d7d2d). Caddy and Gatus on bilby
  now reach the bot over the LAN (`10.0.0.90:8088`) instead of a
  dockernet name; Bugsink gained a published LAN port (`10.0.0.119:8000`)
  and its Fenwick DSN item was updated to match; the bot's OTLP export
  moved back to the `clickstack-otel` dockernet name now that both it and
  the bot live on bandicoot; Backrest's fenwick/signal-cli binds and plan
  moved from `backup/bilby` to `backup/bandicoot`; bandicoot's Alloy
  gained the `parsers/fenwick.alloy` module that drops the bot's own
  stdout (it self-reports OTLP instead). State (`/var/lib/fenwick`,
  `/var/lib/signal-cli`, `/var/lib/brinno-downloader`, 25 MB) moved by a
  root rsync, verified byte-identical on both hosts before the source was
  removed. One gap found and fixed along the way: re-homing the `fenwick`
  Komodo Repo resource to a Periphery that had never cloned it before
  broke the push-to-deploy pull stage (it can only pull an existing
  clone) — fixed with a one-time `CloneRepo` call before re-running the
  deploy; see the loose thread in this step's report for future re-homes.
  Verified: the bot answers on Signal and its web UI loads through
  `fenwick.pod.haus` (302); a Gatus alert reached Signal; an email tool
  call succeeded (op-connect-api reachable on bandicoot's dockernet, 200
  on `/heartbeat`); a Bugsink event from the bot reached `bugs.pod.haus`
  (LAN path, 302); Gatus "Fenwick" and "Signal Delivery (Fenwick)" are
  green; 127 ClickStack trace rows for `ServiceName=fenwick` in the prior
  20 minutes; brinno-downloader's Firebase/MCS reconcile loop runs
  normally; bilby's container, network, image and state-directory
  footprint for all four services is gone. Not independently confirmed:
  a fresh `timelapse_brinno` heartbeat push since the move (last one seen
  was from the day before, within the plan's tolerance but not a new
  sample) and an explicit "digest scheduling" log line (other operation
  evidence is strong). bilby's host_vars no longer declares
  `podhaus_extra_networks` (57b571b); `--tags docker` came back
  `changed=0`. A `--check --diff` of the full `playbooks/bilby.yml`
  (the run deferred in step 2 for live Plex streaming) came back clean —
  `changed=0` on all 47 tasks, including the docker-daemon and firewalld
  tasks — but the real run is still pending: it was blocked by this
  session's own safety controls as too broad an action to run
  unsupervised, not by anything in the check output. Nathan or a future
  session should run `cd ansible && op-vault dev -- pipenv run
  ansible-playbook playbooks/bilby.yml`, expecting `changed=0` throughout
  given the check result above.
