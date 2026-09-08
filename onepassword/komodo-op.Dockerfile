# Upstream ghcr.io/0dragosh/komodo-op publishes a multi-arch manifest,
# but its Dockerfile hardcodes --platform=linux/amd64 and GOARCH=amd64 —
# so the "arm64" tag is a mislabelled amd64 image that crashes with
# "exec format error" on real aarch64 hosts. This file builds a native
# arm64 image from upstream source, wrapped in the same alpine base.
#
# Upstream is pinned to a commit and carries komodo-op.patch on top:
# one ListVariables read per pass and writes only for values that
# differ, instead of a read plus an unconditional write per secret.
# Every Komodo API call is authenticated with a bcrypt check, so the
# unpatched ~370 calls per pass cost Core a full CPU core for half of
# every minute. The patch also drops per-secret logging so a pass that
# changed nothing logs at DEBUG only. Regenerate the patch against the
# pinned commit when bumping it.
#
# Built automatically by Komodo on first deploy (and on every redeploy)
# via compose's `build:` directive in onepassword/compose.yaml + the
# stack.toml's `run_build = true`. No manual `docker build` step needed.

FROM golang:1.25-alpine AS builder
RUN apk add --no-cache git
WORKDIR /src
ARG KOMODO_OP_COMMIT=532e23c4103a1372f08d8eba4129b12c75ea2e63
RUN git init -q . \
    && git remote add origin https://github.com/0dragosh/komodo-op.git \
    && git fetch -q --depth 1 origin "${KOMODO_OP_COMMIT}" \
    && git checkout -q FETCH_HEAD
COPY komodo-op.patch /tmp/komodo-op.patch
RUN git apply --check /tmp/komodo-op.patch && git apply /tmp/komodo-op.patch
RUN CGO_ENABLED=0 GOOS=linux GOARCH=arm64 \
    go build -ldflags "-s -w -X main.Version=local-arm64" \
    -o /komodo-op ./cmd/komodo-op

FROM alpine:latest
RUN addgroup -g 1001 -S appgroup && adduser -u 1001 -S appuser -G appgroup
COPY --from=builder /komodo-op /app/komodo-op
RUN chmod +x /app/komodo-op && chown appuser:appgroup /app/komodo-op

# Content-hash build arg from the podhaus mechanism (see AGENTS.md
# "Content-hash change detection"). Declared purely for cache busting.
ARG STACK_CONTENT_HASH=unset
ENV STACK_CONTENT_HASH=${STACK_CONTENT_HASH}

USER appuser
ENTRYPOINT ["/app/komodo-op", "-daemon"]
