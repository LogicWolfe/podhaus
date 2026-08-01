#!/usr/bin/env bash
# bilby host sshd: trust the Cloudflare and Pomerium user CAs. Password
# authentication remains available on Bilby's non-edge paths as fallback.
#
# Both public keys are Terraform outputs and safe to keep in git.
#
# Run: sudo ./bilby/host-sshd/install.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CF_CA_SRC="$HERE/cloudflare_ca.pub"
POMERIUM_CA_SRC="$HERE/pomerium_ca.pub"
CA_DST="/etc/ssh/podhaus_user_ca.pub"
SSHD_CONFIG="/etc/ssh/sshd_config"
MARKER="# --- podhaus: Cloudflare Access browser-SSH CA (ssh.pod.haus) ---"

[ "$(id -u)" -eq 0 ] || { echo "must run as root (sudo)"; exit 1; }
[ -f "$CF_CA_SRC" ] || { echo "missing $CF_CA_SRC"; exit 1; }
[ -f "$POMERIUM_CA_SRC" ] || { echo "missing $POMERIUM_CA_SRC"; exit 1; }
ssh-keygen -l -f "$CF_CA_SRC" >/dev/null || { echo "invalid Cloudflare CA pubkey"; exit 1; }
ssh-keygen -l -f "$POMERIUM_CA_SRC" >/dev/null || { echo "invalid Pomerium CA pubkey"; exit 1; }

install -o root -g root -m 0644 /dev/null "$CA_DST"
cat "$CF_CA_SRC" "$POMERIUM_CA_SRC" > "$CA_DST"
echo "installed $CA_DST"

if ! grep -qF "$MARKER" "$SSHD_CONFIG"; then
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

sshd -t
echo "sshd config valid"
systemctl reload sshd
echo "sshd reloaded with the podhaus SSH user CAs"
