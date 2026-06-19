#!/bin/bash
# Nightly logical dump of HyperDX's mongo database (dashboards, alerts,
# source defs, ingestion key — tiny but hand-built, not reconstructible
# from telemetry). Keeps the latest ~14 archives in /dump; Backrest's
# 04:00 restic run captures them.
#
# Run via ofelia on the clickstack-mongo container at 03:50 AWST. Was an
# inline `bash -c` ofelia label; promoted to a script so it can push a
# dead-man's-switch heartbeat to Gatus (see observability_clickstack-mongo-dump).
# The mongo image ships neither wget nor curl, so the push uses a bash
# /dev/tcp raw HTTP request.
set -euo pipefail

ARCHIVE="/dump/hyperdx-$(date +%F).archive"

mongodump --uri="mongodb://localhost:27017/hyperdx" --gzip --archive="$ARCHIVE"
ls -1t /dump/hyperdx-*.archive | tail -n +15 | xargs -r rm -f

# Heartbeat push. Tolerate any failure — the dump above already succeeded,
# and a missing push is exactly what the dead-man's-switch should surface.
push_heartbeat() {
    local token="${GATUS_OFELIA_PUSH_TOKEN:-}"
    [ -n "$token" ] || return 0
    exec 3<>/dev/tcp/gatus/8080 || return 0
    printf 'POST /api/v1/endpoints/observability_clickstack-mongo-dump/external?success=true HTTP/1.0\r\nHost: gatus:8080\r\nAuthorization: Bearer %s\r\nContent-Length: 0\r\nConnection: close\r\n\r\n' "$token" >&3
    cat <&3 >/dev/null
    exec 3>&-
}
push_heartbeat || echo "[mongo-dump] WARN: gatus heartbeat push failed"
