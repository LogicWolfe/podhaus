# Pagefind search-index builder. bilby is aarch64 Asahi (16k pages), and
# pagefind's only prebuilt aarch64-Linux binary is musl — which bundles
# jemalloc (gated #[cfg(target_env="musl")]) compiled for 4k pages and
# crashes here. So we build the binary ourselves, cleanly: `cargo install`
# on a GLIBC base, where jemalloc is never compiled in. The published crate
# bundles the prebuilt WASM/UI assets (include_dir, build=false), so this is
# a plain CLI compile — no wasm-pack/nightly/node. LTO off + capped jobs keep
# the build-time memory bounded (see docs).
FROM rust:bookworm AS build
ARG PAGEFIND_VERSION=1.5.2
ENV CARGO_BUILD_JOBS=2 \
    CARGO_PROFILE_RELEASE_LTO=false
RUN cargo install pagefind --version ${PAGEFIND_VERSION} --locked --root /opt/pf

FROM debian:bookworm-slim
ARG STACK_CONTENT_HASH=unset
ENV STACK_CONTENT_HASH=${STACK_CONTENT_HASH}
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl bash \
 && curl -fsSL https://dl.min.io/client/mc/release/linux-arm64/mc -o /usr/local/bin/mc \
 && chmod +x /usr/local/bin/mc \
 && rm -rf /var/lib/apt/lists/*
COPY --from=build /opt/pf/bin/pagefind /usr/local/bin/pagefind
# Executes the freshly-built binary on bilby (16k pages) — fails the build
# loudly if jemalloc ever sneaks back in.
RUN pagefind --version
CMD ["sleep", "infinity"]
