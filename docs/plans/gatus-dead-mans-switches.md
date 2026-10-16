# Dead-man's switches as ClickStack queries

## Goal

Every "did X happen recently" alert in Gatus is a pull check that asks
ClickHouse, so a Gatus restart can never defer or skip it, and the services
being watched push nothing to Gatus.

## The problem

Gatus checks a push endpoint's `heartbeat.interval` on a timer created when
the Gatus process starts, once per interval
(`watchdog/external_endpoint.go`, `time.NewTicker(interval)`). The last push
time is persisted, the check cadence is not. Every podhaus deploy that touches
`gatus/` recreates the container (58 such commits since 2026-08-01, about five
a week), so a 25 h or 48 h window rarely gets one uninterrupted interval, and
even without restarts a silence is noticed one to two intervals after it
begins. Upstream knows (issue 1237, open since 2025-09; fix PRs 1528, 1718,
1792 unmerged). Evidence from Gatus's own database: the Brinno endpoint's last
push was 2026-10-01 06:55 UTC and its failures were recorded on 2026-10-07
14:19 and 2026-10-10 23:15, each exactly 48 h after a Gatus start.

Uptime Kuma has the same defect (its push monitor waits one full interval
after start). Healthchecks does not, but is a second alerting system.

## Approach

Gatus already queries ClickHouse: the *Telemetry Pipeline* checks POST SQL to
ClickHouse's HTTP port on bandicoot (published on the LAN for this) with the
`default` user and assert the answer. A dead-man's switch is the same shape:

- `url: http://${BANDICOOT_LAN_IPV4}:8123/`, `method: POST`, the two
  ClickHouse headers, `body:` the SQL ending in `FORMAT JSONEachRow`.
- The SQL returns one row with one string column `why`: `ok`, or a sentence
  naming what is wrong (which plan, which day, the error text). The condition
  is `[BODY].why == ok`, so the failed condition Gatus reports, and forwards
  to Fenwick in `conditions`, carries the reason.
- `interval: 10m`, `failure-threshold: 2`, so a ClickHouse hiccup needs
  twenty minutes to page. A pull endpoint runs its first check at start and
  every check is stateless, so restarts cost nothing.

The signals come from what services already emit into ClickStack:

| Switch | Signal in ClickStack | Window |
|---|---|---|
| Timelapse / Brinno | a `brinno.archive` span from `brinno-downloader` | 48 h |
| Timelapse / Brinno downloader | a `brinno.reconcile` span | 3 h |
| Timelapse / Brinno stuck day | latest cycle span's `brinno.files_overdue` = 0, else its `brinno.overdue` text | latest cycle |
| Timelapse / Brinno card | latest cycle span's `brinno.card_used_bytes` under 90 % of `brinno.card_total_bytes` | latest cycle |
| Backup / Backrest Nightly, (bandicoot), Kangaroo, Pinelake | Backrest logs per host: no `ERROR … task failed`; every plan with a `running task backup for plan` line also has a `forget for plan` line (Backrest schedules forget only after a snapshot); at least one plan backed up | 25 h |
| Backup / Backrest Forgejo | the same for lines mentioning `forgejo`, plus no `failed=true` stop of the ofelia `forgejo-backup-recover` job | 25 h |
| Backup / Backrest Pets, Yiayia | the same for the plan's lines | 3 h |
| Observability / ClickStack Mongo Dump | an ofelia `Job stop job=clickstack-mongo-dump … failed=false` line | 25 h |
| Plex / Plex Stats Cleanup | an ofelia `Job stop job=plex-stats-cleanup … failed=false` line | 33 days |
| Torrents / RAR Extraction, Pinelake RAR Extraction | the latest ofelia `Job stop job=rar-backlog` line per host: present, `failed=false`, stdout not `UNHEALTHY` | 25 h |

Every query above was run against live data before shipping; each answered
`ok` except where reality disagreed (bilby's stale `clickstack` plan, pinelake
offline, Brinno's genuine silence, the card estimate pending its deploy).

Pushes with short windows stay pushes, since a restart defers them by at most
their window: Sky invalidation (3 m), StreamFab Publish (5 m), Plex Label
Sync and Pinelake Stignore (30 m), Sky Restic Repository (2 h, a weekly
laptop backup judged by an hourly job), and Plexify (event-only).

### What this depends on

ClickStack holding the logs and traces (retention is 180 days) and Alloy
shipping them. If the telemetry pipeline stalls, every switch goes red at
once and the *Telemetry Pipeline* checks say why: loud, not silent. Gatus
queries ClickHouse as `default`; a read-only user would be tidier and is not
required.

Backrest logs no "completed" line. A plan's `forget` task is scheduled only
after a snapshot exists, before the success hooks run, so "forget ran" means
the snapshot landed and "ERROR task failed" catches a fatal hook (the off-site
mirror on bilby's `backrest-state` plan) as well as the backup itself. A
partial backup (some files unreadable) is a warning, not an error, and is not
caught; it never was.

## Removed with the migration

- The Backrest Gatus hooks on every host (the per-repo `CONDITION_ANY_ERROR`
  push and the `backrest-state` success push), the push in
  `forgejo-backup-control` and `sync-bandicoot-repository`, and the
  `GATUS_*` environment that fed them. The error push had never worked: its
  URL carried the task name's spaces unencoded, Gatus rejected every such
  request as malformed, and the hook's own failure logged a daily
  `exit status 1`.
- The push in `clickstack/scripts/mongo-dump.sh`, `plex/scripts/stats-cleanup.sh`
  and `flood/scripts/rar-backlog.sh`, with their environment.
- The Brinno downloader's heartbeat module (fenwick repo); the cycle span now
  carries `brinno.overdue`, `brinno.card_used_bytes` and
  `brinno.card_total_bytes` beside the counts it already had.
- `backup/tests/test_heartbeat_contract.py`, which pinned the push plumbing.
- Bilby's `clickstack` Backrest plan: ClickStack moved to bandicoot, the path
  no longer existed, and the plan had failed nightly since at least
  2026-09-17 without anyone hearing of it.

## Verification

- Each query run by hand against ClickHouse over HTTP exactly as Gatus sends
  it, before and after the change, with the verdicts recorded above.
- Gatus started locally in Docker on the new config with placeholder
  environment: it must log `Validated N endpoints` with N up by twelve and
  `Validated 7 external endpoints`.
- After deploy: the Gatus status page shows the new endpoints evaluating
  within ten minutes; *Backrest Nightly* on bilby stays red until the stale
  plan's last failure ages out of the 25 h window, then resolves; *Brinno*
  stays red until the camera uploads a day and the downloader archives it;
  *Brinno card* goes green once the downloader deploy stamps the card bytes.
- The next Gatus restart (any `gatus/` commit) no longer changes when any of
  these checks runs.

## Left for Nathan

Listed in the session report: whether to keep the remaining short pushes as
they are, and whether a read-only ClickHouse user for Gatus is worth a
secret.
