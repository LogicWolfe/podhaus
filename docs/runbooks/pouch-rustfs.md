# Pouch RustFS

`pouch.pod.haus` is a dedicated S3 endpoint for Sky's encrypted restic
repository. RustFS runs on kangaroo and writes directly to Pouch at
`/share/CACHEDEV1_DATA/Pouch/rustfs`. No repository data lands on Jump.

## Path

```text
Sky's restic
  -> pouch.pod.haus:443
  -> Numbat public TLS tunnel :443
  -> bilby Caddy
  -> kangaroo RustFS :9000
  -> /share/CACHEDEV1_DATA/Pouch/rustfs/sky-backups
```

The public DNS record is grey-cloud. Cloudflare is authoritative DNS but never
enters the data path. The public TLS tunnel carries all TLS on
port 443 to Caddy, so this hostname needs no listener of its own. Caddy
terminates TLS and preserves the request headers required by S3 SigV4.

LAN clients resolve `pouch.pod.haus` to bilby and take the shorter Caddy to
kangaroo path. Remote clients resolve it to Numbat's relay address.

## Provisioning and credentials

Terraform owns the whole identity chain:

- `Pouch RustFS Root` in 1Password, generated once for the server and aliased
  Terraform provider;
- the private `sky-backups` bucket, with S3 versioning disabled;
- the `sky-backups` IAM user, policy, and revocable service account;
- a list-only `sky-backups-monitor` identity for repository-age checks;
- the `Sky Backups` 1Password login containing the S3 access key, secret key,
  repository URL, region, and restic encryption password.

Sky never receives the RustFS root credential. Her policy grants object
read/write/delete plus list and location operations on `sky-backups` only.

The `Sky Backups` 1Password item is the Terraform-owned source of truth for
the client configuration:

```dotenv
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
RESTIC_REPOSITORY=s3:https://pouch.pod.haus/sky-backups/personal-laptop
RESTIC_PASSWORD=...
AWS_DEFAULT_REGION=us-east-1
```

The `personal-laptop` repository is initialized, so the client must not run
`restic init` again. Sky's client only runs the backups. Bilby forgets old
snapshots, checks integrity and prunes (see Maintenance below), because the
laptop is rarely on long enough for a weekly or monthly job to start. Don't enable RustFS bucket versioning: restic owns snapshot retention,
and S3 versions would retain packs that restic has pruned.

Do not use `restic backup --skip-if-unchanged` on the client. A normal backup
always commits a new encrypted `snapshots/<snapshot-id>` object, even when its
file tree matches the parent snapshot and all data packs are deduplicated.
`--skip-if-unchanged` suppresses that commit, which would make a successful run
invisible to the repository monitor.

## Operation

The container has no CPU or memory limit. Backups are bursty and kangaroo has
enough headroom to let RustFS use the host normally. Docker's healthcheck probes
RustFS's live endpoint and kangaroo's existing autoheal container restarts it on
a sustained failure. There are no service-specific resource alerts.

The console port is not published. Terraform reaches the admin API through
`https://pouch.pod.haus`; Sky's scoped key reaches only the S3 operations her
repository needs.

The `sky-backups-monitor` container on bilby lists committed snapshot objects
under `sky-backups/personal-laptop/snapshots/` at 15 minutes past each hour. It
reports success when at least one snapshot object has a server-side modification
time within the last fourteen days.

Terraform provisions a separate `sky-backups-monitor` RustFS identity for this
check. Its policy permits bucket listing and location lookup only. It cannot read,
write, or delete an object.

Before the first snapshot, the repository's `config` object starts the same
fourteen-day grace window. After that, an empty repository or an older newest snapshot
reports failure. Query failures produce no result, so Gatus's two-hour heartbeat
window also catches a stopped monitor or an unreachable repository. Sky's laptop
needs no Gatus credential or callback.

## Maintenance

The `sky-backups` stack on bilby runs one idle `sky-backups-maintenance`
container (the stock `restic/restic` image) that Ofelia execs into, using the
same `Sky Backups` 1Password item as the laptop:

| Job | Schedule | Runs |
|---|---|---|
| `sky-backups-forget` | 03:30 daily | `restic forget` with the retention policy, per host |
| `sky-backups-check` | 04:00 Sunday | `restic check` |
| `sky-backups-prune` | 04:00 on the 8th | `restic forget`, then `restic prune` |
| `sky-backups-read-subset` | 04:00 on the 22nd | `restic check --read-data-subset=<n>/10`, a different tenth each month |

`sky-backups/scripts/maintain.sh` runs each one. Retention keeps hourly snapshots from the last two days, then 7 daily, 5 weekly, 12
monthly and 3 yearly, applied to each host separately so one machine's history never
decides what another keeps. Forget runs daily, so hourly snapshots are thinned as the policy expects, and prune runs it
first, so a prune never works from a stale snapshot list. Jobs that coincide queue on a
local lock. Each first runs `restic unlock`, which removes only locks their
owner stopped refreshing; a running laptop backup refreshes its lock every five
minutes and is never touched. Then it waits up to an hour for any live lock. A
laptop backup that starts during a prune waits 15 minutes for its lock and
then fails, so the jobs run at 04:00, when the laptop is almost always off.

Gatus's `Backup / Sky Restic Maintenance` check reads Ofelia's `Job stop` lines
in ClickStack. It needs a successful forget and check within eight days and a successful
prune and data read within 33 days. Run a job by hand on bilby with
`docker exec sky-backups-maintenance /scripts/maintain.sh check`; a manual run
writes no Ofelia line, so it doesn't satisfy the Gatus check.

## Checks

```sh
curl -fsS https://pouch.pod.haus/health/ready
restic snapshots
restic check
```

An external-path check can force the Numbat route from bilby:

```sh
curl --resolve pouch.pod.haus:443:$(terraform -chdir=terraform output -raw numbat_relay_ipv4) \
  -fsS https://pouch.pod.haus/health/ready
```

## Recovery

Pouch holds this additional backup copy and is deliberately not backed up to
Jump. If the container or its configuration is lost while Pouch survives,
redeploy the stack and run Terraform to recreate the bucket and IAM state. If
Pouch itself is lost, the repository is lost with it; create a new empty bucket
and initialize a new restic repository from Sky's source data.

RustFS system metadata lives beside the objects under the dedicated data root.
Do not edit, move, restore individual files from, or prune the server data root.
