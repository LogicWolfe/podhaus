# Pinelake monitoring

Depends on the [outbound gateway contract](index.md), not Cloudflare Access or
Tailscale.

## Required signals

- Komodo reports Pinelake Periphery connected through
  `core-connect.pod.haus`.
- Pinelake Alloy self-metrics arrive through `logs-ingest.pod.haus` at least
  once per minute. Add a Gatus ClickHouse freshness query keyed by
  `ResourceAttributes['host']='pinelake'`.
- Add direct Gatus checks for each local service and its storage sentinel. These
  prove the backend rather than accepting an authentication redirect.
- Add off-LAN checks only for public or machine endpoints where end-to-end edge
  coverage matters. Use the endpoint's scoped credential, never a broad bypass.
- Backrest keeps the existing per-plan heartbeat and repository freshness
  checks.

## Failure interpretation

A healthy local check plus failed public check points to the Pinelake rathole
client, Numbat, DNS, or Pomerium. A stale Alloy heartbeat with Periphery still
connected points to the logging path. Both connections failing usually means
Pinelake's internet path, Numbat, or host power.

## Acceptance

After a reboot with no user login, Periphery reconnects, an Alloy heartbeat
lands, local service checks pass, and each deliberately public route works from
off-LAN. Stopping one named rathole route alerts only that service.
