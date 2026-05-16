# Platform stacks — logging, autoheal, backup, scheduling

The four multi-host shared services that pinelake joins as a per-host
overlay. Pattern matches what bilby + kangaroo already do — see
[Stack conventions](/stack-conventions.html). Per-host directories
under each shared stack, `compose.shared.yaml` unchanged, only the
overlay differs.

User decision context: **logs ship to bilby's ClickStack collector
centrally; autoheal, backup, and cron all live on pinelake.**

Depends on: [Host bootstrap](host-bootstrap.md).

## Logging — Alloy → bilby's ClickStack collector (cross-LAN OTLP)

Each host runs its own Alloy collector tailing Docker container logs,
shaping them through a per-service parser chain, and shipping **OTLP**
to bilby's ClickStack collector. VictoriaLogs + Grafana were
decommissioned when ClickStack (ClickHouse + HyperDX UI at
`watch.pod.haus` + bundled OTel collector + MongoDB) replaced them —
see [clickstack-migration](/plans/clickstack-migration/). pinelake is a
non-bilby host, so it ships cross-LAN to bilby's published OTLP/HTTP
endpoint at `http://10.0.0.119:4318` authed with a HyperDX ingestion
key — exactly the kangaroo pattern.

### Files

```
logging/
├── compose.shared.yaml          # already exists; Alloy image + Docker
│                                # socket mount; OTLP→ClickStack sink
├── bilby/
│   ├── alloy-conf/
│   │   ├── config.alloy         # ships in-network to clickstack-otel:4318
│   │   └── parsers/             # per-service parser modules
│   └── ...
├── kangaroo/
│   ├── alloy-conf/
│   │   ├── config.alloy         # cross-LAN OTLP to 10.0.0.119:4318
│   │   └── parsers/             # alloy, autoheal, backrest, …
│   └── ...
└── pinelake/                    # NEW
    ├── stack.toml
    ├── compose.yaml             # include: [../compose.shared.yaml]
    └── alloy-conf/
        ├── config.alloy
        └── parsers/             # per-service parsers, config-as-code
```

### `logging/pinelake/alloy-conf/config.alloy`

Mirror `logging/kangaroo/alloy-conf/config.alloy` exactly, swapping
only the host label. That config is the canonical cross-LAN reference:
docker discovery → `loki.process "containers"` (ANSI strip) →
per-service parser chain (`parsers/<service>.alloy`, config-as-code) →
`otelcol.receiver.loki` Loki→OTLP bridge → `otelcol.processor.transform`
enrich (`service.name` from container, severity from level token) →
`otelcol.processor.batch` → `otelcol.exporter.otlphttp` to bilby's
published collector.

The relevant differences from kangaroo:

```alloy
loki.source.docker "containers" {
  host          = "unix:///var/run/docker.sock"
  targets       = discovery.relabel.container_logs.output
  forward_to    = [loki.process.containers.receiver]
  relabel_rules = discovery.relabel.container_logs.rules
  labels        = {"host" = "pinelake"}
}

// ... per-service parser chain over pinelake's own container set ...

otelcol.exporter.otlphttp "clickstack" {
  client {
    endpoint = "http://10.0.0.119:4318"   // bilby's published OTLP/HTTP
    headers  = {
      // HyperDX ingestion API key (same key as bilby + kangaroo;
      // injected via logging/pinelake/stack.toml ← 1Password). Empty
      // ⇒ 401 ⇒ no data — loud failure, no silent fallback.
      "authorization" = sys.env("CLICKSTACK_INGESTION_KEY"),
    }
  }
}
```

Endpoint: `http://10.0.0.119:4318` — bilby's published OTLP/HTTP port,
reached cross-LAN. LAN-only, plaintext — same trust posture as the
old cross-LAN `:9428` VL push, just OTLP now. **Not** the
Cloudflare-fronted `watch.pod.haus` (HyperDX UI only; the collector
ingest port is not behind CF).

Per-service parsers live under `logging/pinelake/alloy-conf/parsers/`
as config-as-code — add one `parsers/<service>.alloy` module per
pinelake container that needs shaping (flood, plex, syncthing, …) and
wire it into the parser chain in `config.alloy`, mirroring how
kangaroo chains `parsers.komodo_periphery → parsers.alloy → …`.

> **Inherited known issue — cross-LAN exporter reliability.** pinelake
> uses the same cross-LAN `otelcol.exporter.otlphttp` pattern as
> kangaroo, so it inherits the open follow-up: kangaroo's exporter has
> been observed to silently stop shipping and not self-recover after
> the bilby collector is disrupted (e.g. a `clickstack` redeploy), with
> the container still reporting `healthy` because the healthcheck only
> probes Alloy's `:12345` TCP port. See the
> [ingestion-pipeline known issue](/plans/clickstack-migration/ingestion-pipeline.md).
> Whatever guard lands there (exporter `retry_on_failure`/`sending_queue`
> tuning, a periodic alloy self-restart, or a metrics-based autoheal /
> Gatus heartbeat) should be applied to pinelake's overlay too.

### `logging/pinelake/stack.toml`

Mirror `logging/kangaroo/stack.toml`:

```toml
[[stack]]
name = "pinelake-logging"
description = "Alloy on pinelake — ships container logs to bilby's ClickStack collector (cross-LAN OTLP)"
tags = ["pinelake", "podhaus"]
deploy = true

[stack.config]
server = "pinelake"
linked_repo = "podhaus"
run_directory = "logging/pinelake"
file_paths = ["compose.yaml", "../compose.shared.yaml"]

environment = """
TZ=[[TZ]]
CLICKSTACK_INGESTION_KEY=[[OP__KOMODO__CLICKSTACK_INGESTION_KEY__CREDENTIAL]]
"""
```

The `CLICKSTACK_INGESTION_KEY` is the HyperDX ingestion key, the same
secret kangaroo + bilby use — already in 1Password, synced as the
`OP__KOMODO__CLICKSTACK_INGESTION_KEY__CREDENTIAL` Komodo Variable, no
new secret to create.

### `logging/pinelake/compose.yaml`

```yaml
include:
  - ../compose.shared.yaml

services:
  alloy:
    container_name: alloy
    volumes:
      - ./alloy-conf:/etc/alloy:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - /Users/baxter/.colima/default/docker.sock:/var/run/docker.sock:ro  # if shared rootless
```

Bind the **`alloy-conf` directory** (not a single `config.alloy`
file) — `config.alloy` does `import.file "parsers" { filename =
"/etc/alloy/parsers" }`, so the whole directory plus the
`parsers/` subdir must be mounted, and a directory bind avoids the
single-file inode pin. Pick **one** docker-socket bind (the one the
colima daemon actually exposes — confirm with `docker context inspect
colima`); `compose.shared.yaml` already mounts the socket, so the
override may be unnecessary — verify by reading `compose.shared.yaml`
during implementation.

### Verification

After deploy, in bilby's HyperDX UI at `watch.pod.haus`:
- A `host='pinelake'` filter returns log lines
- `service.name='flood'` (after Flood migration) shows up
- `service.name='plex'` (after Plex migration) shows up

If nothing arrives within a minute of restart, check Alloy logs for
connection-refused (cross-LAN routing to `10.0.0.119:4318` blocked) or
`401 Unauthorized` (missing/wrong `CLICKSTACK_INGESTION_KEY`).

### Bilby-side change (if any)

None expected — the ClickStack collector accepts any OTLP source
presenting a valid HyperDX ingestion key; there is no per-host
allowlist (kangaroo just ships cross-LAN with the same key and it
works). Verify pinelake's LAN can reach `10.0.0.119:4318`.

## Autoheal — local on pinelake

Each host runs its own `willfarrell/autoheal`, watching the local
Docker daemon, restarting unhealthy containers labelled
`autoheal: "true"`. Trivial per-host overlay.

### Files

```
autoheal/
├── compose.shared.yaml          # already exists
├── bilby/stack.toml
├── kangaroo/stack.toml
└── pinelake/                    # NEW
    ├── stack.toml
    └── compose.yaml             # include: [../compose.shared.yaml]
```

### `autoheal/pinelake/compose.yaml`

```yaml
include:
  - ../compose.shared.yaml

services:
  autoheal:
    container_name: autoheal
    restart: unless-stopped
    environment:
      AUTOHEAL_CONTAINER_LABEL: autoheal
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
```

### `autoheal/pinelake/stack.toml`

```toml
[stack]
server = "pinelake"
linked_repo = "podhaus"
run_directory = "/etc/komodo/repos/podhaus/autoheal/pinelake"
```

### Verification

After deploy:
- `docker ps` shows `autoheal` container, no published ports
- Force a healthcheck failure (e.g. `docker exec flood pkill -STOP
  -f rtorrent`) and confirm autoheal restarts it within ~3 minutes
  (3 failed checks × 60 s interval)
- Then `docker exec flood pkill -CONT …` to recover gracefully if
  the kill didn't take effect

## Backup — Backrest on pinelake, local restic repo + OneDrive mirror

Pinelake hosts its own Backrest instance backing up to a local restic
repo on the TerraMaster volume, then bilby's existing rclone
OneDrive-mirror hook syncs that repo offsite.

Mirrors kangaroo's pattern but with a different repo location and
different 1Password secret items.

### Repo location decision

Open question #10 in the index. Options:

1. **On TerraMaster** (`/Volumes/TerraMaster/_backups/pinelake-restic/`)
   — local, fast, **but co-located with the data it's backing up**.
   If TerraMaster fails, the backup is also gone. The OneDrive mirror
   is what makes this safe.
2. **Internal NVMe** (`/Users/baxter/restic/`) — separate disk from
   TerraMaster, ~610 GiB free. **Recommended**: separates failure
   domains.
3. **Over the network to bilby's Jump** — would require an NFS/SMB
   mount from pinelake to QNAP. Not currently routable from
   pinelake's `192.168.1.0/24` LAN.

Default: option 2 (internal NVMe). The OneDrive mirror provides the
off-site copy.

### Files

```
backup/
├── compose.shared.yaml          # already exists; Backrest container + init
├── bilby/stack.toml
├── kangaroo/stack.toml
└── pinelake/                    # NEW
    ├── stack.toml
    └── compose.yaml             # include: [../compose.shared.yaml]
```

### `backup/pinelake/stack.toml`

```toml
[stack]
server = "pinelake"
linked_repo = "podhaus"
run_directory = "/etc/komodo/repos/podhaus/backup/pinelake"

[stack.environment]
HOST_NAME                = "pinelake"
RESTIC_REPO_PATH         = "/Users/baxter/restic/pinelake"
RESTIC_REPO_PASSWORD     = "[[OP__KOMODO__RESTIC_REPO_PINELAKE_PASSWORD__CREDENTIAL]]"
GATUS_PUSH_TOKEN         = "[[OP__KOMODO__GATUS_BACKREST_PINELAKE_PUSH_TOKEN__CREDENTIAL]]"
```

New 1Password items needed:

- `Restic Repo password (pinelake)` — generate fresh; store
  `CREDENTIAL` field.
- `Gatus Backrest pinelake push token` — generate fresh; store
  `CREDENTIAL` field.

Both surface automatically as Komodo Variables via `komodo-op`.

### `backup/pinelake/compose.yaml`

```yaml
include:
  - ../compose.shared.yaml

services:
  backrest:
    container_name: backrest
    volumes:
      - /Users/baxter/restic:/repos
      - /Users/baxter/.config/torrent:/sources/flood:ro
      - /Users/baxter/Library/Application Support/Syncthing:/sources/syncthing:ro
      - /Users/baxter/Library/Application Support/Plex Media Server:/sources/plex:ro
      - /etc/cloudflared:/sources/cloudflared:ro
      - /Users/baxter/Library/Preferences/com.plexapp.plexmediaserver.plist:/sources/plex/com.plexapp.plexmediaserver.plist:ro
      # NOTE: above is a single-file bind, which IS allowed for read-only
      # sources we don't expect to be rewritten. If concerned, bind the
      # parent ~/Library/Preferences/ and use --include.
```

The hard rule against single-file binds applies to **configs the
running service re-reads after startup**. A backup source is read once
per snapshot; if the plist is renamed-rewritten, the next backup pass
re-resolves the path. Less risky than a service config bind. Still,
preferred form: bind the parent directory and let restic include only
the needed file.

### Backrest plans

Match bilby's stagger: 04:00 AWST, with offsets per stack.

| Plan | Source path inside container | Schedule | Retention |
|---|---|---|---|
| `flood-pinelake` | `/sources/flood/` (excl. `*.session`, `.tmp`) | 04:00 daily | 14/4/6 |
| `syncthing-pinelake` | `/sources/syncthing/` (excl. `syncthing.log*`) | 04:10 daily | 14/4/6 |
| `plex-pinelake` | `/sources/plex/{Plug-in Support/Databases,Plug-in Support/Preferences,Plug-in Support/Data,Plug-in Support/Caches,Preferences.xml,com.plexapp.plexmediaserver.plist}` | 04:20 daily | 14/4/6 |
| `cloudflared-pinelake` | `/sources/cloudflared/` (config + tunnel JSON) | 04:30 daily | 14/4/6 |
| `backrest-state` | `/var/lib/backrest/` (the Backrest config + index) | 04:40 daily | 14/4/6 |

Weekly prune + check on Sunday 05:00 (well after the 04:30 dead-time
window per [user prefs on scheduling](/scheduling.html)).

**Plex media excluded** — 1.4 GB `Metadata/` + 20 GB `Media/` are
regenerable and not worth ~1 GB/day of restic delta.

**Torrent data excluded** — 1.2 TB on TerraMaster, replaceable by
re-downloading.

### Rclone OneDrive mirror

Bilby's `backrest-state` plan has a hook on
`CONDITION_SNAPSHOT_SUCCESS` that triggers an rclone push of the
restic repos to OneDrive. For pinelake, two options:

1. **Mirror pinelake's repo from pinelake itself** — needs rclone +
   OneDrive token on pinelake. Adds setup but contains failure
   domain.
2. **Mirror pinelake's repo via bilby** — bilby would need to pull
   pinelake's repo over the tailnet first. Adds an extra hop and
   makes bilby a dependency for pinelake's offsite.

Default: option 1. Add an rclone OneDrive remote configured on
pinelake, drive it from a `backrest-state` `CONDITION_SNAPSHOT_SUCCESS`
hook locally. New 1Password item: `rclone OneDrive token (pinelake)`,
multi-line OAuth blob — seeded host-side by `komodo-start` (matches
how bilby handles it).

### Gatus push heartbeat

Each backup plan emits a `CONDITION_SNAPSHOT_SUCCESS` / `_FAILURE`
hook to a Gatus push endpoint with the `GATUS_PUSH_TOKEN`. New Gatus
config entries:

```yaml
- name: backrest-pinelake-flood
  group: backup-pinelake
  conditions:
    - "[BODY].success == true"
  alerts:
    - type: email
      conditions: ["[BODY].success == false"]
```

(Five entries, one per plan.) See [Monitoring](monitoring.md).

## Scheduling — ofelia on pinelake

Bilby already has an ofelia stack for host-side cron-style jobs.
Pinelake gets its own local ofelia. Same overlay pattern as the
others.

### What cron does pinelake need?

Inventory:

| Job | Why | Frequency |
|---|---|---|
| Plex DB optimise | `PRAGMA optimize` on library.db; mitigates the bilby butler timezone incident pattern | weekly, 04:50 AWST Sun |
| Plex `Cache` cleanup | macOS Plex didn't need this; container's Cache/ can grow | monthly |
| rtorrent session backup | `.session/` is small; nice to have a parallel snapshot outside restic | daily |
| Cloudflared health probe | external curl from inside the host's docker network to each `*.pinelake.haus` and log mismatches | every 5 min |

Most are nice-to-have, not strictly required. Start with Plex DB
optimise as the only ofelia job; add more as needed.

### Files

```
scheduling/
├── compose.shared.yaml          # already exists; ofelia image + Docker
│                                # label-discovery
└── pinelake/                    # NEW
    ├── stack.toml
    └── compose.yaml
```

### `scheduling/pinelake/compose.yaml`

```yaml
include:
  - ../compose.shared.yaml

services:
  ofelia:
    container_name: ofelia
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
```

Ofelia discovers jobs from container **labels** rather than a config
file, so most of the per-host config lives on the target container.
The Plex DB optimise job, for instance, is a label on the Plex
container itself:

```yaml
labels:
  autoheal: "true"
  ofelia.enabled: "true"
  ofelia.job-exec.plex-db-optimize.schedule: "0 50 4 * * 0"   # Sun 04:50
  ofelia.job-exec.plex-db-optimize.command: >
    sqlite3 /config/Library/Application\ Support/Plex\ Media\ Server/Plug-in\ Support/Databases/com.plexapp.plugins.library.db
    "PRAGMA optimize;"
```

That label goes in `plex/pinelake/compose.yaml`, not in the
scheduling stack. The scheduling stack just runs ofelia; ofelia
discovers labels.

## Cross-cutting: 1Password Homelab vault entries

Summary of new items required across all four stacks:

| Item name | Field | Used by |
|---|---|---|
| `Restic Repo password (pinelake)` | `CREDENTIAL` | Backrest |
| `Gatus Backrest pinelake push token` | `CREDENTIAL` | Backrest + Gatus |
| `rclone OneDrive token (pinelake)` | multi-line OAuth blob | rclone (seeded by komodo-start) |
| `Plex Token (pinelake)` | `CREDENTIAL` | Plex Preferences init |
| `Komodo Periphery (pinelake)` | `CREDENTIAL` or `PRIVATE_KEY` | host-bootstrap |

## Deploy order

1. Logging — first, so subsequent deploys' logs are visible centrally
2. Autoheal — second, so subsequent deploys' healthchecks self-recover
3. Backup — before any of the service stacks deploy, so initial-state
   snapshots happen before stacks start mutating state. **Critical**:
   take a baseline snapshot of each source before its stack flips.
4. Scheduling — last; needs target containers to exist for ofelia
   labels to be discovered

## Acceptance criteria

- HyperDX at `watch.pod.haus` shows `host='pinelake'` log lines
- `docker ps` on pinelake shows: alloy, autoheal, backrest, ofelia
- Backrest UI (via bilby tunnel, no need for a pinelake-specific
  hostname) shows 5 plans, all green after first scheduled run
- Restic repo present at `/Users/baxter/restic/pinelake/` with
  snapshots
- OneDrive mirror destination shows pinelake repo synced
- Gatus shows 5 new backup heartbeats under the `backup-pinelake`
  group, all green
- Plex DB optimise label discovered by ofelia (`docker logs ofelia`
  shows `Loaded plex-db-optimize`)

## Open items deferred

- Whether `backrest` UI needs its own `backrest.pinelake.haus` ingress
  or whether bilby's `backrest.pod.haus` can connect to remote repos.
  Default: no separate ingress; manage via bilby's UI if it supports
  remote repos, or SSH-tunnel to pinelake's port.
- Whether to converge on a single shared `compose.shared.yaml` for
  Backrest that supports any host (currently is shared) — verify
  during implementation that the pinelake overlay is small.
- Whether to add additional ofelia jobs beyond Plex DB optimise. Add
  as need surfaces.
