FROM python:3-slim

ARG STACK_CONTENT_HASH=unset
ENV STACK_CONTENT_HASH=${STACK_CONTENT_HASH}
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir grpcio grpcio-tools PyJWT requests docker

# Protos vendored from pomerium/pomerium v0.33.0 (pkg/grpc/{databroker,session});
# the databroker is Pomerium's internal contract, so refresh these when a
# Pomerium upgrade breaks the stream.
COPY databroker.proto session.proto ./
RUN python -m grpc_tools.protoc -I. \
    --python_out=. --grpc_python_out=. databroker.proto session.proto

COPY main.py ./

CMD ["python", "main.py"]
