#!/bin/bash
# Nightly logical dump of HyperDX's mongo database (dashboards, alerts,
# source defs, ingestion key — tiny but hand-built, not reconstructible
# from telemetry). Keeps the latest ~14 archives in /dump; Backrest's
# 04:00 restic run captures them.
#
# Run via ofelia on the clickstack-mongo container at 03:50 AWST. Its exit
# status is the verdict: ofelia's "Job stop" line records it, and the
# ClickStack Mongo Dump check in Gatus reads that line from ClickStack.
set -euo pipefail

ARCHIVE="/dump/hyperdx-$(date +%F).archive"

mongodump --uri="mongodb://localhost:27017/hyperdx" --gzip --archive="$ARCHIVE"
ls -1t /dump/hyperdx-*.archive | tail -n +15 | xargs -r rm -f
