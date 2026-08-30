#!/usr/bin/env bash
# chattr +i on the BARE mountpoints given as arguments, so a missed mount
# makes Docker's bind-source auto-create fail loudly instead of silently
# writing real data to the host's own disk (2026-05-23 postmortem). The bit
# lives on the underlying root-filesystem inode, which the real volume
# shadows when mounted — a non-recursive bind of / exposes the bare dirs
# (without their overlays), so the bit can be set on a live host without
# disturbing running containers. Mounting over a +i dir is unaffected.
#
# Run by ansible/roles/storage_binds via `script:`. Output contract for the
# task's changed_when: TRIPWIRE-SET = bit newly set, TRIPWIRE-SWEPT = empty
# auto-create debris removed, TRIPWIRE-OK = already correct (unchanged).
set -euo pipefail

if [ "$#" -eq 0 ]; then
    echo "usage: chattr-tripwire.sh <bare-mountpoint>..." >&2
    exit 2
fi

trip=$(mktemp -d)
mount --bind / "$trip"
trap 'umount "$trip" 2>/dev/null || umount -l "$trip"; rmdir "$trip"' EXIT

for mp in "$@"; do
    d="$trip/${mp#/}"
    if [ ! -d "$d" ]; then
        # Fresh host. Created only when absent: chmod/chown on an existing
        # immutable dir returns EPERM, so the dir must never be re-touched.
        mkdir -p "$d"
        chmod 0755 "$d"
    fi

    # Anything that holds bytes means something wrote to local disk while
    # the volume was unmounted. That needs a human, not a chattr: fail the
    # play loudly. (The old installer warned and carried on — a scrolled-past
    # warning is how this state stays invisible.)
    if [ -n "$(find "$d" -mindepth 1 ! -type d -print -quit)" ]; then
        echo "ERROR: bare $mp holds files while unmounted — possible local-disk stub contamination; inspect before setting +i" >&2
        exit 1
    fi

    # Empty directory trees are not contamination, they are the exact debris
    # Docker leaves when it auto-creates a bind source against an unmounted
    # volume — the failure this tripwire exists to prevent. Sweeping them is
    # what lets the +i bit be set at all, since it must go on an empty dir.
    swept=""
    if [ -n "$(find "$d" -mindepth 1 -print -quit)" ]; then
        find "$d" -mindepth 1 -depth -type d -exec rmdir {} +
        swept="yes"
    fi

    if lsattr -d "$d" | awk '{print $1}' | grep -q i; then
        [ -n "$swept" ] && echo "TRIPWIRE-SWEPT $mp" || echo "TRIPWIRE-OK $mp"
    else
        chattr +i "$d"
        echo "TRIPWIRE-SET $mp"
    fi
done
