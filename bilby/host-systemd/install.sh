#!/usr/bin/env bash
# Install bilby host-level systemd units that harden NFS auto-recovery.
# Idempotent — re-run after editing any unit file.
#
# Layered defence:
#   1. wait-for-qnap-nfs.service holds docker.service start until TCP/2049
#      on the QNAP responds (or 180 s timeout — then docker starts anyway
#      and individual NFS-bind containers fail loudly).
#   2. docker.service.d/ drop-in wires the wait into docker's startup.
#   3. mnt-{pouch,jump}.automount.d/ drop-ins disable systemd's start-rate
#      limit so an automount unit can never go to permanently-failed state
#      (the 2026-05-30 failure mode).
#   4. firewalld: stages the declarative zone + custom service XML from
#      bilby/firewalld/ (source of truth) and reloads. The XML is the
#      config; this script just installs and reloads it.
#
# Run as root on bilby. Requires sudo.

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
DEST=/etc/systemd/system

install -m 0644 "$REPO_DIR/wait-for-qnap-nfs.service" "$DEST/wait-for-qnap-nfs.service"

install -d -m 0755 "$DEST/docker.service.d"
install -m 0644 "$REPO_DIR/docker.service.d/10-wait-for-qnap.conf" "$DEST/docker.service.d/10-wait-for-qnap.conf"

install -d -m 0755 "$DEST/mnt-pouch.automount.d"
install -m 0644 "$REPO_DIR/mnt-pouch.automount.d/10-no-rate-limit.conf" "$DEST/mnt-pouch.automount.d/10-no-rate-limit.conf"

install -d -m 0755 "$DEST/mnt-jump.automount.d"
install -m 0644 "$REPO_DIR/mnt-jump.automount.d/10-no-rate-limit.conf" "$DEST/mnt-jump.automount.d/10-no-rate-limit.conf"

systemctl daemon-reload
systemctl enable wait-for-qnap-nfs.service

# --- NFS-bind stub tripwire + share sentinels (2026-05-23 postmortem) ---
# Two host/NAS-side defenses applied by hand in the 2026-05-23 remediation
# and never codified. Folding them in makes them reproducible: a Pouch
# RAID rebuild wipes the sentinels, and a fresh host has no tripwire.

# 1. chattr +i on the BARE /mnt/{pouch,jump} mountpoints, so a missed NFS
#    mount makes Docker's bind-subdir auto-create fail loudly instead of
#    silently writing real data to local disk. The bit lives on the
#    underlying btrfs inode, which NFS shadows when mounted — a
#    non-recursive bind of / exposes the bare dirs (without their NFS
#    overlays), so we set +i idempotently on a live host without
#    disturbing running containers. Mounting NFS over a +i dir is
#    unaffected.
TRIP=$(mktemp -d)
mount --bind / "$TRIP"
for mp in mnt/pouch mnt/jump; do
    d="$TRIP/$mp"
    install -d -m 0755 "$d"
    if [ -n "$(ls -A "$d" 2>/dev/null)" ]; then
        echo "  WARNING: bare /$mp non-empty while unmounted — possible local-disk stub contamination; NOT setting +i. Inspect." >&2
    elif chattr +i "$d"; then
        echo "  tripwire: +i ensured on /$mp"
    else
        echo "  WARNING: chattr +i /$mp failed" >&2
    fi
done
umount "$TRIP" 2>/dev/null || umount -l "$TRIP"
rmdir "$TRIP"

# 2. Sentinel markers on the real NFS shares. Each NFS bind-source subpath
#    a stack uses gets a .podhaus-share-mounted file ON the share, so a
#    container's healthcheck can prove it bound the real share, not a
#    local stub. Touching the path triggers the automount. Keep this list
#    in sync with NFS binds (AGENTS.md: drop a marker when you add one).
# Forgejo keeps SQLite/config on local NVMe and repositories on Jump.
# Provision both sides here so a fresh bilby has the exact ownership the
# rootless image and QNAP's all_squash mapping expect.
install -d -o 1000 -g 100 -m 0750 \
    /var/lib/forgejo /var/lib/forgejo/data /var/lib/forgejo/data/log \
    /var/lib/forgejo/config
install -d -o 1000 -g 100 -m 0750 \
    /mnt/jump/forgejo \
    /mnt/jump/forgejo/repositories \
    /mnt/jump/forgejo/lfs \
    /mnt/jump/forgejo/attachments \
    /mnt/jump/forgejo/repo-archives

for p in /mnt/pouch /mnt/jump /mnt/jump/backups /mnt/jump/paperless \
         /mnt/jump/paperless/documents /mnt/jump/plex-video-thumbnails \
         /mnt/jump/forgejo; do
    if [ -d "$p" ] && touch "$p/.podhaus-share-mounted" 2>/dev/null; then
        echo "  sentinel: $p/.podhaus-share-mounted"
    else
        echo "  WARNING: could not write sentinel at $p (share unmounted/unreachable or path missing)" >&2
    fi
done

# --- firewalld declarative config (bilby/firewalld/) ---
# The XML under bilby/firewalld/ is the source of truth for bilby's
# firewall; this stages it the same way the systemd units above are
# staged, then reloads. Custom service definitions are installed BEFORE
# the zone so the zone never references an undefined service. A bad edit
# is caught by --check-config before any reload (reloads don't drop
# established connections, so ssh survives regardless).
if command -v firewall-cmd >/dev/null 2>&1; then
  FW_SRC="$REPO_DIR/../firewalld"
  install -d -m 0755 /etc/firewalld/services
  for svc in "$FW_SRC"/services/*.xml; do
    install -m 0644 "$svc" "/etc/firewalld/services/$(basename "$svc")"
    echo "  firewalld service: $(basename "$svc")"
  done
  install -m 0644 "$FW_SRC/zones/public.xml" /etc/firewalld/zones/public.xml
  echo "  firewalld zone: public.xml"
  if firewall-cmd --check-config; then
    firewall-cmd --reload
    echo "  firewalld reloaded"
  else
    echo "  ERROR: firewall-cmd --check-config failed — NOT reloading; fix the XML" >&2
    exit 1
  fi
else
  echo "  WARNING: firewall-cmd not found — skipping firewalld config" >&2
fi

echo "Installed. Verify:"
echo "  systemctl cat wait-for-qnap-nfs.service"
echo "  firewall-cmd --list-services   # ssh mdns dhcpv6-client plex music-assistant"
echo "  systemctl cat docker.service | grep -A2 'After=wait-for-qnap'"
echo "  systemctl cat mnt-pouch.automount | grep -A2 'StartLimit'"
echo "  systemctl cat mnt-jump.automount  | grep -A2 'StartLimit'"
