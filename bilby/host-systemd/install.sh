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

echo "Installed. Verify:"
echo "  systemctl cat wait-for-qnap-nfs.service"
echo "  systemctl cat docker.service | grep -A2 'After=wait-for-qnap'"
echo "  systemctl cat mnt-pouch.automount | grep -A2 'StartLimit'"
echo "  systemctl cat mnt-jump.automount  | grep -A2 'StartLimit'"
