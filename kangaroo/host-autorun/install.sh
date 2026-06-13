#!/bin/sh
# Install kangaroo's boot hook (autorun.sh) onto the QNAP config DOM, so
# Container Station's user Docker engine — and therefore the kangaroo
# stacks' restart:unless-stopped containers — come back after a reboot or
# a Container Station upgrade. Idempotent; safe to re-run.
#
# Runs ON kangaroo. kangaroo_bootstrap ships this dir over and invokes it;
# it can also be run by hand from an SSH session on kangaroo.
#
# Why a DOM autorun.sh and not crontab: kangaroo's cron is BusyBox crond,
# which silently ignores the `@reboot` nickname, so the previous
# crontab-based hook never ran. /etc/init.d/init_nas.sh runs
# /tmp/config/autorun.sh (off the boot DOM) at startup when
# `Misc Autorun`=TRUE — the native QNAP boot hook, upgrade-surviving.
set -eu
PATH=/usr/bin:/bin:/sbin:/usr/sbin

SRC_DIR=$(cd "$(dirname "$0")" && pwd)
MARK="# >>> podhaus kangaroo autorun (managed by kangaroo/host-autorun) >>>"
MNT=/tmp/config

# Derive the boot DOM's config partition exactly as init_nas.sh does
# (hal_app reports the boot physical device; partition 6 is the config FS).
BOOT_DEV=$(/sbin/hal_app --get_boot_pd port_id=0)
DOM_PART="${BOOT_DEV}6"
[ -b "$DOM_PART" ] || { echo "config DOM partition $DOM_PART not a block device" >&2; exit 1; }

# Mount the DOM config partition (normally only mounted transiently at
# boot). Track whether we mounted it so we leave it as we found it.
mkdir -p "$MNT"
MOUNTED_BY_US=0
if ! grep -q " $MNT " /proc/mounts; then
    mount "$DOM_PART" -t ext2 "$MNT"
    MOUNTED_BY_US=1
fi

DEST="$MNT/autorun.sh"
# Never clobber a foreign autorun.sh we didn't write.
if [ -f "$DEST" ] && ! grep -qF "$MARK" "$DEST"; then
    echo "Refusing to overwrite existing non-podhaus $DEST — inspect manually." >&2
    [ "$MOUNTED_BY_US" = 1 ] && umount "$MNT"
    exit 1
fi
cp "$SRC_DIR/autorun.sh" "$DEST"
chmod 0755 "$DEST"
sync
[ "$MOUNTED_BY_US" = 1 ] && umount "$MNT"

# Enable the boot hook (persisted in /etc/config/uLinux.conf on md9).
setcfg Misc Autorun TRUE

# Remove the dead `@reboot` crontab line from earlier bootstrap runs.
CRON=/etc/config/crontab
CRON_MARKER="# komodo-periphery autostart (managed by kangaroo_bootstrap)"
if grep -qF "$CRON_MARKER" "$CRON" 2>/dev/null; then
    sed -i "/${CRON_MARKER}/,+1d" "$CRON"
    crontab "$CRON"
    /etc/init.d/crond.sh restart >/dev/null 2>&1 || true
    echo "removed dead @reboot crontab line"
fi

echo "autorun installed at DOM:$DOM_PART -> $DEST ; Misc Autorun=$(getcfg Misc Autorun -d 0)"
