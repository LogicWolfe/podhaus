#!/bin/sh
# Check the Restic repository's committed snapshot objects in MinIO. Restic
# writes snapshots/<id> only when a backup reaches its commit point, including
# normal successful runs whose file tree is unchanged.
set -u

: "${SKY_BACKUPS_ENDPOINT:?SKY_BACKUPS_ENDPOINT is required}"
: "${SKY_BACKUPS_BUCKET:?SKY_BACKUPS_BUCKET is required}"
: "${SKY_BACKUPS_PREFIX:?SKY_BACKUPS_PREFIX is required}"
: "${SKY_BACKUPS_MAX_AGE:?SKY_BACKUPS_MAX_AGE is required}"
: "${SKY_BACKUPS_ACCESS_KEY:?SKY_BACKUPS_ACCESS_KEY is required}"
: "${SKY_BACKUPS_SECRET_KEY:?SKY_BACKUPS_SECRET_KEY is required}"
: "${GATUS_BASE_URL:?GATUS_BASE_URL is required}"
: "${GATUS_HEARTBEAT_PUSH_TOKEN:?GATUS_HEARTBEAT_PUSH_TOKEN is required}"

alias_name=sky-backups-monitor
target="${alias_name}/${SKY_BACKUPS_BUCKET}"
snapshot_pattern="/${SKY_BACKUPS_PREFIX}/snapshots/[0-9a-f]{64}$"
config_pattern="/${SKY_BACKUPS_PREFIX}/config$"
gatus_endpoint="${GATUS_BASE_URL}/api/v1/endpoints/backup_sky-restic-repository/external"

publish_result() {
    success="$1"
    detail="$2"

    curl --fail --silent --show-error --request POST --get \
        --header "Authorization: Bearer ${GATUS_HEARTBEAT_PUSH_TOKEN}" \
        --data-urlencode "success=${success}" \
        --data-urlencode "error=${detail}" \
        "$gatus_endpoint"
}

# Keep mc's generated alias file in tmpfs. The scoped S3 credential remains in
# the container environment and never gets written into the image or repo.
if ! mc alias set --quiet "$alias_name" "$SKY_BACKUPS_ENDPOINT" \
    "$SKY_BACKUPS_ACCESS_KEY" "$SKY_BACKUPS_SECRET_KEY" >/dev/null; then
    echo "sky-backups monitor: couldn't configure the MinIO client" >&2
    exit 1
fi

# Start at the bucket root so the ListBucket-only identity doesn't need to stat
# the prefix as an object. Depth four includes personal-laptop/config and
# personal-laptop/snapshots/<id>, but skips data/<prefix>/<pack> at depth five.
if ! objects=$(mc find "$target" --maxdepth 4 --print '{time} {}'); then
    echo "sky-backups monitor: couldn't list repository metadata objects" >&2
    exit 1
fi

if ! recent_objects=$(mc find "$target" --maxdepth 4 \
    --newer-than "$SKY_BACKUPS_MAX_AGE" --print '{time} {}'); then
    echo "sky-backups monitor: couldn't query recent repository metadata" >&2
    exit 1
fi

snapshots=$(printf '%s\n' "$objects" | grep -E "$snapshot_pattern" || true)
recent=$(printf '%s\n' "$recent_objects" | grep -E "$snapshot_pattern" || true)

if [ -n "$recent" ]; then
    latest=$(printf '%s\n' "$recent" | sort | tail -n 1)
    echo "sky-backups monitor: fresh committed snapshot: ${latest}"
    publish_result true "" || exit 1
    exit 0
fi

if [ -z "$snapshots" ]; then
    # A newly initialized repository gets the same seven-day window before its
    # first backup is due. The config object is written by `restic init` and is
    # the only safe clock available before the first snapshot exists.
    repository_config=$(printf '%s\n' "$objects" | grep -E "$config_pattern" || true)
    recent_config=$(printf '%s\n' "$recent_objects" | grep -E "$config_pattern" || true)
    if [ -n "$recent_config" ]; then
        echo "sky-backups monitor: repository is within its first-backup grace window: ${recent_config}"
        publish_result true "" || exit 1
        exit 0
    fi
    if [ -z "$repository_config" ]; then
        detail="The ${SKY_BACKUPS_BUCKET}/${SKY_BACKUPS_PREFIX} repository has no config or committed snapshot."
    else
        detail="No Restic snapshot was committed within ${SKY_BACKUPS_MAX_AGE} of repository initialization: ${repository_config}."
    fi
else
    latest=$(printf '%s\n' "$snapshots" | sort | tail -n 1)
    detail="Newest committed Restic snapshot is older than ${SKY_BACKUPS_MAX_AGE}: ${latest}."
fi

echo "sky-backups monitor: ${detail}" >&2
publish_result false "$detail"
exit 1
