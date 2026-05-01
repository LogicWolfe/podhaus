# Disposable image for one-shot RAR backlog cleanup.
# Build: docker build -t rar-cleanup:local /home/nathan/repos/podhaus/rar-cleanup-scripts
# Delete when cleanup is done: docker rmi rar-cleanup:local
FROM debian:trixie-slim

# unrar is in non-free; enable it for this layer only.
RUN set -eux; \
    echo "deb http://deb.debian.org/debian trixie non-free" > /etc/apt/sources.list.d/non-free.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        coreutils \
        findutils \
        python3 \
        sqlite3 \
        unrar; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /state
