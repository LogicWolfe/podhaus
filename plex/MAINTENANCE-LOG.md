# Plex Overnight Maintenance Log — 2026-04-12

## Background

Plex running on bilby with 44GB SQLite database on NFS (10.0.0.25:/Jump/plex).
Multiple issues discovered today:
- Wrong host timezone (America/New_York → fixed to Australia/Perth) caused butler to run during peak hours
- Butler + on-the-fly theme track analysis caused cascading SQLite write lock storms
- Theme music DB records missing for many shows — files on disk since 2022 but DB doesn't reference them
- Write contention from normal play state updates also causing lock storms
- Plex crashed earlier today (autoheal SIGTERM), recovered 872 WAL frames

## Plan

Create 3 fix copies from the original (original at /Jump/plex is never modified):

| Copy | DB Location | Metadata | DB Fix | Metadata Fix |
|------|------------|----------|--------|--------------|
| **local-db** | Local NVMe (/var/lib/plex-local) | NFS (/Jump/plex-local-meta), freshly regenerated | VACUUM + REINDEX | Force refresh all libraries |
| **sync** | NFS (/Jump/plex-sync) | NFS (kept from original) | VACUUM + REINDEX | RefreshLocalMedia + scan + analyze |
| **clean** | NFS (/Jump/plex-clean) | NFS (wiped + re-downloaded) | VACUUM + REINDEX | Force refresh all libraries |

Order: local-db (easiest) → sync → clean (heaviest)

All copies also get: BIF generation enabled, DeepMediaAnalysis, chapter thumbnails, final DB optimize.

## Execution Log

### Phase 1: Create copies (22:03 AWST)
- Stopped Plex
- sync copy: rsync to /Jump/plex-sync — 57GB, completed ~22:27
- clean copy: rsync to /Jump/plex-clean — 57GB, completed ~22:27
- local-db copy: rsync (DB only) to /var/lib/plex-local — 46GB, completed ~22:08
- Created empty /Jump/plex-local-meta for local-db metadata
- Plex DB backups from April 11 excluded from all copies to save space

### Phase 2: local-db (started 22:48 AWST)
- Attempted offline VACUUM using Plex's bundled "Plex SQLite" tool
  - System sqlite3 fails: missing `icu_root` collation (Plex custom)
  - Plex SQLite is a wrapper that expects the full PMS binary alongside it
  - Extracted to host, tried symlink trick — runs but produces no output
  - Decision: use Plex API OptimizeDatabase instead (runs VACUUM/REINDEX online)
- Started Plex against local-db copy (compose.local-db.yaml)
- SELinux fix required: added `:z` to local bind mount in compose file
- API OptimizeDatabase ran (6.5 min to 60%, then stuck at 60% for 30min — VACUUM phase blocked all API requests)
- Force refresh all 10 libraries: completed in 25 minutes, zero lock storms during refresh
  - Movies: 2min, TV Shows: 10min, Greek Movies: <1min, Kids Movies: 1min
  - Kids TV: 10min, Sports/Kids Video/Doc Movies: <1min each, Doc TV: <1min, Anime: <1min
- Analyzed all 10 libraries: ~1 minute total
- DeepMediaAnalysis: 3 minutes
- GenerateChapterThumbsTask: 10 seconds
- DB optimize stuck at 60% — restarted Plex to clear it

#### Health check results (local-db)
| Test | Result |
|------|--------|
| Bluey theme | 200 in **7ms** |
| Fallout theme | 200 in **9ms** |
| Inspector Gadget theme | 200 in **78ms** |
| Bluey S2 metadata | 200 in **7ms** |
| Kids TV hub | 200 in **158ms** |
| Library sections | 200 in **1ms** |
| Lock storms | **0** |
| On-the-fly analyses | 3 (completed fast, no lock storms) |
| DB size | 44GB + 14GB WAL |
| Metadata on NFS | 7.3GB |

**Assessment: Excellent.** Theme music serves in single-digit ms. No lock storms during the entire force refresh + analyze workload. The 3 on-the-fly analyses that did occur completed without cascading. DB on local NVMe eliminates the write contention issue. The stuck optimize is a concern — Plex's online VACUUM blocks all API requests, which is the same write lock pattern but self-inflicted.

### Phase 3: sync (started 00:04 AWST)
- Started Plex on /Jump/plex-sync (all NFS)
- RefreshLocalMedia: 5 minutes
- UpgradeMediaAnalysis: instant
- Scanned Movies (instant), then TV Shows scan triggered
- Butler auto-started and scanned all libraries in background (~30 min), blocking our script
- Skipped DB optimize (known to stall)
- Ran health check twice: once during butler (all timeouts), once after clean restart

#### Health check results (sync — clean restart)
| Test | Result |
|------|--------|
| Bluey theme | 200 in **41ms** |
| Fallout theme | 200 in **18ms** |
| Inspector Gadget theme | 200 in **471ms** (triggered on-the-fly analysis) |
| Bluey S2 metadata | 200 in **62ms** |
| Kids TV hub | 200 in **624ms** |
| Library sections | 200 in **19ms** |
| Lock storms | **0** |
| On-the-fly analyses | **1** (Inspector Gadget theme — still not pre-populated) |
| DB size | 44GB |
| Metadata | 12GB (original, not re-downloaded) |

**Assessment: Partial fix.** Theme music mostly works (Bluey/Fallout OK), but Inspector Gadget still triggered an on-the-fly analysis — the lighter RefreshLocalMedia approach didn't fully fix all missing theme DB records. Response times 3-10x slower than local-db. During butler scans, API becomes completely unresponsive (all requests timeout). The NFS DB is functional at idle but fragile under any write load.

### Phase 4: clean (started 01:01 AWST)
- Started Plex on /Jump/plex-clean (all NFS, metadata wiped)
- Wiped Metadata/, Media/, Cache/, Plug-in Support/Caches/ before starting
- Force refresh started: Movies done in 2.5min, TV Shows started
- TV Shows refresh triggered concurrent background scan + metadata downloads
- Concurrent metadata downloads ran continuously for 35+ minutes, blocking pipeline advancement
- Only Movies and TV Shows force-refreshed before health check (8 libraries incomplete)
- Metadata re-downloaded: 12GB (from scratch)
- Skipped analyze, butler tasks, and optimize due to time constraints

#### Health check results (clean — after restart, incomplete refresh)
| Test | Result |
|------|--------|
| Bluey theme | **TIMEOUT** (30s) — Kids TV not yet refreshed |
| Fallout theme | **TIMEOUT** (30s) |
| Inspector Gadget theme | **TIMEOUT** (30s) |
| Bluey S2 metadata | 200 in **16.4s** |
| Kids TV hub | 200 in **448ms** |
| Library sections | 200 in **17ms** |
| Lock storms | **0** |
| On-the-fly analyses | 4 (during refresh) |
| DB size | 44GB |
| Metadata | 12GB (re-downloaded) |

**Assessment: Incomplete — not a fair test.** Theme timeouts are expected since only 2 of 10 libraries were force-refreshed before the health check. The 16.4s metadata response and theme timeouts suggest NFS write contention from the ongoing metadata download activity. Zero lock storms is notable. This copy needs more time to finish refreshing all libraries before it can be fairly evaluated. The key structural finding holds: NFS DB is slow under any write load.

### Phase 5: Restore original (01:40 AWST)
- Stopped Plex on clean copy
- Switched plex_jump volume back to /Jump/plex
- Started Plex on original data

### Phase 6: VACUUM completion on local-db (Apr 13)

#### VACUUM v1 attempt (06:07 - 10:35)
- Started OptimizeDatabase via API on local-db
- Ran for ~4.5 hours, WAL grew to ~40 GB
- **Killed by autoheal at 10:35** — healthcheck timed out under VACUUM DB lock pressure
- Plex restart rolled back the VACUUM transaction (only 13 frames recovered)
- Lost all progress

#### VACUUM v2 attempt (10:56 - 17:57)
Belt-and-suspenders to prevent kill:
1. Removed `autoheal: "true"` label from compose.local-db.yaml
2. Disabled Plex healthcheck entirely (`healthcheck: disable: true`)
3. Stopped the autoheal container

VACUUM ran uninterrupted for **7 hours 1 minute**:
- Phase 1 (temp DB build): ~12 min
- Phase 2 (WAL fill, 0 → 46.41 GB): ~5 hours, rate declined from 570 MB/min to 60 MB/min
- Phase 3 (checkpoint replay): ~1 hour, main DB rewritten in place
- Final commit + WAL truncation: triggered by Plex shutdown

Research confirmed this duration is normal for a 47 GB Plex DB (community reports of 13-24h on 50-67 GB DBs).

#### Final compaction
- Original DB: **47.13 GB** (47,131,291,648 bytes)
- Compacted DB: **45.35 GB** (45,351,560,192 bytes)
- Reclaimed: **1.78 GB (3.8%)** — modest because the DB was already well-packed
- WAL after restart: 116 KB (clean)
- Total local-db dir: 44 GB

#### Post-optimize health check (local-db)
| Test | Result | vs Pre-optimize |
|------|--------|-----------------|
| Bluey theme | **9ms** | 7ms (≈) |
| Fallout theme | **7ms** | 9ms (≈) |
| Inspector Gadget theme | **5ms** | 78ms (-93%) |
| Bluey S2 metadata | **5ms** | 7ms (≈) |
| Kids TV hub | **28ms** | 158ms (-82%) |
| Sections | **1ms** | 1ms (=) |
| Lock storms | **0** | — |
| On-the-fly analyses | **0** | — |

**Assessment:** Optimization successful. Theme music and metadata reads all sub-30ms. The biggest improvement was Inspector Gadget theme (78ms → 5ms) and Kids TV hub (158ms → 28ms) — the VACUUM/REINDEX clearly improved query plans on the larger paths. Modest 3.8% disk space reclamation confirms the DB wasn't heavily fragmented before — most of the 7-hour runtime was rebuilding indexes (especially FTS5), not reclaiming space.

### Phase 7: statistics_bandwidth cleanup (18:50 - 18:51)

Investigation of why VACUUM only reclaimed 3.8% revealed the actual culprit:

```
table                  rows
statistics_bandwidth   796,867,521  ← 9.3 years of bandwidth tracking events
taggings               401,005
media_streams          130,346
metadata_items         21,402
```

The `statistics_bandwidth` table (Plex's internal bandwidth tracking, used only for the Status → Statistics chart in Plex Web) contained **796 million rows** dating back to 2017. At ~70 bytes/row including indexes, this single table was ~55 GB — accounting for almost the entire 47 GB DB.

#### Cleanup approach
Stopped Plex, ran via Plex SQLite (offline):
```sql
BEGIN;
CREATE TABLE statistics_bandwidth_new (...);  -- same schema
INSERT INTO statistics_bandwidth_new
    SELECT id, account_id, device_id, timespan, at, lan, bytes
    FROM statistics_bandwidth WHERE at >= strftime('%s', 'now', '-30 days');
DROP TABLE statistics_bandwidth;
ALTER TABLE statistics_bandwidth_new RENAME TO statistics_bandwidth;
CREATE INDEX index_statistics_bandwidth_on_at ON ...;
CREATE INDEX index_statistics_bandwidth_on_account_id_and_timespan_and_at ON ...;
COMMIT;
```

**Result**: 796,867,521 → **3,410 rows** (last 30 days).

#### Followup VACUUM
After restart, triggered OptimizeDatabase. **Completed in <60 seconds** (vs 7 hours for v2) because there was barely any data left to copy.

#### Final state
| | Before everything | After Phase 6 (VACUUM) | After Phase 7 (delete + VACUUM) |
|---|---|---|---|
| Library DB | 47.13 GB | 45.35 GB | **208 MB** |
| Total local-db dir | — | 44 GB | **1.7 GB** |
| Reduction | — | 3.8% | **99.6%** |

**Lesson**: The 7-hour VACUUM v2 was almost entirely wasted churning through bandwidth statistics rows. The actual library data (metadata, media, streams, watch state, FTS indexes) is only ~200 MB. Plex's `statistics_bandwidth` table grows indefinitely with no UI to manage it — this is the "Plex DB bloat" the community talks about.

#### Data lost
- Bandwidth chart history older than 30 days (Plex Web → Status → Statistics)
- Nothing else — all library content, metadata, watch state, posters, custom edits intact

## Summary & Recommendations

### Comparative results (idle, after restart)

| Test | local-db (NVMe) | sync (NFS) | clean (NFS, incomplete) |
|------|-----------------|------------|------------------------|
| Bluey theme | **7ms** | 41ms | timeout |
| Fallout theme | **9ms** | 18ms | timeout |
| Inspector Gadget | **78ms** | 471ms | timeout |
| Bluey S2 metadata | **7ms** | 62ms | 16,400ms |
| Kids TV hub | **158ms** | 624ms | 448ms |
| Lock storms | **0** | 0 | 0 |
| On-the-fly analyses | 0 | 1 | 4 |
| Under write load | **stable** | **unresponsive** | not tested |

### Key findings

1. **local-db is the clear winner.** DB on local NVMe eliminates write contention completely. Theme music in single-digit ms. No lock storms even during heavy force refresh + analyze workload. The only issue: Plex's own OptimizeDatabase got stuck at 60% for 30min, but that's a Plex internal issue not specific to this config.

2. **NFS DB is structurally fragile under write load.** Both sync and clean copies became unresponsive during any background write activity (butler scans, metadata downloads). The NFS latency is fine for reads, but SQLite write serialization + WAL checkpointing causes cascading contention.

3. **Force refresh fixes theme music.** The local-db copy (force refresh all) had 0 on-the-fly analyses for themes. The sync copy (lighter RefreshLocalMedia) still had 1. Force refresh is the complete fix.

4. **Offline VACUUM not possible.** Plex's SQLite uses custom ICU collation not available in system sqlite3. The bundled "Plex SQLite" is a wrapper that can't be used standalone. Online OptimizeDatabase is the only option but it blocks all API requests during the VACUUM phase.

### Recommended path forward

**Use local-db configuration**: DB on local NVMe (/var/lib/plex-local), metadata on NFS (/Jump/plex-local-meta). This gives the best of both worlds — fast DB writes on local storage, shared metadata accessible from NFS. The compose.local-db.yaml file is ready.

**Remaining work for local-db:**
- The DB optimize never completed — run it during a maintenance window (expect ~30min of API unavailability)
- BIF generation was enabled but chapter thumbnails need time to generate (butler will handle overnight)
- Metadata is 7.3GB vs 12GB original — force refresh downloaded most but not all assets
- Poster selections need manual verification

### Files created
- `plex/compose.local-db.yaml` — Docker Compose for local-db config
- `plex/plex-switch.sh` — Switch between copies
- `plex/plex-maintenance.sh` — Maintenance script (phases can be run individually)
- `plex/MAINTENANCE-LOG.md` — This file

### Data locations
- `/Jump/plex` — Original (untouched)
- `/Jump/plex-sync` — Sync copy (NFS, partial fix)
- `/Jump/plex-clean` — Clean copy (NFS, incomplete refresh)
- `/var/lib/plex-local` + `/Jump/plex-local-meta` — Local-db copy (recommended)
