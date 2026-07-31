# Pouch MinIO

`pouch.pod.haus` is a dedicated S3 endpoint for Sky's encrypted restic
repository. The MinIO process runs on kangaroo and writes directly to Pouch at
`/share/CACHEDEV1_DATA/Pouch/minio`. No repository data lands on Jump.

## Path

```text
Sky's restic
  -> pouch.pod.haus:443
  -> kookaburra rathole :443
  -> bilby Caddy
  -> kangaroo 10.0.0.25:9000
  -> /share/CACHEDEV1_DATA/Pouch/minio/sky-backups
```

The public DNS record is grey-cloud. Cloudflare is authoritative DNS but never
enters the data path. The existing rathole `storage` service carries all TLS on
port 443 to Caddy, so this hostname doesn't need a second relay service. Caddy
terminates TLS and preserves the request headers required by S3 SigV4.

LAN clients resolve `pouch.pod.haus` to bilby and take the shorter Caddy to
kangaroo path. Remote clients resolve it to kookaburra's reserved IP.

## Provisioning and credentials

Terraform owns the whole identity chain:

- `Pouch MinIO Root` in 1Password, generated once for the server and aliased
  Terraform provider;
- the private `sky-backups` bucket, with S3 versioning disabled;
- the `sky-backups` IAM user, policy, and revocable service account;
- the `Sky Backups` 1Password login containing the S3 access key, secret key,
  repository URL, region, and restic encryption password.

Sky never receives the MinIO root credential. Her policy grants object
read/write/delete plus list and location operations on `sky-backups` only.

The `Sky Backups` 1Password item is the Terraform-owned source of truth for
the client configuration:

```dotenv
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
RESTIC_REPOSITORY=s3:https://pouch.pod.haus/sky-backups
RESTIC_PASSWORD=...
AWS_DEFAULT_REGION=us-east-1
```

The repository was initialized during deployment verification, so the client
must not run `restic init` again. Configure the backup and retention schedule
on Sky's client. Don't enable MinIO bucket versioning: restic owns snapshot
retention, and S3 versions would retain packs that restic has pruned.

After each successful backup, the client must report to Gatus:

```sh
restic backup /path/to/data && \
  curl --fail --silent --show-error --request POST \
    --header "Authorization: Bearer ${GATUS_HEARTBEAT_PUSH_TOKEN}" \
    'https://gatus.pod.haus/api/v1/endpoints/backup_sky-laptop/external?success=true'
```

Source `GATUS_HEARTBEAT_PUSH_TOKEN` from the client-side secret store before
the job runs; its value is the 1Password Homelab item `Gatus Heartbeat Push
Token`. Do not put the literal token in a script, service definition, or this
repository. The `&&` is load-bearing: only a successful restic process refreshes
the dead-man switch. Gatus alerts after 168 hours without a success.

## Operation

The container has no CPU or memory limit. Backups are bursty and kangaroo has
enough headroom to let MinIO use the host normally. Docker's healthcheck probes
MinIO's live endpoint and kangaroo's existing autoheal container restarts it on
a sustained failure. There are no service-specific resource alerts.

The console port is not published. Terraform reaches the admin API through
`https://pouch.pod.haus`; Sky's scoped key reaches only the S3 operations her
repository needs.

The public Gatus exception covers only
`/api/v1/endpoints/backup_sky-laptop/external`. Cloudflare Access still protects
the Gatus dashboard and every other route, while the push path requires the
Gatus bearer token.

## Checks

```sh
curl -fsS https://pouch.pod.haus/minio/health/live
restic snapshots
restic check
```

An external-path check can force the kookaburra route from bilby:

```sh
curl --resolve pouch.pod.haus:443:170.64.241.136 \
  -fsS https://pouch.pod.haus/minio/health/live
```

## Recovery

Pouch holds this additional backup copy and is deliberately not backed up to
Jump. If the container or its configuration is lost while Pouch survives,
redeploy the stack and run Terraform to recreate the bucket and IAM state. If
Pouch itself is lost, the repository is lost with it; create a new empty bucket
and initialize a new restic repository from Sky's source data.

The MinIO system metadata lives beside the objects under the dedicated data
root. Don't edit, move, or restore individual files underneath it.
