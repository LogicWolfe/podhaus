# Pagefind search-index builder for the skycroeser-net bucket. Long-running
# container; ofelia execs scripts/index.sh on a schedule (see compose labels).
FROM node:20-alpine
ARG STACK_CONTENT_HASH=unset
ENV STACK_CONTENT_HASH=${STACK_CONTENT_HASH}
RUN apk add --no-cache bash curl ca-certificates \
 && curl -fsSL https://dl.min.io/client/mc/release/linux-arm64/mc -o /usr/local/bin/mc \
 && chmod +x /usr/local/bin/mc \
 && npm install -g pagefind \
 && pagefind --version
CMD ["sleep", "infinity"]
