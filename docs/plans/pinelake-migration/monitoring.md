# Monitoring — Gatus probes + heartbeats for pinelake

Pinelake services need health checks the same way bilby's services do.
Gatus already runs on bilby; extending it to cover pinelake is config-
only — no new stack on pinelake.

Depends on: [Cloudflare tunnel + Terraform](cloudflare-tunnel.md)
(Access policy chain for service-token bypass).

## Probe shapes

Three classes match the existing pattern in `gatus/conf/config.yaml`:

1. **HTTP probe** — Gatus on bilby curls a hostname expecting a
   specific response. Used for the public endpoints behind Cloudflare
   Access; the service token in 1Password gets sent as a header to
   bypass the Access challenge.
2. **Push heartbeat** — a process on pinelake POSTs to a Gatus push
   endpoint after some scheduled work succeeds. Used for backup
   plans (one per Backrest plan).
3. **Komodo API checks:** Gatus asks Core for Pinelake's Periphery state.
   The existing unresolved-critical-alert query separately catches deploy,
   build, procedure, and stack-state failures.

## Probes to add

### HTTP (Cloudflare-fronted public endpoints)

These need a service-token bypass in each Pinelake Access application and
the matching client credentials injected into Gatus. Without both pieces,
Gatus gets a login redirect rather than a real backend signal.

The Homelab service-token resource already exists in `terraform/access.tf`,
but its client credentials are not currently exposed to Komodo. Add a
Terraform-managed 1Password login item using the resource's `client_id` and
`client_secret`, following the Forgejo OIDC pattern in
`terraform/pocket_id.tf`. Then wire the resulting variables through
`gatus/stack.toml` and `gatus/compose.yaml` as
`CF_ACCESS_HOMELAB_CLIENT_ID` and `CF_ACCESS_HOMELAB_CLIENT_SECRET`.
Link the existing Homelab bypass policy to the three Pinelake applications;
do not broaden Nathan's interactive allow policy.

```yaml
# in gatus/conf/config.yaml
endpoints:
  - name: pinelake-flood
    group: pinelake
    url: "https://torrent.pinelake.haus/"
    conditions:
      - "[STATUS] == 200"
      - "[RESPONSE_TIME] < 3000"
      - "[BODY].length() > 100"   # Flood UI HTML
    headers:
      CF-Access-Client-Id: "${CF_ACCESS_HOMELAB_CLIENT_ID}"
      CF-Access-Client-Secret: "${CF_ACCESS_HOMELAB_CLIENT_SECRET}"

  - name: pinelake-syncthing
    group: pinelake
    url: "https://sync.pinelake.haus/"
    conditions:
      - "[STATUS] == 200"
      - "[BODY].length() > 100"
    headers:
      CF-Access-Client-Id: "${CF_ACCESS_HOMELAB_CLIENT_ID}"
      CF-Access-Client-Secret: "${CF_ACCESS_HOMELAB_CLIENT_SECRET}"
```

Do not probe the SSH hostname with an ordinary HTTP GET. An Access-protected
SSH route is exercised by the `cloudflared access ssh` client flow, so a 200
HTTP assertion is not a reliable SSH health signal. The Pinelake Periphery
check proves the host's tailnet management path; test SSH separately in the
host runbook if it needs an end-to-end monitor.

### Tailnet probes (parallel path)

Bilby's Docker daemon already forwards unknown names to MagicDNS while
preserving embedded Docker DNS. First prove a dockernet probe can resolve
Pinelake and reach an intentionally exposed test listener or `tailscale serve`
endpoint. Native services bound only to Mac loopback are not directly
reachable over the tailnet. Add no host networking or sidecar unless testing
demonstrates a real routing gap.

Only then add a second probe per service through that intentional tailnet
listener. When the Cloudflare probe fails but the tailnet probe is green,
that separates a Cloudflare or connector fault from a backend fault. Do not
write a probe against `pinelake:8384` while native Syncthing remains bound to
Mac loopback. Network-resiliency detail is in
[Network resiliency](network-resiliency.md).

### Push heartbeat (Backrest pipeline)

Use one nightly pipeline endpoint matching the current Kangaroo pattern. The
state plan reports success only after its OneDrive mirror hook completes; the
repository-level failure hook reports failures from any plan. Add more
endpoints only if a Pinelake plan later gets an independent schedule.
The Gatus push pattern is documented in `gatus/conf/config.yaml`:

```yaml
external-endpoints:
  - name: Backrest Pinelake Nightly
    group: Backup
    token: ${GATUS_HEARTBEAT_PUSH_TOKEN}
    heartbeat:
      interval: 25h
    alerts:
      - type: custom
        description: "Pinelake Flood backup did not check in."
        failure-threshold: 1
        success-threshold: 1
        send-on-resolved: true
```

Pinelake's stack maps its shared `GATUS_BACKREST_PUSH_TOKEN` variable to the
existing general-purpose `GATUS_HEARTBEAT_PUSH_TOKEN` item. The state plan's
`CONDITION_SNAPSHOT_SUCCESS` hook and repository-level `CONDITION_ANY_ERROR`
hook POST to
`https://gatus.pod.haus/api/v1/endpoints/<name>/external?token=…&success=…`.

### Komodo state and deploy alerts

Add a `GetServerState` endpoint matching the existing Kangaroo and Kookaburra
checks, with `server = "pinelake"`. The existing `Komodo Alerts` endpoint
already polls unresolved critical alerts and therefore covers deploy, build,
procedure, server, and unexpected stack-state failures without a new webhook.

### Tailscale health (optional)

The Pinelake Periphery state check already proves the management path end to
end. If a separate device-presence check is still useful after migration,
extend the existing Tailscale OAuth client's scopes and query the devices API.
Do not introduce a legacy API key just for this check.

## Dashboard

Gatus renders endpoints by group on its own status page. HyperDX at
`watch.pod.haus` is the observability UI for ClickStack logs, metrics,
and traces; it doesn't replace the Gatus status page. Adding a
`pinelake` group surfaces the new checks in Gatus without a dashboard
configuration change.

If desired, add a "pinelake-only" dashboard variant filtering on
`group=~"pinelake|backup-pinelake"`.

## Alert routing

Use the existing alert contract. Service checks inherit the default
custom alerter and reach Fenwick as `service_alert` events. Fenwick
decides how to notify over Signal. Only the checks that watch Fenwick
itself use the independent Postmark email backstop.

No group-specific routing is needed. Reuse the `*defaults` anchor for
ordinary checks and the existing push-endpoint authentication pattern
for Backrest heartbeats.

## Cross-references

- [Stack conventions — autoheal + Gatus](/stack-conventions.html)
- [Monitoring](/monitoring.html) — steady-state docs
- [Platform stacks](platform-stacks.md) — Backrest pinelake plans

## Acceptance criteria

- 2 HTTP probes on `pinelake` group, both green from bilby Gatus
- The Pinelake nightly pipeline heartbeat is green after its first complete
  snapshot and OneDrive mirror
- A forced service failure reaches Fenwick and produces the expected Signal
  notification; Fenwick's own checks retain the independent Postmark backstop
- Pinelake Periphery state is green in Gatus; a forced critical Komodo alert
  makes the existing `Komodo Alerts` check fail

## Open items deferred

- Tailnet parallel probes (depends on bilby Gatus reaching tailnet)
- Tailscale device-presence probe
- Whether to alert on "Cloudflare path down but tailnet up" vs just
  "service down" — useful but adds Gatus complexity
