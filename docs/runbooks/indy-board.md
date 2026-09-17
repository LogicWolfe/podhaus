# Indy Board

The service behind Indigo's room controller (an ESP32-C6 with a Nuimo dial)
and display panel (an Inkplate 10). It renders the pages, drives Home
Assistant and Music Assistant, and keeps both boards' firmware current over
their WiFi links. The code, its stack files and its own docs live in the
[indy-board repo](https://git.pod.haus/LogicWolfe/indy-board)
(`docs/architecture.md`, `docs/maintenance.md`).

## Topology

- **Stack** `indy-board` on bilby, container `indy-service`, on `dockernet`.
  Defined by `stack.toml`, `compose.yaml` and `Dockerfile` at the indy-board
  repo root; podhaus holds only the Komodo repo, sync and procedure, the
  Forgejo webhook, the Alloy drop module and the Gatus check.
- **Boards dial in** to bilby's LAN address: the panel on `:5099`, the
  controller on `:5100`, both published by the container. Each board's
  address and port are in its own flash config partition, written by cable.
- **Home Assistant and Music Assistant** use host networking, so the
  service reaches them through the dockernet gateway, `172.18.0.1:8123` and
  `:8095`.
- **No state.** The image carries the service and both boards' firmware;
  nothing is bind-mounted and nothing needs backing up.

## Deploys

A merge to indy-board's `main` whose CI passes advances `deploy`; the
webhook fires `indy-board-push-deploy`, which pulls, syncs, builds and
recreates the container (`--force-recreate`, so every deploy is a fresh
container). Each board is offered its image from the new container when it
next connects, which is within seconds of the restart. A board runs a new
image on trial and falls back to its previous image by itself if the new one
does not hold a session with the service.

The first cold build is long: it installs both firmware toolchains, ESP-IDF
included. Its caches (Docker cache mounts `indy-*`) make later builds
incremental. The compile steps share one locked cache so they run one at a
time, which keeps the build within bilby's memory.

On a Komodo that has never deployed the stack, run `CloneRepo indy-board`
once first: the procedure's pull stage fails on a clone that does not exist.

`tools/ship.sh service|controller|panel`, run from any indy-board checkout,
builds that target on bilby and copies it into the running container. The
next deploy replaces it.

## Secrets and settings

- `Home Assistant` (Homelab) → `INDY_HA_TOKEN`, a long-lived Home Assistant
  token.
- `indy-board-music-assistant` (Homelab) → `INDY_MA_TOKEN`.
- `clickstack-ingestion-key` (Homelab) → `INDY_OTLP_AUTHORIZATION`.
- Entity, provider and player IDs and the URLs are `[[variable]]` blocks in
  the repo's `stack.toml`.

## Logs and alerts

The service exports its own logs and spans to ClickStack
(`ServiceName = 'indy-service'`), including the boards' log lines, boot
reports and status records, each with a `device` attribute of `controller`
or `panel`. Alloy drops the container's stdout
(`logging/alloy-modules/indy-service.alloy`); `docker logs indy-service`
shows the same records.

Gatus **Indy Board devices reporting** alerts when either board's
`device alive` records stop for 15 minutes. The service itself logs an error
record for a board that keeps failing its boots or stays away, with the
evidence and the manual recovery step.

## Recovery

- **A board stays away.** Check its power and the WiFi. Neither board can be
  power-cycled remotely, and the panel has a battery. A board that can't
  reach the service at all needs a cable flash from a checkout on bilby:
  `tools/flash.sh controller|panel CONFIG_IMAGE` (the Inkplate on
  `/dev/ttyUSB0`, the C6 on `/dev/ttyACM0`).
- **A bad firmware image.** The board rolls back on its own. To stop the
  image being offered again, revert it on `main`, or ship a working build.
- **The container won't start.** `docker logs indy-service` names the
  missing or invalid setting.
