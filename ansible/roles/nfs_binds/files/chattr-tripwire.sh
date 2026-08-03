#!/usr/bin/env bash
# chattr +i on the BARE /mnt/{pouch,jump} mountpoints, so a missed NFS
# mount makes Docker's bind-subdir auto-create fail loudly instead of
# silently writing real data to local disk (2026-05-23 postmortem). The
# bit lives on the underlying btrfs inode, which NFS shadows when
# mounted — a non-recursive bind of / exposes the bare dirs (without
# their NFS overlays), so the bit can be set on a live host without
# disturbing running containers. Mounting NFS over a +i dir is
# unaffected.
#
# Run by ansible/roles/nfs_binds via `script:`. Output contract for the
# task's changed_when: TRIPWIRE-SET = bit newly set (changed),
# TRIPWIRE-OK = already set (unchanged).
set -euo pipefail

trip=$(mktemp -d)
mount --bind / "$trip"
trap 'umount "$trip" 2>/dev/null || umount -l "$trip"; rmdir "$trip"' EXIT

for mp in mnt/pouch mnt/jump; do
    d="$trip/$mp"
    if [ ! -d "$d" ]; then
        # Fresh host. Created only when absent: chmod/chown on an existing
        # immutable dir returns EPERM, so the dir must never be re-touched.
        mkdir -p "$d"
        chmod 0755 "$d"
    fi
    if [ -n "$(ls -A "$d")" ]; then
        # Content on the bare dir means something wrote to local disk while
        # the share was unmounted. That needs a human, not a chattr: fail
        # the play loudly. (The old installer warned and carried on — a
        # scrolled-past warning is how this state stays invisible.)
        echo "ERROR: bare /$mp non-empty while unmounted — possible local-disk stub contamination; inspect before setting +i" >&2
        exit 1
    fi
    if lsattr -d "$d" | awk '{print $1}' | grep -q i; then
        echo "TRIPWIRE-OK /$mp"
    else
        chattr +i "$d"
        echo "TRIPWIRE-SET /$mp"
    fi
done
