# Upstream ghcr.io/0dragosh/komodo-op publishes a multi-arch manifest,
# but its Dockerfile hardcodes --platform=linux/amd64 and GOARCH=amd64 —
# so the "arm64" tag is a mislabelled amd64 image that crashes with
# "exec format error" on real aarch64 hosts. This file builds a native
# arm64 image from the same source, wrapped in the same alpine base.
#
# Built automatically by Komodo on first deploy (and on every redeploy)
# via compose's `build:` directive in onepassword/compose.yaml + the
# stack.toml's `run_build = true`. No manual `docker build` step needed.

FROM golang:1.25-alpine AS builder
RUN apk add --no-cache git
WORKDIR /src
RUN git clone --depth 1 https://github.com/0dragosh/komodo-op.git /src
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
