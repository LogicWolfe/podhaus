#!/bin/sh
# Render the rathole config from a committed template, substituting
# secrets from env (RATHOLE_TOKEN / RATHOLE_NOISE_LOCAL_PRIVATE_KEY /
# RATHOLE_NOISE_REMOTE_PUBLIC_KEY), then exec rathole. On kookaburra it
# also discovers DigitalOcean's anchor IPv4 from instance metadata. The
# Reserved IP maps to that anchor, which lets rathole own anchor:22 while
# host sshd owns the droplet's ordinary public IPv4:22.
set -eu

TEMPLATE="${RATHOLE_CONFIG_TEMPLATE:?set RATHOLE_CONFIG_TEMPLATE}"
RENDERED=/run/rathole.toml

if [ "${RATHOLE_DISCOVER_ANCHOR:-0}" = "1" ]; then
  RATHOLE_ANCHOR_IPV4="$(
    curl -fsS --max-time 5 \
      http://169.254.169.254/metadata/v1/interfaces/public/0/anchor_ipv4/address
  )"
  case "$RATHOLE_ANCHOR_IPV4" in
    ''|*[!0-9.]*)
      echo "invalid DigitalOcean anchor IPv4: $RATHOLE_ANCHOR_IPV4" >&2
      exit 1
      ;;
  esac
  export RATHOLE_ANCHOR_IPV4
fi

envsubst '${RATHOLE_TOKEN} ${RATHOLE_GIT_TOKEN} ${RATHOLE_NOISE_LOCAL_PRIVATE_KEY} ${RATHOLE_NOISE_REMOTE_PUBLIC_KEY} ${RATHOLE_ANCHOR_IPV4} ${RATHOLE_PUBLIC_TLS_TOKEN} ${RATHOLE_FORGEJO_SSH_TOKEN} ${RATHOLE_PROTECTED_HTTP_TOKEN} ${RATHOLE_BILBY_SSH_TOKEN} ${RATHOLE_VOLTAIRE_SSH_TOKEN} ${NUMBAT_APPLICATION_IPV4} ${NUMBAT_RELAY_IPV4}' \
  < "$TEMPLATE" > "$RENDERED"

exec rathole "$RENDERED"
