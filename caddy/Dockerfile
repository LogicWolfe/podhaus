# Caddy + the caddy-dns/cloudflare module (needed for DNS-01 wildcard
# issuance of *.storage.pod.haus). Built inline rather than pulling a
# third-party prebuilt image — config-as-code, same inline-build
# pattern as plex/backup init images.
FROM caddy:2-builder AS builder
RUN xcaddy build --with github.com/caddy-dns/cloudflare

FROM caddy:2
COPY --from=builder /usr/bin/caddy /usr/bin/caddy

# Content-hash build arg from the podhaus mechanism (see AGENTS.md
# "Content-hash change detection"). Declared purely for cache busting:
# setting it as an ENV from the ARG means a different value produces
# a different layer hash, so any change to a tracked file in this
# stack's build context invalidates everything from this layer down.
# The value is never read by the running container.
ARG STACK_CONTENT_HASH=unset
ENV STACK_CONTENT_HASH=${STACK_CONTENT_HASH}
