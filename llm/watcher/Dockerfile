FROM python:3-slim

ARG STACK_CONTENT_HASH=unset
ENV STACK_CONTENT_HASH=${STACK_CONTENT_HASH}
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Standard library only. nvidia-smi comes from the NVIDIA container runtime,
# which puts it in the container when the service is given the GPU.
COPY *.py ./watcher/

CMD ["python", "-m", "watcher"]
