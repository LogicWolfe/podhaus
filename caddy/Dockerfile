# Caddy + the caddy-dns/cloudflare module (needed for DNS-01 wildcard
# issuance of *.storage.pod.haus). Built inline rather than pulling a
# third-party prebuilt image — config-as-code, same inline-build
# pattern as plex/backup init images.
FROM caddy:2-builder AS builder
RUN xcaddy build --with github.com/caddy-dns/cloudflare

FROM caddy:2
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
