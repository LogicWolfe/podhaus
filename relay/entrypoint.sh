#!/bin/sh
# Render the rathole config from a committed template, substituting
# secrets from env (RATHOLE_TOKEN / RATHOLE_NOISE_LOCAL_PRIVATE_KEY /
# RATHOLE_NOISE_REMOTE_PUBLIC_KEY), then exec rathole. The template is
# bind-mounted read-only (directory bind); the rendered file lives only
# in the container. rathole has no native env interpolation, so this
# wrapper is how the noise keypair + token stay out of committed source.
set -eu

TEMPLATE="${RATHOLE_CONFIG_TEMPLATE:?set RATHOLE_CONFIG_TEMPLATE}"
RENDERED=/run/rathole.toml

envsubst '${RATHOLE_TOKEN} ${RATHOLE_NOISE_LOCAL_PRIVATE_KEY} ${RATHOLE_NOISE_REMOTE_PUBLIC_KEY}' \
  < "$TEMPLATE" > "$RENDERED"

exec rathole "$RENDERED"
