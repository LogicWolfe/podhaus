# nathanbaxter-deploy builder image — node:lts + git + mcli, ready to
# clone, build, and mirror. STACK_CONTENT_HASH busts the build cache
# whenever the build script or this Dockerfile changes (see the
# content-hash mechanism in AGENTS.md).

ARG STACK_CONTENT_HASH=unset
FROM quay.io/minio/mc:latest AS mc

FROM node:lts
ARG STACK_CONTENT_HASH
ENV STACK_CONTENT_HASH=${STACK_CONTENT_HASH}

RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates git curl openssh-client && \
    rm -rf /var/lib/apt/lists/*

COPY --from=mc /usr/bin/mc /usr/local/bin/mcli

COPY build.sh /usr/local/bin/build.sh
RUN chmod +x /usr/local/bin/build.sh

CMD ["/usr/local/bin/build.sh"]
