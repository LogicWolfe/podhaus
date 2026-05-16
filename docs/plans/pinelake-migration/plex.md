# Plex migration

The highest-risk stream. Plex on pinelake is the **native macOS app**,
not a container — and unlike bilby (where Plex was already
containerised and the migration was filesystem-to-filesystem), pinelake
requires translating macOS preferences (`.plist`) into the container
format (`Preferences.xml`), with the `PlexOnlineToken` and
`MachineIdentifier` intact, before the container can be allowed to
start.

Get this wrong and the server either claims a new
`MachineIdentifier` (clients re-pair, watch history orphaned in the
cloud), or loses access to Plex Pass features (token rotation), or
re-scans 1.1 TB of media (cold thumbnails, intros lost). The
[Plex runbook](/runbooks/plex.html) and
[Plex maintenance log](/runbooks/plex-maintenance.html) describe the
identity-preservation init-container pattern already used on bilby —
the same pattern applies here.

Depends on: [Host bootstrap](host-bootstrap.md), and **a verified
pre-migration backup**.

## State to preserve

All under `~/Library/Application Support/Plex Media Server/`
(22 GB total):

| Path | Size | Notes |
|---|---|---|
| `Plug-in Support/Databases/com.plexapp.plugins.library.db` | 33 MB | The library. WAL must be checkpointed before copy. |
| `Plug-in Support/Databases/com.plexapp.plugins.library.blobs.db` | 82 MB | Blob store (artwork lookups). |
| `Plug-in Support/Databases/*-2026-05-*` | varies | Plex's own scheduled DB dumps. Useful as a fallback source. |
| `Metadata/Movies/`, `Metadata/TV Shows/` | 1.4 GB | Posters, art, agent payloads. |
| `Media/` | 20 GB | Thumbnails, BIFs, intro detection. Regenerable but expensive. |
| `Plug-in Support/{Preferences,Data,Caches,Metadata Combination}/` | <1 MB | Agent configs, scrobble state. |
| `Codecs/`, `Scanners/`, `Updates/`, `Cache/`, `Logs/` | varies | **Disposable.** Will regenerate. |

Plus the macOS-specific preferences file:

| Path | Size | Notes |
|---|---|---|
| `~/Library/Preferences/com.plexapp.plexmediaserver.plist` | 1.2 KB | **Identity.** Has to be translated to `Preferences.xml`. |

Identity-bearing keys in the plist (token redacted):

```
MachineIdentifier          = c9d75740-0fd3-4bba-9874-be61f5dc8d38
ProcessedMachineIdentifier = 92311858cdd55fb33583fda2e6fc037e3655da85
AnonymousMachineIdentifier = 166ee17f-2122-4dcf-9d5e-38961c51ff25
CertificateUUID            = 5801df40ceea4deaaefd8bd027fc22ff
CertificateVersion         = 3
FriendlyName               = "Pine Lake"
PlexOnlineUsername         = dolabax
PlexOnlineMail             = dolabaxter+plex@gmail.com
PlexOnlineHome             = 1
PublishServerOnPlexOnlineKey = 1
PlexOnlineToken            = <REDACTED — long-lived auth>
AcceptedEULA               = 1
LanguageInCloud            = 1
ScheduledLibraryUpdatesEnabled = 1
FSEventLibraryUpdatesEnabled   = 1
OldestPreviousVersion      = 1.27.2.5929-a806c5905
```

## Library paths and the `/Volumes/TerraMaster` decision

All library sections root in `/Volumes/TerraMaster`:

| Section | Roots |
|---|---|
| Films | `/Volumes/TerraMaster/Movies`, `/Volumes/TerraMaster/Torrents/Movies` |
| TV shows | `/Volumes/TerraMaster/TV`, `/Volumes/TerraMaster/Kids/TV`, `/Volumes/TerraMaster/Torrents/TV` |
| Sports | `/Volumes/TerraMaster/Sports`, `/Volumes/TerraMaster/Torrents/Sports` |

The library DB records absolute paths. **Rewriting library paths in
the DB is the most common Plex-migration footgun.** Two options:

1. **Mount media at the same path in the container.** Bind
   `/Volumes/TerraMaster` to `/Volumes/TerraMaster` inside the
   container. Library DB references match. No DB surgery needed.
   This is the recommended path.

2. **Rewrite paths.** Update `section_locations.root_path` rows
   pre-cutover. Higher risk — every mismatch results in a section
   showing as "unavailable" until the path resolves. Avoid.

Option 1 wins. The compose bind-mount becomes:

```yaml
volumes:
  - /Volumes/TerraMaster:/Volumes/TerraMaster:ro,delegated
```

`ro,delegated` is the right choice: Plex doesn't write to the media
roots, and `delegated` is the macOS virtiofs/osxfs flag that gives
the best read performance for large directories. (Confirm whether
this flag is supported by colima's virtiofs — it should be a no-op
hint if unsupported, not an error.)

## Plist → Preferences.xml translation

The Docker Plex image (`plexinc/pms-docker`) expects state at:

```
<container>/config/Library/Application Support/Plex Media Server/
  ├── Preferences.xml
  ├── Plug-in Support/
  ├── Metadata/
  └── Media/
```

The macOS native app stores prefs in
`~/Library/Preferences/com.plexapp.plexmediaserver.plist` (binary
plist), and everything else in
`~/Library/Application Support/Plex Media Server/`. Translation
required for the plist; everything else is a directory move.

### Translation: plist → XML

`<dict>` keys in the plist become attributes on the root
`<Preferences>` element. Plex publishes this mapping in their forum
guidance for "Move install between platforms"; the gist:

```xml
<?xml version="1.0" encoding="utf-8"?>
<Preferences
  MachineIdentifier="c9d75740-0fd3-4bba-9874-be61f5dc8d38"
  ProcessedMachineIdentifier="92311858cdd55fb33583fda2e6fc037e3655da85"
  AnonymousMachineIdentifier="166ee17f-2122-4dcf-9d5e-38961c51ff25"
  CertificateUUID="5801df40ceea4deaaefd8bd027fc22ff"
  CertificateVersion="3"
  FriendlyName="Pine Lake"
  PlexOnlineUsername="dolabax"
  PlexOnlineMail="dolabaxter+plex@gmail.com"
  PlexOnlineHome="1"
  PublishServerOnPlexOnlineKey="1"
  PlexOnlineToken="REDACTED"
  AcceptedEULA="1"
  LanguageInCloud="1"
  ScheduledLibraryUpdatesEnabled="1"
  FSEventLibraryUpdatesEnabled="0"
  ButlerStartHour="2"
  ButlerEndHour="5"
  OldestPreviousVersion="1.27.2.5929-a806c5905"
/>
```

Notes on the translation:

- `FSEventLibraryUpdatesEnabled` — macOS-specific (FSEvents). Set to
  `0` for Linux container; the container uses inotify and Plex
  auto-detects. Forcing `1` in the container can produce noisy
  warnings.
- `ButlerStartHour` / `ButlerEndHour` — the macOS plist doesn't have
  these set (Plex uses defaults of 02:00–05:00 local). Pinning them
  here makes the timezone discipline explicit. Critical: the
  bilby plex butler-timezone incident is a documented past failure
  mode — see [Plex maintenance log](/runbooks/plex-maintenance.html).
  TZ in the container should be `Australia/Perth` (matches AWST).
- `PlexOnlineToken` — long-lived, identity-tied. Should be sourced
  from 1Password (new item: `Plex Token (pinelake)`) and rendered
  into `Preferences.xml` by an init container, **not** committed to
  the repo. Same pattern as bilby's Plex.
- Anything else read out of the plist that's not on this list is
  safe to drop.

### Init container

Bilby's Plex stack has a Preferences init container that:

1. Templates `Preferences.xml` from `Preferences.template.xml` using
   the `OP__KOMODO__PLEX_TOKEN__CREDENTIAL` env var.
2. Validates that the on-disk `Preferences.xml`'s `MachineIdentifier`
   matches the expected value (refuses to start if not).
3. Exits 0 to let the main Plex container start.

Same pattern for pinelake. The expected `MachineIdentifier`
(`c9d75740-…`) is baked into the init container's environment or
template comparison. **Plex never starts without this check passing.**
That guarantees identity preservation even after a half-baked restore.

## Public exposure decision (open question #3 in index)

Today, there's **no `plex.pinelake.haus` ingress.** Plex remote access
is via Plex's own relay (`PublishServerOnPlexOnlineKey=1`). Options:

1. **Keep current.** Plex relay handles remote; LAN clients direct.
   Zero CF change. Simplest. Recommended unless Plex Pass remote
   streaming is unsatisfactory.
2. **Tailscale serve.** Add `tailscale serve --https=443 --bg
   http://localhost:32400` so Plex is reachable at
   `https://pinelake.<tailnet>.ts.net`. Tailnet-only, no public DNS,
   no Access app. Cheap.
3. **Cloudflare tunnel ingress.** Add `plex.pinelake.haus →
   http://172.18.0.1:32400`. Requires a fat-pipe-friendly tunnel
   config (Plex transcoding is bandwidth-heavy through CF). Add a
   `pinelake_service` module entry. Family / Homelab token Access
   policy decision per #5 in the index.

Recommendation: 1 + 2 (Plex relay + tailnet serve). Skip Cloudflare
ingress for Plex unless there's a concrete reason — Plex traffic
through Cloudflare is rarely worth the latency and is a known source
of warnings about excessive non-cacheable bandwidth on free CF zones.

## Compose layout

`plex/pinelake/compose.yaml`:

```yaml
services:
  plex-prefs:
    container_name: plex-prefs
    image: alpine:latest
    user: "501:20"
    restart: "no"
    environment:
      EXPECTED_MACHINE_ID: c9d75740-0fd3-4bba-9874-be61f5dc8d38
      PLEX_TOKEN: ${PLEX_TOKEN}
    volumes:
      - /Users/baxter/Library/Application Support/Plex Media Server:/config
      - ./Preferences.template.xml:/template/Preferences.template.xml:ro
    command:
      - /bin/sh
      - -c
      - |
        set -eu
        target="/config/Preferences.xml"
        if [ -f "$$target" ]; then
          have=$$(grep -oE 'MachineIdentifier="[^"]+"' "$$target" | head -1 | cut -d'"' -f2)
          if [ "$$have" != "$$EXPECTED_MACHINE_ID" ]; then
            echo "REFUSING TO START: expected $$EXPECTED_MACHINE_ID, found $$have"
            exit 1
          fi
        else
          sed "s|__PLEX_TOKEN__|$$PLEX_TOKEN|" /template/Preferences.template.xml > "$$target.tmp"
          mv "$$target.tmp" "$$target"
        fi

  plex:
    container_name: plex
    image: plexinc/pms-docker:latest
    restart: unless-stopped
    network_mode: host
    depends_on:
      plex-prefs:
        condition: service_completed_successfully
    environment:
      TZ: Australia/Perth
      PLEX_CLAIM: ""               # left empty; identity already preserved
      ADVERTISE_IP: "http://192.168.1.128:32400/"
      ALLOWED_NETWORKS: "192.168.1.0/24,100.64.0.0/10"
    volumes:
      - /Users/baxter/Library/Application Support/Plex Media Server:/config
      - /Volumes/TerraMaster:/Volumes/TerraMaster:ro
    labels:
      autoheal: "true"
    healthcheck:
      test: ["CMD-SHELL", "curl -fsS http://127.0.0.1:32400/identity >/dev/null || exit 1"]
      interval: 60s
      timeout: 10s
      retries: 3
      start_period: 120s
```

`plex/pinelake/stack.toml`:

```toml
[stack]
server = "pinelake"
linked_repo = "podhaus"
run_directory = "/etc/komodo/repos/podhaus/plex/pinelake"

[stack.environment]
PLEX_TOKEN = "[[OP__KOMODO__PLEX_TOKEN_PINELAKE__CREDENTIAL]]"
```

The init container's `EXPECTED_MACHINE_ID` is hard-coded as the
documented identity. Sourcing it from a Komodo Variable would be
cleaner but adds a footgun: if the env block ever rendered empty,
the init would accept any identity. Hard-coded is safer.

**`/Volumes/TerraMaster` bind is `:ro`** — Plex doesn't write to
media. Reduces the blast radius of any container bug.

`network_mode: host` matches bilby's Plex — needed for proper
client discovery, DLNA, and avoiding NAT for direct LAN clients.
cloudflared (if/when ingress is added) reaches Plex via
`172.18.0.1:32400` from inside its container.

## Cutover sequence

### Pre-flight

1. **Snapshot.** Step 1 of [Host bootstrap](host-bootstrap.md) covers
   this, but reconfirm: full rsync of
   `~/Library/Application Support/Plex Media Server/` and the plist
   to a destination off pinelake. Verify with sha256 spot-checks.
2. **Save the 1Password Plex token.** Pull it out of the plist via:
   ```
   defaults read com.plexapp.plexmediaserver PlexOnlineToken
   ```
   Store as `Plex Token (pinelake)` in the Homelab vault.
3. **Build the template.** Generate `Preferences.template.xml` from
   the plist values above. Replace the token value with the literal
   string `__PLEX_TOKEN__`. Commit the template to the repo (it
   contains no secrets).
4. **Verify the expected machine ID** matches what's in the existing
   plist by reading
   `defaults read com.plexapp.plexmediaserver MachineIdentifier`.
5. **Schedule cutover during off-hours.** Default 04:00 AWST
   (matches the dead-time window). Notify the household — Plex will
   be offline for the cutover window.

### Stop native Plex

```sh
osascript -e 'quit app "Plex Media Server"'
# Or: kill the PID
# Wait for sqlite WAL checkpoint
sqlite3 "~/Library/Application Support/Plex Media Server/Plug-in Support/Databases/com.plexapp.plugins.library.db" "PRAGMA wal_checkpoint(TRUNCATE);"
```

WAL truncate ensures the DB is consistent at the file level — without
it, the container's first start may apply the WAL with different
locking semantics and produce a "database is locked" error.

### Disable native auto-start

Remove the login item:

```sh
osascript -e 'tell application "System Events" to delete login item "Plex Media Server"'
```

If that errors (GUI auth required), do it manually via System
Settings → General → Login Items.

### Deploy container

`./komodo-sync` (smart-deploy will see the new hash and bring it up).
Watch the init container logs:

```
plex-prefs    | (no MachineIdentifier mismatch error)
plex-prefs    | exit 0
plex          | Starting Plex Media Server.
plex          | [healthcheck] /identity 200
```

### Verify identity

`curl -s http://localhost:32400/identity | xmllint --xpath
'string(/MediaContainer/@machineIdentifier)' -` returns
`c9d75740-0fd3-4bba-9874-be61f5dc8d38`. Plex web UI shows "Pine
Lake" with the same library sections.

Open a client (iOS, web, TV) and verify watch history is intact. If
history is gone but identity is right, the issue is a stale client
cache — fix by signing out + back in on that client.

### Library checks

Each section in the UI shows the expected media counts. Don't
trigger a "Scan Library Files" — let it run on schedule. A surprise
mass rescan means a mount path mismatch; stop and investigate.

### Retire native install

After 48-h soak:

```sh
# Move the .app out of /Applications (don't delete in case of rollback)
mv "/Applications/Plex Media Server.app" "/Applications/_archive-Plex Media Server.app"
```

Do **not** delete the original
`~/Library/Application Support/Plex Media Server/` directory — that's
the running container's state directory. Same for the plist.

## Rollback path

Within the cutover window:
1. `docker stop plex plex-prefs && docker rm plex plex-prefs`
2. Re-open the native app from `/Applications/Plex Media Server.app`
   (still installed). It reads the same state directory; native
   resumes.

After the soak (`.app` archived): same as above but the unarchive
step is `mv /Applications/_archive-Plex Media Server.app
/Applications/Plex Media Server.app`.

Rollback is safe because the container hasn't modified state in a way
the native app can't read — but if it has been running for a long
time, the DB schema may have migrated forward. **Do not rollback to a
significantly older native Plex version.** The .app on disk matches
1.40.4 which is current; if the container has run for weeks, expect
the DB to have been migrated by minor-version updates and a native
downgrade to be a one-way trip.

## Risks specific to pinelake

- **No off-host backup currently exists.** The bootstrap snapshot is
  the only restore source until Backrest is running. Don't start
  Plex migration until the snapshot is verified.
- **`/Volumes/TerraMaster` mount race.** Plex container won't start
  until `/Volumes/TerraMaster` is present. `docker run` will fail or
  start with an empty path otherwise. The `colima-start-wait.sh`
  wrapper handles this for boot; for manual restarts, confirm the
  volume is mounted first.
- **Apple FSEvents → inotify.** Library auto-scan-on-change worked
  on the native FSEvents stack. In the container it's inotify;
  works on Linux, but kernel inotify watch limits can bite for
  6.6 TiB across many subdirectories. Set
  `fs.inotify.max_user_watches=1048576` inside the colima VM if
  scan events look sluggish.
- **Plex transcoding on M1 — partial regression risk.** Native
  Apple-Silicon Plex (1.40+) uses VideoToolbox for **H.264 encode**
  and for decode of H.264/H.265/ProRes. **HEVC/H.265 encode is
  software even on native** — VideoToolbox encode on AS is H.264-only.
  In a Linux container under colima, no HW path is available
  (no VAAPI, no QSV, no VT passthrough), so **everything becomes
  software CPU encode**. Practical impact depends on the workload:
  - If sessions are predominantly H.264 → H.264 (bitrate/resolution
    downscale to remote clients): **HW today, software in container**
    — real regression, M1 CPU encode of 1080p H.264 is ~30–60 fps
    per core depending on preset.
  - If sessions are HEVC → anything: software both before and after,
    **no regression**.
  - Direct play / direct stream sessions: unaffected either way.
  Check the current setting (`Settings → Transcoder → Use hardware
  acceleration when available`) and audit the Tautulli-style transcode
  history (or `Plex Media Server.log` grep for `VideoToolbox`) before
  cutover. If the workload is HW-H.264-heavy and the regression is
  unacceptable, Plex should stay native (option 1c in [index](index.md)).

## Backup plan (post-cutover)

Once Backrest is up on pinelake, add `plex-pinelake` plan:

- `/Users/baxter/Library/Application Support/Plex Media Server/Plug-in Support/Databases/`
- `/Users/baxter/Library/Application Support/Plex Media Server/Plug-in Support/Preferences/`
- `/Users/baxter/Library/Application Support/Plex Media Server/Plug-in Support/Data/`
- `Preferences.xml` (templated from token, but the rendered file is
  identity-bearing)

Exclude:
- `Media/` — 20 GB of thumbnails/BIFs, regenerable
- `Metadata/` — 1.4 GB, regenerable
- `Cache/`, `Logs/`, `Updates/`, `Scanners/`, `Codecs/`

Detail in [Platform stacks](platform-stacks.md).

## Acceptance criteria

- `plex-prefs` init container exits 0; `plex` container starts
- `curl http://localhost:32400/identity` returns
  `c9d75740-0fd3-4bba-9874-be61f5dc8d38`
- All library sections present with their expected media counts; no
  unexpected rescan
- Web UI / mobile client shows watch history intact
- `plex.tv` lists the server as online with the same name "Pine Lake"
- Native `Plex Media Server.app` archived (or in place but
  not auto-starting)
- Backup plan added (separate stream)

## Open items deferred

- Public-exposure decision (open question #3)
- Whether to fold pinelake's plex into a `plex/compose.shared.yaml`
  with bilby's. Pinelake's identity is different; the shared compose
  would be the image + ports + Preferences-init-pattern. Worth doing
  once both are stable.
- Hardware transcoding alternatives on Apple Silicon under colima —
  research separately; not in scope for migration.
