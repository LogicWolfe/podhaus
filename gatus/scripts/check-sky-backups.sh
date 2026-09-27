#!/bin/sh
# Check the Restic repository's committed snapshot objects in RustFS. Restic
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
target="${alias_name}/${SKY_BACKUPS_BUCKET}/${SKY_BACKUPS_PREFIX}"
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

# Keep rc's generated alias file in tmpfs. The scoped S3 credential remains in
# the container environment and never gets written into the image or repo.
if ! rc alias set "$alias_name" "$SKY_BACKUPS_ENDPOINT" \
    "$SKY_BACKUPS_ACCESS_KEY" "$SKY_BACKUPS_SECRET_KEY" >/dev/null; then
    echo "sky-backups monitor: couldn't configure the RustFS client" >&2
    exit 1
fi

# The S3 list request begins at the repository prefix. It returns config plus
# snapshots at depth two, while excluding the data-pack objects below it.
if ! objects=$(rc object find --json "$target" --maxdepth 2); then
    echo "sky-backups monitor: couldn't list repository metadata objects" >&2
    exit 1
fi

age_number=${SKY_BACKUPS_MAX_AGE%?}
age_unit=${SKY_BACKUPS_MAX_AGE#"$age_number"}
case "$age_number" in
    ''|*[!0-9]*)
        echo "sky-backups monitor: invalid maximum age: ${SKY_BACKUPS_MAX_AGE}" >&2
        exit 1
        ;;
esac
case "$age_unit" in
    s) age_multiplier=1 ;;
    m) age_multiplier=60 ;;
    h) age_multiplier=3600 ;;
    d) age_multiplier=86400 ;;
    w) age_multiplier=604800 ;;
    *)
        echo "sky-backups monitor: invalid maximum age: ${SKY_BACKUPS_MAX_AGE}" >&2
        exit 1
        ;;
esac
max_age_seconds=$((age_number * age_multiplier))

# rc's JSON gives each object's server-side RFC3339 modification time. jq
# validates it before comparing an epoch value, so a changed response shape or
# timestamp can never make a repository look fresh.
if ! repository=$(printf '%s' "$objects" | jq -ce \
    --arg prefix "$SKY_BACKUPS_PREFIX" \
    --argjson max_age_seconds "$max_age_seconds" '
    def snapshot:
        (.key | startswith($prefix + "/snapshots/")) and
        ((.key | ltrimstr($prefix + "/snapshots/")) | test("^[0-9a-f]{64}$"));
    def timestamp:
        if (.last_modified | type) == "string" then
            .last_modified | fromdateiso8601
        else
            error("repository metadata object has no last_modified timestamp")
        end;
    if (.matches | type) != "array" then
        error("RustFS client response has no matches array")
    else
        [
            .matches[] |
            if (.key | type) != "string" then
                error("repository metadata object has no key")
            else
                .
            end |
            select(.key == ($prefix + "/config") or snapshot) |
            . + {modified_epoch: timestamp}
        ] as $metadata |
        [$metadata[] | select(snapshot)] as $snapshots |
        [$metadata[] | select(.key == ($prefix + "/config"))] as $configs |
        (now - $max_age_seconds) as $cutoff |
        {
            latest_snapshot: ($snapshots | max_by(.modified_epoch)),
            fresh_snapshot: ($snapshots | map(select(.modified_epoch > $cutoff)) | max_by(.modified_epoch)),
            latest_config: ($configs | max_by(.modified_epoch)),
            fresh_config: ($configs | map(select(.modified_epoch > $cutoff)) | max_by(.modified_epoch))
        }
    end'); then
    echo "sky-backups monitor: couldn't parse repository metadata" >&2
    exit 1
fi

if ! state=$(printf '%s' "$repository" | jq -er '
    if .fresh_snapshot != null then "fresh-snapshot"
    elif .latest_snapshot != null then "stale-snapshot"
    elif .fresh_config != null then "fresh-config"
    elif .latest_config != null then "stale-config"
    else "missing-repository"
    end'); then
    echo "sky-backups monitor: couldn't classify repository metadata" >&2
    exit 1
fi

case "$state" in
    fresh-snapshot)
        if ! latest=$(printf '%s' "$repository" | jq -er \
            '"\(.fresh_snapshot.last_modified) \(.fresh_snapshot.key)"'); then
            echo "sky-backups monitor: couldn't read fresh snapshot metadata" >&2
            exit 1
        fi
        echo "sky-backups monitor: fresh committed snapshot: ${latest}"
        publish_result true "" || exit 1
        exit 0
        ;;
    fresh-config)
        if ! config=$(printf '%s' "$repository" | jq -er \
            '"\(.fresh_config.last_modified) \(.fresh_config.key)"'); then
            echo "sky-backups monitor: couldn't read fresh repository configuration" >&2
            exit 1
        fi
        echo "sky-backups monitor: repository is within its first-backup grace window: ${config}"
        publish_result true "" || exit 1
        exit 0
        ;;
    stale-snapshot)
        if ! latest=$(printf '%s' "$repository" | jq -er \
            '"\(.latest_snapshot.last_modified) \(.latest_snapshot.key)"'); then
            echo "sky-backups monitor: couldn't read stale snapshot metadata" >&2
            exit 1
        fi
        detail="Newest committed Restic snapshot is older than ${SKY_BACKUPS_MAX_AGE}: ${latest}."
        ;;
    stale-config)
        if ! config=$(printf '%s' "$repository" | jq -er \
            '"\(.latest_config.last_modified) \(.latest_config.key)"'); then
            echo "sky-backups monitor: couldn't read repository configuration metadata" >&2
            exit 1
        fi
        detail="No Restic snapshot was committed within ${SKY_BACKUPS_MAX_AGE} of repository initialization: ${config}."
        ;;
    missing-repository)
        detail="The ${SKY_BACKUPS_BUCKET}/${SKY_BACKUPS_PREFIX} repository has no config or committed snapshot."
        ;;
    *)
        echo "sky-backups monitor: unknown repository state: ${state}" >&2
        exit 1
        ;;
esac

echo "sky-backups monitor: ${detail}" >&2
publish_result false "$detail"
exit 1
