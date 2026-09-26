# syntax=docker/dockerfile:1
FROM rust:1.97.1-trixie AS builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ca-certificates curl git unzip pkg-config libssl-dev lld \
    protobuf-compiler flatbuffers-compiler && rm -rf /var/lib/apt/lists/*
WORKDIR /usr/src/rustfs
# The release image omits SFTP, which Blocs needs for publishing.
RUN git clone --depth 1 --branch 1.0.0 https://github.com/rustfs/rustfs.git . \
    && ./scripts/static.sh
ENV CARGO_BUILD_JOBS=2 CARGO_INCREMENTAL=0 CARGO_PROFILE_RELEASE_LTO=false \
    CARGO_PROFILE_RELEASE_DEBUG=false CARGO_PROFILE_RELEASE_STRIP=symbols \
    RUSTFS_BUILD_VERSION=1.0.0
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/usr/local/cargo/git \
    --mount=type=cache,target=/usr/src/rustfs/target \
    cargo run --locked --bin gproto && \
    cargo build --release --locked --bin rustfs --features sftp \
      --config 'profile.release.package.rustfs.codegen-units=16' && \
    install -m 0755 target/release/rustfs /usr/local/bin/rustfs

FROM ubuntu:26.04
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 10001 rustfs && useradd -u 10001 -g rustfs -M rustfs \
    && mkdir /data /logs && chown 10001:10001 /data /logs
COPY --from=builder /usr/local/bin/rustfs /usr/local/bin/rustfs
ARG STACK_CONTENT_HASH
ENV STACK_CONTENT_HASH=${STACK_CONTENT_HASH}
USER 10001:10001
ENTRYPOINT ["/usr/local/bin/rustfs"]
