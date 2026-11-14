# Pomerium with one extra file: a static busybox, for the healthcheck in
# ../compose.yaml. The upstream image is distroless, so it has no shell and no
# HTTP client, and `pomerium health` reports only what the Go process says
# about its own components: it stays green while Envoy refuses every
# connection.
FROM busybox:stable-musl AS probe

# Pinned: releases from 0.34.0 leak one connection to their bundled Envoy every
# 30 seconds, about 110 MB a day, until the container fills its memory limit
# and stops answering. This is the last release that does not. The cause and
# the check a newer release has to pass before this pin comes off are in
# docs/networking.html#pomerium-pin.
FROM pomerium/pomerium:v0.33.6

ARG STACK_CONTENT_HASH=unset
ENV STACK_CONTENT_HASH=${STACK_CONTENT_HASH}

COPY --from=probe /bin/busybox /bin/busybox
