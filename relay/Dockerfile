# rathole has no published arm64 image (bilby is M1) and building from
# source via `cargo install` is slow/fragile in the rootless builder.
# Instead pull the official static release binary for the build host's
# arch. The same image runs clients on arm64 origins and the server on
# Numbat. run_build = true in each stack.toml builds it per host.
FROM debian:stable-slim
ARG STACK_CONTENT_HASH=unset
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl unzip gettext-base \
 && rm -rf /var/lib/apt/lists/* \
 && test -n "$STACK_CONTENT_HASH" \
 && arch="$(uname -m)" \
 && case "$arch" in \
      aarch64) asset="rathole-aarch64-unknown-linux-musl.zip" ;; \
      x86_64)  asset="rathole-x86_64-unknown-linux-gnu.zip" ;; \
      *) echo "unsupported arch: $arch" >&2; exit 1 ;; \
    esac \
 && curl -fsSL -o /tmp/r.zip \
      "https://github.com/rathole-org/rathole/releases/latest/download/${asset}" \
 && unzip -o /tmp/r.zip -d /usr/local/bin rathole \
 && chmod +x /usr/local/bin/rathole \
 && rm /tmp/r.zip
# gettext-base => envsubst: the entrypoint renders token/noise keys from
# env (komodo-op) into the runtime config; nothing secret is committed.
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# The content hash is consumed before the download so every requested
# rebuild checks the current upstream release instead of reusing an old
# dependency layer.
ENV STACK_CONTENT_HASH=${STACK_CONTENT_HASH}

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
