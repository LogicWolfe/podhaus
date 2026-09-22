FROM docker:cli AS docker
FROM python:3-slim
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=docker /usr/local/bin/docker /usr/local/bin/docker
COPY download.py /tmp/download.py
ARG STACK_CONTENT_HASH
ENV STACK_CONTENT_HASH=${STACK_CONTENT_HASH}
RUN python /tmp/download.py && rm /tmp/download.py
COPY gateway.py /opt/lumen/gateway.py
ENTRYPOINT ["python", "/opt/lumen/gateway.py"]
