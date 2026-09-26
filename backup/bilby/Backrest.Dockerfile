FROM garethgeorge/backrest:latest

RUN apk add --no-cache jq

ARG STACK_CONTENT_HASH=unset
ENV STACK_CONTENT_HASH=${STACK_CONTENT_HASH}
