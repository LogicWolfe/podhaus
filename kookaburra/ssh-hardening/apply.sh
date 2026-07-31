#!/bin/bash
# Kookaburra SSH hardening — auto-allowlist successful-auth IPs to
# bypass MaxStartups pressure WITHOUT banning anyone. Public SSH stays
# open as a recovery path; scanners and fumbled-key agents are
# rate-limited (10/min per source IP) but never blocked. Successful
# pubkey auth promotes the source IP into nftables `ssh_trusted` with
# a 30-day rolling timeout — refreshed on every subsequent auth from
# that IP, so active IPs never expire.
#
# Idempotent: safe to re-run. kookaburra_bootstrap invokes it on every
# bootstrap pass so DR / rebuild reproduces the state.

set -euo pipefail

BILBY_WAN="${BILBY_WAN:-144.6.147.203}"   # seed: bilby's home WAN
METADATA=http://169.254.169.254/metadata/v1/interfaces/public/0
PUBLIC_IPV4="$(curl -fsS --max-time 5 "$METADATA/ipv4/address")"
ANCHOR_IPV4="$(curl -fsS --max-time 5 "$METADATA/anchor_ipv4/address")"

valid_ipv4() {
  local value=$1 octet
  [[ $value =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || return 1
  IFS=. read -r -a octets <<< "$value"
  for octet in "${octets[@]}"; do
    (( 10#$octet <= 255 )) || return 1
  done
}

valid_ipv4 "$PUBLIC_IPV4" || {
  echo "invalid DigitalOcean public IPv4: $PUBLIC_IPV4" >&2
  exit 1
}
valid_ipv4 "$ANCHOR_IPV4" || {
  echo "invalid DigitalOcean anchor IPv4: $ANCHOR_IPV4" >&2
  exit 1
}
[[ $PUBLIC_IPV4 != "$ANCHOR_IPV4" ]] || {
  echo "public and anchor IPv4 unexpectedly match: $PUBLIC_IPV4" >&2
  exit 1
}

echo "[ssh-harden] public=$PUBLIC_IPV4 anchor=$ANCHOR_IPV4"

echo "[ssh-harden] sshd config drop-in"
mkdir -p /etc/ssh/sshd_config.d
cat > /etc/ssh/sshd_config.d/99-podhaus.conf <<EOF
# podhaus SSH hardening — applied by kookaburra_bootstrap.
# Password auth disabled: scanners can't even try a password, so
# they drop quickly. (Pubkey auth + the nftables allowlist below
# carries the auth + rate-limit story.)
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
ListenAddress $PUBLIC_IPV4:22
# Generous MaxStartups — the per-source rate-limit lives at the
# nftables layer so this just needs enough headroom for legit bursts.
MaxStartups 200:30:1000
EOF
chmod 644 /etc/ssh/sshd_config.d/99-podhaus.conf
sshd -t

echo "[ssh-harden] nftables ssh_trusted set + per-IP rate-limit"
# Atomically replace the podhaus table. Set has a 30d timeout per
# element — successful auths refresh; stale entries expire.
nft delete table inet podhaus 2>/dev/null || true
nft -f - <<NFT
table inet podhaus {
  set ssh_trusted {
    type ipv4_addr
    flags timeout
    timeout 30d
    elements = { $BILBY_WAN }
  }
  chain ssh_input {
    type filter hook input priority -10; policy accept;
    # Already-established TCP flows always pass (existing sessions).
    tcp dport 22 ct state established,related accept
    # Reserved-IP traffic lands on DigitalOcean's anchor address.
    # rathole, not host sshd, owns this socket. Do not apply host SSH's
    # scanner rate-limit or PAM trusted-source semantics to Git clients.
    ip daddr $ANCHOR_IPV4 tcp dport 22 accept
    # No port-22 service belongs on another local destination.
    ip daddr != $PUBLIC_IPV4 tcp dport 22 drop
    # Trusted IPs bypass rate-limit entirely.
    tcp dport 22 ip saddr @ssh_trusted accept
    # Everyone else: rate-limited to 10 new conn/min per source IP.
    # No ban — over the rate, packets just drop until the bucket
    # refills. Legitimate fumbled-key agents fit within 10/min;
    # internet scanners doing hundreds/min do not.
    # Expire scanner identities. Without a timeout this dynamic set eventually
    # fills its 65,535-entry default and drops every previously unseen source,
    # including legitimate recovery clients.
    tcp dport 22 ct state new meter ssh_rate size 65535 { ip saddr timeout 1h limit rate 10/minute } accept
    tcp dport 22 ct state new drop
  }
}
NFT

echo "[ssh-harden] PAM open_session hook to add source IP to trusted"
cat > /usr/local/bin/ssh-trust-add.sh <<'SH'
#!/bin/bash
# Runs on every PAM open_session (i.e. after successful auth, before
# the user's shell). Adds the remote IP to ssh_trusted, refreshing
# its 30-day timeout. IPv4 only for now.
set -e
[ "${PAM_TYPE:-}" = "open_session" ] || exit 0
[ -n "${PAM_RHOST:-}" ] || exit 0
case "$PAM_RHOST" in
  *.*.*.*)
    /usr/sbin/nft "delete element inet podhaus ssh_trusted { $PAM_RHOST }" 2>/dev/null || true
    /usr/sbin/nft "add element inet podhaus ssh_trusted { $PAM_RHOST }" 2>/dev/null || true
    ;;
esac
exit 0
SH
chmod 755 /usr/local/bin/ssh-trust-add.sh

# Hook into /etc/pam.d/sshd idempotently
if ! grep -q "ssh-trust-add.sh" /etc/pam.d/sshd; then
  printf 'session optional pam_exec.so /usr/local/bin/ssh-trust-add.sh\n' >> /etc/pam.d/sshd
fi

echo "[ssh-harden] persist nftables across reboot"
mkdir -p /etc/nftables/podhaus
nft list table inet podhaus > /etc/nftables/podhaus/ssh-allowlist.nft
if [ ! -f /etc/sysconfig/nftables.conf ] || ! grep -q "podhaus" /etc/sysconfig/nftables.conf; then
  printf 'include "/etc/nftables/podhaus/*.nft"\n' >> /etc/sysconfig/nftables.conf
fi
systemctl enable --now nftables.service 2>&1 | tail -3 || true

echo "[ssh-harden] reload sshd"
systemctl reload sshd

echo "[ssh-harden] verify"
sshd -T 2>/dev/null | grep -iE "^(listenaddress|password|kbdinteractive|maxstartups|permitroot)"
ss -ltnp | grep "$PUBLIC_IPV4:22"
echo "current ssh_trusted elements:"
nft list set inet podhaus ssh_trusted 2>/dev/null | grep elements
echo "[ssh-harden] DONE"
