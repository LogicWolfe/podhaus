#!/usr/bin/env bash
# Bilby host sshd: trust Pomerium's user CA. Password authentication
# remains available on Bilby's non-edge paths as fallback.
#
# Run: sudo ./bilby/host-sshd/install.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POMERIUM_CA_SRC="$HERE/../../pomerium/keys/user-ca.pub"
CA_DST="/etc/ssh/pomerium-user-ca.pub"
SSHD_CONFIG="/etc/ssh/sshd_config"
OLD_MARKER="# --- podhaus: Cloudflare Access browser-SSH CA (ssh.pod.haus) ---"
MARKER="# --- podhaus: Pomerium SSH user CA ---"

[ "$(id -u)" -eq 0 ] || { echo "must run as root (sudo)"; exit 1; }
[ -f "$POMERIUM_CA_SRC" ] || { echo "missing $POMERIUM_CA_SRC"; exit 1; }
ssh-keygen -l -f "$POMERIUM_CA_SRC" >/dev/null || { echo "invalid Pomerium CA pubkey"; exit 1; }

install -o root -g root -m 0644 "$POMERIUM_CA_SRC" "$CA_DST"
echo "installed $CA_DST"

if grep -qF "$OLD_MARKER" "$SSHD_CONFIG"; then
  sed -i "s|^${OLD_MARKER}$|${MARKER}|" "$SSHD_CONFIG"
elif ! grep -qF "$MARKER" "$SSHD_CONFIG"; then
  {
    echo ""
    echo "$MARKER"
    echo "TrustedUserCAKeys $CA_DST"
  } >> "$SSHD_CONFIG"
  echo "appended TrustedUserCAKeys block to $SSHD_CONFIG"
else
  echo "TrustedUserCAKeys block already present"
fi

sed -i "s|^TrustedUserCAKeys /etc/ssh/cloudflare_ca.pub$|TrustedUserCAKeys $CA_DST|" "$SSHD_CONFIG"
sed -i "s|^TrustedUserCAKeys /etc/ssh/podhaus_user_ca.pub$|TrustedUserCAKeys $CA_DST|" "$SSHD_CONFIG"

sshd -t
echo "sshd config valid"
systemctl reload sshd
rm -f /etc/ssh/cloudflare_ca.pub /etc/ssh/podhaus_user_ca.pub
echo "sshd reloaded with the Pomerium SSH user CA"
