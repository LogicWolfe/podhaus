#!/bin/sh
# Runs inside the plex container every 60s.
# Fails if Plex API is down or critical remote mounts are unreadable.
#
# /config itself is a local bind mount to /var/lib/plex-local on the host.
# The mounts that
# can fail independently of local disk are the media files (Pouch NFS) and
# the BIF scrubbing thumbnails (Jump NFS — a separate export/volume). Check
# both.
#
# Sentinel-marker check (not `ls`): the marker .podhaus-share-mounted
# lives on the QNAP NFS share itself at every bind-source path, so it's
# absent on a bare btrfs stub (the case caught by the 2026-05-23 post-
# reboot incident, where /mnt/pouch wasn't NFS-mounted and Docker
# bind-mounted the empty stub). `[ -e ]` is a stat — never blocks like
# `ls` could on a soft NFS stall. See
# docs/postmortems/2026-05-23-pouch-jump-mount-failure.md.
set -e

curl -sf http://localhost:32400/identity > /dev/null

# Pouch NFS mount — media files (bind from /mnt/pouch on host).
[ -e /Users/Shared/Pouch/.podhaus-share-mounted ]

# BIF scrubbing thumbnails — bind from /mnt/jump/plex-video-thumbnails
# on host. If Jump is unmounted, the chattr +i tripwire on /mnt/jump
# blocks Docker's subdir auto-create entirely, so Plex won't even start
# in that state. This check guards against the post-start case (Jump
# went away mid-run).
[ -e "/config/Library/Application Support/Plex Media Server/Media/localhost/.podhaus-share-mounted" ]
