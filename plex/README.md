# Plex

Plex Media Server runs in a container on podhaus (Mac mini M1, Asahi Linux). All persistent state lives on Kangaroo NAS — the host is disposable, the NAS is the source of truth.

This document is the runbook for setting Plex up from scratch on a fresh host. Follow it top to bottom.

---

## Critical state — do not lose this

Plex's identity is the single most important thing to preserve across host rebuilds. Clients (apps, smart TVs, plex.tv) identify the server by its `MachineIdentifier`. If it changes, every client treats it as a brand-new server: shared libraries break, watch state is orphaned, you have to re-pair every device.

| Field | Value | Lives in |
|---|---|---|
| `MachineIdentifier` | `e2edf17235c0f4f9b51578e13d7be476c88c1b67` | `Preferences.xml` |
| `CertificateUUID` | `08daece225664375a110630c19cfa1e5` | `Preferences.xml` |
| `AnonymousMachineIdentifier` | `b1e4e63d-1957-4247-ac5f-5e952bcac15f` | `Preferences.xml` |
| `PlexOnlineUsername` | `PodHaus` | `Preferences.xml` |
| Server name (hostname) | `Bilby` | container `hostname:` |

`Preferences.xml` lives at `Kangaroo:/Jump/plex/Library/Application Support/Plex Media Server/Preferences.xml` — i.e. on the NAS, not on the Mac mini. **A host wipe does not affect it.** The only thing that destroys identity is the `pms-docker` first-run script overwriting the file when it can't find one (see Lessons Learned), and the init container in this stack exists specifically to prevent that.

### Verify identity is intact

From any host that can reach the NAS:

```sh
grep -oE 'MachineIdentifier="[^"]*"' \
  '/path/to/Jump/plex/Library/Application Support/Plex Media Server/Preferences.xml'
```

Expected output:

```
MachineIdentifier="e2edf17235c0f4f9b51578e13d7be476c88c1b67"
```

Cross-check against plex.tv (replace `<token>` with the value of `PlexOnlineToken` from the same file):

```sh
curl -s "https://plex.tv/api/v2/resources?X-Plex-Token=<token>&X-Plex-Client-Identifier=verify" \
  | grep -oE 'clientIdentifier":"[^"]*"' | head
```

The owned server's `clientIdentifier` must equal the `MachineIdentifier` above.

### Back it up before touching anything

Before any host work, copy `Preferences.xml` to a path Plex never touches:

```sh
cp '/Users/Shared/Jump/plex/Library/Application Support/Plex Media Server/Preferences.xml' \
   '/Users/Shared/Pouch/backups/plex/Preferences.xml.good'
```

The init container in this stack will restore from `Preferences.xml.good` if it ever finds the live file missing or wrong. **This backup is the last line of defense against losing identity.** Refresh it any time you intentionally change server settings.

---

## NAS configuration (Kangaroo, 10.0.0.25)

| Mount on host | NAS export | Purpose | Backing |
|---|---|---|---|
| `/mnt/jump/plex` | `Kangaroo:/Jump/plex` | Plex config + 44 GB SQLite database | SATA SSD pair, 382 GB |
| `/mnt/pouch` | `Kangaroo:/Pouch` | Media library (movies, TV, etc.) | HDD array, 29 TB |

### QNAP NFS settings

In **Control Panel → Shared Folders → [Jump|Pouch] → Edit Shared Folder Permissions → NFS host access**, both shares need:

| Setting | Value | Why |
|---|---|---|
| Host/IP | `10.0.0.119` | Mac mini's LAN IP. Restrict to this host only. |
| Access | Read/Write | |
| Squash | Map to NAS uid `1000` | Files created over NFS are owned by uid 1000. Must match `PLEX_UID` in compose. |
| Sync | Unchecked (async) | Server acks before flushing. Safe with UPS. |
| Secure | Unchecked | Don't require privileged source port server-side. |

NFS service: **Control Panel → Network & File Services → NFS Service** — enable NFSv4, max version 4.x.

### Jumbo frames

The full path (Mac NIC, switch, QNAP NIC) is configured for MTU 9000. On Linux, set MTU on the relevant interface — for podhaus this is the 10GbE Aquantia AQC113 (`enp*` under Asahi). Verify on the host with `ip link show <iface>`. Verify end-to-end with `ping -M do -s 8972 10.0.0.25` — must succeed.

---

## Library paths — preserve these exactly

Library paths are stored as absolute paths in the SQLite database. Mounting Pouch at the same path inside the container that the database expects means **zero library reconfiguration** after a rebuild.

| Library | Database path |
|---|---|
| Movies | `/Users/Shared/Pouch/Movies` |
| TV Shows | `/Users/Shared/Pouch/TV` |
| Anime | `/Users/Shared/Pouch/Anime` |
| Kids Movies | `/Users/Shared/Pouch/Kids/Movies` |
| Kids TV | `/Users/Shared/Pouch/Kids/TV` |
| Kids Video | `/Users/Shared/Pouch/Kids/Videos` |
| Sports | `/Users/Shared/Pouch/Sports`, `/Users/Shared/Pouch/Races` |
| Documentary Movies | `/Users/Shared/Pouch/Documentaries` |
| Documentary TV | `/Users/Shared/Pouch/Documentary Series` |
| Ελληνικές Ταινίες | `/Users/Shared/Pouch/Ελληνικές Ταινίες` |

This is why the compose volume mount is `pouch:/Users/Shared/Pouch` and not `pouch:/media` or `pouch:/data` — the path is a contract with the database, not a stylistic choice.

> **Cleanup item**: one library entry historically referenced `/Volumes/Macintosh HD/Users/Shared/Pouch/Documentary Series` (a leftover from when Plex ran natively on macOS). If this still appears in the Documentary TV library settings after the new container is up, remove it via the Plex web UI — it will never resolve under Linux.

Plugins to reinstall (or carry across in `/config/Plug-ins/`): **Trakttv**, **Sub-Zero**.

---

## Host setup (Asahi Linux)

Assumes Fedora Asahi Remix is already installed and you can SSH in as a user with sudo. Hostname `podhaus`, static IP `10.0.0.119` on the 10GbE interface (DHCP reservation on the UniFi side is preferred to keeping a static IP in the Linux config).

### 1. Install Docker

```sh
sudo dnf install moby-engine docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker $USER  # log out + back in for group to apply
```

### 2. Clone the repo

```sh
mkdir -p ~/repos && cd ~/repos
git clone <podhaus repo url>
cd podhaus
```

### 3. Verify you can reach the NAS

```sh
ping -c 3 10.0.0.25
showmount -e 10.0.0.25   # should list /Jump and /Pouch
```

If `showmount` isn't installed: `sudo dnf install nfs-utils`.

### 4. Verify identity is intact on the NAS

Mount `/Jump/plex` temporarily to check `Preferences.xml`:

```sh
sudo mkdir -p /mnt/check
sudo mount -t nfs -o vers=4.1,ro 10.0.0.25:/Jump/plex /mnt/check
grep -oE 'MachineIdentifier="[^"]*"' \
  '/mnt/check/Library/Application Support/Plex Media Server/Preferences.xml'
sudo umount /mnt/check
```

Must return `MachineIdentifier="e2edf17235c0f4f9b51578e13d7be476c88c1b67"`. If it doesn't, **stop here** and recover from `/Pouch/backups/plex/Preferences.xml.good` before going further.

---

## Plex stack contents

Three files live in this directory: `compose.yaml`, `backup.sh`, and `healthcheck.sh`. The init container is defined inline in compose. Below is what each should contain on the new host. Treat the existing `compose.yaml` as a starting point — the changes from current state are flagged in **Lessons Learned** at the bottom.

### `compose.yaml`

```yaml
services:
  plex-init:
    container_name: plex-init
    image: alpine:latest
    restart: "no"
    volumes:
      - jump:/config
      - pouch:/pouch
    command:
      - /bin/sh
      - -c
      - |
        set -e
        PREF="/config/Library/Application Support/Plex Media Server/Preferences.xml"
        BACKUP="/pouch/backups/plex/Preferences.xml.good"
        EXPECTED_ID="e2edf17235c0f4f9b51578e13d7be476c88c1b67"

        verify() { grep -q "MachineIdentifier=\"$EXPECTED_ID\"" "$1" 2>/dev/null; }

        if [ ! -s "$PREF" ] || ! verify "$PREF"; then
          echo "Live Preferences.xml missing or has wrong identity"
          if [ -s "$BACKUP" ] && verify "$BACKUP"; then
            echo "Restoring from $BACKUP"
            cp "$BACKUP" "$PREF"
          else
            echo "FATAL: no good backup with expected MachineIdentifier"
            echo "Refusing to start Plex - manual intervention required"
            exit 1
          fi
        fi

        verify "$PREF" || { echo "FATAL: identity check failed after restore"; exit 1; }
        echo "Preferences.xml ok ($(stat -c%s "$PREF") bytes, $EXPECTED_ID)"

  plex:
    container_name: plex
    hostname: Bilby
    image: plexinc/pms-docker:latest
    restart: unless-stopped
    network_mode: host
    depends_on:
      plex-init:
        condition: service_completed_successfully
    environment:
      TZ: Australia/Perth
      PLEX_UID: "1000"
      PLEX_GID: "100"
      CHANGE_CONFIG_DIR_OWNERSHIP: "false"
    volumes:
      - jump:/config
      - pouch:/Users/Shared/Pouch
      - ./healthcheck.sh:/scripts/healthcheck.sh:ro
    tmpfs:
      - /transcode:size=4g
    healthcheck:
      test: ["CMD", "/scripts/healthcheck.sh"]
      interval: 60s
      timeout: 15s
      retries: 3
      start_period: 180s

  plex-backup:
    container_name: plex-backup
    image: alpine:latest
    restart: unless-stopped
    command: ["/bin/sh", "/scripts/backup.sh"]
    volumes:
      - ./backup.sh:/scripts/backup.sh:ro
      - jump:/config
      - pouch:/pouch
      - /var/run/docker.sock:/var/run/docker.sock

volumes:
  jump:
    driver: local
    driver_opts:
      type: nfs
      o: "addr=10.0.0.25,nfsvers=4.1,soft,timeo=600,retrans=5,rw"
      device: ":/Jump/plex"
  pouch:
    driver: local
    driver_opts:
      type: nfs
      o: "addr=10.0.0.25,nfsvers=4.1,soft,timeo=600,retrans=5,nolock,rw"
      device: ":/Pouch"
```

### `healthcheck.sh`

```sh
#!/bin/sh
# Runs inside the plex container every 60s.
# Fails if any of: Plex API down, NFS mounts unreadable, plex.tv mapping not published.
set -e

# 1. Local API responds
curl -sf http://localhost:32400/identity > /dev/null

# 2. NFS mounts are actually readable (not just dentry-cached)
ls /Users/Shared/Pouch/Movies > /dev/null
ls /config/Library > /dev/null

# 3. Plex is published to plex.tv with a non-empty address
PREF="/config/Library/Application Support/Plex Media Server/Preferences.xml"
TOKEN=$(grep -oE 'PlexOnlineToken="[^"]*"' "$PREF" | cut -d'"' -f2)
[ -n "$TOKEN" ] || exit 1

ACCT=$(curl -sf "http://localhost:32400/myplex/account?X-Plex-Token=$TOKEN")
echo "$ACCT" | grep -q 'mappingState="mapped"'
echo "$ACCT" | grep -qE 'publicAddress="[^"]+"'
```

Mark executable: `chmod +x healthcheck.sh`.

### `backup.sh`

The existing script (already in this directory) does a daily `sqlite3 .backup` of the library database with integrity check and auto-recovery. **Add a Preferences.xml copy** to the same backup directory in the same loop:

```sh
cp "/config/Library/Application Support/Plex Media Server/Preferences.xml" \
   "/pouch/backups/plex/Preferences.xml.good.tmp" \
  && mv "/pouch/backups/plex/Preferences.xml.good.tmp" \
        "/pouch/backups/plex/Preferences.xml.good"
```

This keeps the init container's restore source fresh.

---

## Setup procedure

After `compose.yaml`, `healthcheck.sh`, and the updated `backup.sh` are in place:

### 1. Pre-flight: identity must be correct

Already verified in host setup step 4 above. If you skipped that, do it now. **Do not proceed if `MachineIdentifier` doesn't match `e2edf17235c0f4f9b51578e13d7be476c88c1b67`** — the init container will refuse to start the stack and you'll be debugging in the wrong place.

### 2. Confirm remote-access settings are intact

Three Plex preferences must be set for remote access to work on this host. They live in `Preferences.xml` on the NAS, so they persist across rebuilds — but verify before bringing the stack up:

```sh
docker run --rm -v plex_jump:/config alpine:latest sh -c '
  PREF="/config/Library/Application Support/Plex Media Server/Preferences.xml"
  for k in PublishServerOnPlexOnlineKey ManualPortMappingMode ManualPortMappingPort; do
    grep -o "$k=\"[^\"]*\"" "$PREF" || echo "$k MISSING"
  done
'
```

Expected output:

```
PublishServerOnPlexOnlineKey="1"
ManualPortMappingMode="1"
ManualPortMappingPort="32400"
```

If any are missing or wrong, fix them (see **Lessons Learned: remote access needs three settings** below for the full story and recovery steps). Do not proceed until they're correct.

Do **not** pin `customConnections`, `PreferredNetworkInterface`, or `LanNetworksBandwidth` to the host LAN IP. The DHCP-reserved 10.0.0.119 has rotated before and pinning it just forces a rediscovery step on every host rebuild for zero functional benefit — Plex auto-detects the LAN interface on real Linux `network_mode: host`.

### 3. Bring up the stack

```sh
cd ~/repos/podhaus/plex
docker compose up -d
```

What should happen:

1. `plex-init` container runs, verifies `Preferences.xml` exists and has the expected `MachineIdentifier`, exits 0
2. `plex` container starts (depends on `plex-init` completing successfully)
3. `plex-backup` container starts in parallel
4. After ~3 minutes (start_period), the healthcheck begins probing
5. Within a few cycles, status becomes `(healthy)`

Watch it come up:

```sh
docker logs -f plex
```

You're looking for `Plex Media Server first run setup complete` followed by service start lines, with **no `Token obtained successfully` line** (that line means first-run wiped your Preferences.xml — see Lessons Learned).

---

## Verification checklist

Run through these in order. Don't tick "done" until everything in this list is green.

### Container layer

```sh
docker ps --filter name=plex --format 'table {{.Names}}\t{{.Status}}'
```

Both `plex` and `plex-backup` must be `Up … (healthy)` (plex-init should have exited successfully and not appear here).

### Local API + identity

```sh
curl -sf http://localhost:32400/identity \
  | grep -oE 'machineIdentifier="[^"]*"'
```

Must return `machineIdentifier="e2edf17235c0f4f9b51578e13d7be476c88c1b67"`. Anything else means identity has changed — **stop, do not let any client connect, restore from backup**.

### NFS mounts are alive

```sh
docker exec plex ls /Users/Shared/Pouch/Movies | head
docker exec plex ls /config/Library | head
```

Both should list files. If either hangs or errors, NFS is broken — check host-side connectivity to `10.0.0.25` and the QNAP NFS service status.

### Libraries query

```sh
TOKEN=$(docker exec plex sh -c \
  'grep -oE "PlexOnlineToken=\"[^\"]*\"" "/config/Library/Application Support/Plex Media Server/Preferences.xml" | cut -d\" -f2')
curl -s "http://localhost:32400/library/sections?X-Plex-Token=$TOKEN" \
  | grep -oE 'title="[^"]*"' | head
```

Must list all 10 libraries (Movies, TV Shows, Anime, Kids Movies, …).

### plex.tv reachability — **the bit that was actually broken before**

```sh
curl -s "http://localhost:32400/myplex/account?X-Plex-Token=$TOKEN" \
  | grep -oE '(mappingState|publicAddress|publicPort)="[^"]*"'
```

Must show:

```
mappingState="mapped"
publicAddress="<your real public IP>"   # not empty
publicPort="<a real port>"               # not "0"
```

If `publicAddress=""` or `publicPort="0"`, the publish loop is broken — Plex cannot determine its own reachable address. See **Lessons Learned: shallow healthchecks** below.

### From plex.tv's perspective

```sh
curl -s "https://plex.tv/api/v2/resources?includeHttps=1&includeRelay=1&X-Plex-Token=$TOKEN&X-Plex-Client-Identifier=verify" \
  -H "Accept: application/json" | python3 -m json.tool | grep -A 5 '"name": "Bilby"'
```

The `connections` array under Bilby must contain an address that's actually reachable from outside the Mac mini. Specifically: at least one of (a) `10.0.0.119` (LAN), (b) your public IP, or (c) a `relay=true` entry. If the only entries are RFC1918 addresses in `192.168.x.x` ranges that match Docker bridge ranges, you've hit the same OrbStack-class failure mode again — but you shouldn't, because you're on real Linux.

### From a real client

Open the Plex app on a phone or TV, sign in to your Plex account, find Bilby in the server list. Browse a library. Play a file. Direct play and transcode (force a quality lower than the source) both work.

Only after **all of the above** pass is the deployment done.

---

## Backup and recovery

### What gets backed up automatically

The `plex-backup` sidecar runs daily and writes to `Pouch:/backups/plex/`:

| File | Source | What it protects against |
|---|---|---|
| `backup.db` | `com.plexapp.plugins.library.db` (44 GB SQLite) | Database corruption — preserves library, watch history, metadata |
| `Preferences.xml.good` | live `Preferences.xml` | First-run wipe — preserves server identity |

The backup script does an `sqlite3 .backup` (consistent snapshot, safe while Plex is running), runs `PRAGMA integrity_check` on the result, and only promotes it to `backup.db` if the check passes. Two consecutive failures triggers an auto-restore from the last good backup.

### Manual recovery: identity wiped

If you find `Preferences.xml` has the wrong `MachineIdentifier` (or is the 650-byte stub size that means a fresh first-run):

```sh
docker compose stop plex
docker run --rm \
  -v plex_jump:/config \
  -v plex_pouch:/pouch \
  alpine:latest sh -c '
    cp "/pouch/backups/plex/Preferences.xml.good" \
       "/config/Library/Application Support/Plex Media Server/Preferences.xml"
  '
docker compose start plex
```

The init container will verify identity on next start.

### Manual recovery: database corruption

```sh
docker compose stop plex
docker run --rm \
  -v plex_jump:/config \
  -v plex_pouch:/pouch \
  alpine:latest sh -c '
    cp "/pouch/backups/plex/backup.db" \
       "/config/Library/Application Support/Plex Media Server/Plug-in Support/Databases/com.plexapp.plugins.library.db"
    rm -f "/config/Library/Application Support/Plex Media Server/Plug-in Support/Databases/com.plexapp.plugins.library.db-wal"
    rm -f "/config/Library/Application Support/Plex Media Server/Plug-in Support/Databases/com.plexapp.plugins.library.db-shm"
  '
docker compose start plex
```

### Last-resort: re-claim a lost identity

If both `Preferences.xml` and `Preferences.xml.good` are gone or have the wrong identity, the server identity is unrecoverable. You'll need to:

1. Get a fresh claim token from <https://plex.tv/claim>
2. Add `PLEX_CLAIM: claim-xxxxxx` to the plex container env
3. Let first-run create a brand-new `Preferences.xml`
4. **Update the `EXPECTED_ID` in the init container** to the new MachineIdentifier
5. **Update the `MachineIdentifier` constant in the Critical State table at the top of this document**
6. Refresh the Preferences.xml.good backup
7. Re-pair every client device manually (no migration path for shared libraries, watch state, or remote-friend access — they all see a new server)

This is recovery, not migration. Avoid getting here.

---

## Lessons learned (and why this stack looks the way it does)

### Why we left OrbStack/macOS for Asahi Linux

`network_mode: host` on any Mac-VM Docker (OrbStack, Docker Desktop, Colima) means "host of the Linux VM", not "host of the Mac". The container only sees the VM's internal bridges (e.g. 192.168.139.x, 192.168.215.x), never the Mac's `en0`. Plex's auto-discovery picks one of those internal addresses, publishes it to plex.tv, and every client trying to discover the server through plex.tv gets handed an unreachable address. Local API works (because you're hitting localhost which OrbStack proxies through), but every remote/discovery client sees the server as offline.

On real Linux, `network_mode: host` actually means the host. The container sees the real `enp*` interface and `10.0.0.119`, publishes correctly, and the whole problem class disappears. This is also why **Home Assistant** and **Syncthing** — both of which need real LAN broadcast/mDNS visibility — had to move off the Mac VM stack.

### Why the init container exists

The `pms-docker` image runs a `40-plex-first-run` script at every container start that, **if it doesn't see a `Preferences.xml`**, creates a fresh one (claiming a brand-new server identity if `PLEX_CLAIM` is set, or leaving an unconfigured stub if not). This script can't tell the difference between "this is a fresh install" and "the NFS mount isn't ready yet", and the consequences of guessing wrong are catastrophic: the existing identity is gone, every client treats the server as new, no recovery without a backup.

This actually happened during the original NFS migration. The init container is the structural fix — it runs **before** Plex, hard-codes the expected `MachineIdentifier`, and refuses to let the stack come up if either the live file or the backup doesn't match. It is intentionally fail-fast: if identity can't be confirmed, nothing starts. Better an offline Plex than a Plex with the wrong identity.

### Why the healthcheck looks like it does

The previous healthcheck only ran `curl /identity` and `test -d` on the mount points. It missed two entire failure classes:

1. **Stale NFS dentry cache.** `test -d` resolves against the kernel's cached directory entry, which can stay valid even when actual reads from the directory return EIO. The fix is to use `ls`, which forces an actual readdir.
2. **Plex healthy locally but invisible to plex.tv.** When Plex can't determine a publishable address, the local API still returns 200 — but `mappingState` stays in `Mapped - Publishing` and `publicAddress` stays empty. The fix is to query `/myplex/account` and verify both `mappingState="mapped"` and a non-empty `publicAddress`.

The new `healthcheck.sh` checks all three. If any fail, the container is marked unhealthy and the restart policy (or autoheal, if enabled in `autoheal/`) kicks in. **Note that on real Linux, simple restart actually fixes things** — unlike the OrbStack situation where `docker restart` couldn't remount stale NFS volumes because the mounts lived on the VM host, not in the container namespace.

### Remote access needs three settings (and one of them is the master kill switch)

Remote access was broken for a while after the container migration. The surface-level symptoms were `mappingState="Mapped - Not Published (Not Reachable)"`, `publicAddress=""`, and `POST https://plex.tv/servers.xml` returning HTTP 422. The actual root cause was buried three layers deep and it's worth documenting so the next version of me doesn't waste the time I did.

The three preferences that must be set in `Preferences.xml`:

| Setting | Value | Why |
|---|---|---|
| `PublishServerOnPlexOnlineKey` | `1` | **The master "Enable Remote Access" toggle.** Lives in the unnamed `[]` pref group (not `[network]`), which is why it's easy to miss when grepping for network settings. Had silently been set to `0` — probably a leftover from the OrbStack era where remote access was deliberately disabled to stop the VM-bridge-IP publishing bug. When this is `0`, Plex does not run its publish flow at all. No public IP discovery, no port mapping, no reachability check. The 422s you see with this off are a degenerate heartbeat POST — they look like the real publish but they're not. |
| `ManualPortMappingMode` | `1` | Tells Plex "skip UPnP port-mapping creation, trust the static port forward". Needed because Plex's UPnP IGD discovery uses multicast SSDP, which UniFi silently drops on this LAN — unicast NAT-PMP to the gateway works fine (Plex uses it to learn the public IP), but the UPnP `AddPortMapping` path never gets off the ground. Without manual mode, Plex doesn't know what port to advertise. |
| `ManualPortMappingPort` | `32400` | The external port that the UniFi port forward points at. Paired with the mode above. |

Setting `PublishServerOnPlexOnlineKey=1` alone is enough to make Plex *try* to publish. The other two are what make the publish *succeed* given that UniFi's SSDP multicast is filtered and Plex can't do UPnP auto-mapping.

What we explicitly do **not** set:

- `customConnections` — left empty. On real-Linux `network_mode: host`, Plex auto-detects `10.0.0.119` correctly and publishes the right `plex.direct` URL without help. Pinning it here hardcodes the DHCP-reserved host IP, which is a fragility we don't need.
- `PreferredNetworkInterface` — left empty. Same reasoning: the value would be the host LAN IP, and we don't want IPs baked into preferences.
- `LanNetworksBandwidth` — left empty. Defining a subnet here had zero observable effect on interface enumeration or publish behavior.

### Diagnosing remote-access breakage

If remote access breaks again, skip the UPnP rabbit hole and check these three prefs first:

```sh
docker exec plex sh -c 'grep -oE "(PublishServerOnPlexOnlineKey|ManualPortMappingMode|ManualPortMappingPort)=\"[^\"]*\"" \
  "/config/Library/Application Support/Plex Media Server/Preferences.xml"'
```

Then watch for the actual publish flow in the log:

```sh
docker exec plex sh -c 'tail -f "/config/Library/Application Support/Plex Media Server/Logs/Plex Media Server.log"' \
  | grep -iE "publish|mapping|nat|reachab|Published Mapping"
```

A healthy publish looks like this:

```
PublicAddressManager: Got public IP from v4.plex.tv: <your public IP>
NAT: UPnP, getPublicIP didn't find usable IGD.               ← expected, SSDP is filtered
NAT: PMP::getPublicIP, Received public IP from router: <same IP>  ← NAT-PMP unicast works
MyPlex: Sending Server Info to myPlex (..., ip=<public IP>, port=32400)
MyPlex: Published Mapping State response was 201             ← 201, NOT 422
MyPlex: mapping state set to 'Mapped - Publishing'
```

An empty `ip=` or `port=0` in the `Sending Server Info` line means `ManualPortMappingMode/Port` isn't being honored — check `PublishServerOnPlexOnlineKey` first.

### Why the database lives on Jump (SSD), not Pouch (HDD)

Jump is a 382 GB SATA SSD pair on the QNAP. Pouch is the 29 TB HDD media array. The 44 GB SQLite database does heavy random IO during library scans and search — random 4K fsync IOPS on Jump benchmark at ~2.5× Pouch (1,068 vs 424 IOPS). Bulk media reads, on the other hand, are fully sequential and the HDDs are fine. Splitting them keeps each workload on the right backing storage.

### Why the transcode directory is a tmpfs

Transcoding writes a lot of small temp files during a session (1.5–2.2 GB for a typical single transcode). Putting `/transcode` on tmpfs keeps it in RAM, avoiding NFS round-trips on the hot path. On a 16 GB Mac mini, 4 GB of tmpfs is comfortable.

### Why no Plex hardware transcoding

Apple Silicon's media engines (VideoToolbox) have no Linux driver — they're an undocumented Apple block and Asahi can't expose them. Plex transcoding is software-only. This was already true on OrbStack (Linux container had no VideoToolbox access there either), so it's not a regression. M1 CPU is fast enough for 1080p in software trivially; 4K HDR tone-mapping is the worst case and if it becomes a problem the answer is "play a different copy" or "let the client direct-play".

---

## References

- [plexinc/pms-docker (official image)](https://github.com/plexinc/pms-docker)
- [pms-docker first-run script (the one that wipes Preferences.xml)](https://github.com/plexinc/pms-docker/blob/master/root/etc/cont-init.d/40-plex-first-run)
- [Plex hardware transcoding support matrix](https://support.plex.tv/articles/115002178853-using-hardware-accelerated-streaming/)
- [Asahi Linux M1 feature support](https://asahilinux.org/docs/platform/feature-support/m1/)
- [Asahi DisplayPort/Thunderbolt status (re: headless install)](https://asahilinux.org/docs/hw/soc/display-controllers/)
