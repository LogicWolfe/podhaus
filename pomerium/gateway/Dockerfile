# Pomerium with one extra file: a static busybox, for the healthcheck in
# ../compose.yaml. The upstream image is distroless, so it has no shell and no
# HTTP client, and `pomerium health` reports only what the Go process says
# about its own components: it stays green while Envoy refuses every
# connection.
FROM busybox:stable-musl AS probe

FROM pomerium/pomerium:latest

ARG STACK_CONTENT_HASH=unset
ENV STACK_CONTENT_HASH=${STACK_CONTENT_HASH}

COPY --from=probe /bin/busybox /bin/busybox
