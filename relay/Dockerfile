# rathole has no published arm64 image (bilby is M1) and building from
# source via `cargo install` is slow/fragile in the rootless builder.
# Instead pull the official static release binary for the build host's
# arch — arm64 (bilby client) or x86_64 (kookaburra server). Same
# "build locally because upstream's arch story is wrong" pattern as
# komodo-op. run_build = true in the stack.toml builds per host.
FROM debian:stable-slim
ARG RATHOLE_VERSION=v0.5.0
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl unzip gettext-base \
 && rm -rf /var/lib/apt/lists/* \
 && arch="$(uname -m)" \
 && case "$arch" in \
      aarch64) asset="rathole-aarch64-unknown-linux-musl.zip" ;; \
      x86_64)  asset="rathole-x86_64-unknown-linux-gnu.zip" ;; \
      *) echo "unsupported arch: $arch" >&2; exit 1 ;; \
    esac \
 && curl -fsSL -o /tmp/r.zip \
      "https://github.com/rapiz1/rathole/releases/download/${RATHOLE_VERSION}/${asset}" \
 && unzip -o /tmp/r.zip -d /usr/local/bin rathole \
 && chmod +x /usr/local/bin/rathole \
 && rm /tmp/r.zip
# gettext-base => envsubst: the entrypoint renders token/noise keys from
# env (komodo-op) into the runtime config; nothing secret is committed.
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
