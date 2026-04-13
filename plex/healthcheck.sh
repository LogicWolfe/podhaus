#!/bin/sh
# Runs inside the plex container every 60s.
# Fails if Plex API is down or critical remote mounts are unreadable.
#
# /config itself is a local bind mount to /var/lib/plex-local on the host
# (post Phase 6 pivot — see alligator-bilby-migration.md). The only mounts
# that can fail independently of local disk are the Pouch NFS bind mounts
# for media files and BIF scrubbing thumbnails. Check both.
set -e

curl -sf http://localhost:32400/identity > /dev/null

# Pouch NFS mount — media files (bind mount from /mnt/pouch on host)
ls /Users/Shared/Pouch/Movies > /dev/null

# BIF scrubbing thumbnails — bind mount from /mnt/pouch/plex-video-thumbnails
# on host into the config tree. Broken mount = broken scrubbing, so autoheal
# should notice.
ls "/config/Library/Application Support/Plex Media Server/Media/localhost" > /dev/null
