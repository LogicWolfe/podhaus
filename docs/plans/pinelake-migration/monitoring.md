# Monitoring — Gatus probes + heartbeats for pinelake

Pinelake services need health checks the same way bilby's services do.
Gatus already runs on bilby; extending it to cover pinelake is config-
only — no new stack on pinelake.

Depends on: [Cloudflare tunnel + Terraform](cloudflare-tunnel.md)
(Access policy chain for service-token bypass).

## Probe shapes

Three classes match the existing pattern in `gatus/config.yaml`:

1. **HTTP probe** — Gatus on bilby curls a hostname expecting a
   specific response. Used for the public endpoints behind Cloudflare
   Access; the service token in 1Password gets sent as a header to
   bypass the Access challenge.
2. **Push heartbeat** — a process on pinelake POSTs to a Gatus push
   endpoint after some scheduled work succeeds. Used for backup
   plans (one per Backrest plan).
3. **Komodo deployment check** — Komodo Core (on bilby) reports
   stack deployment success/failure for pinelake stacks via the
   existing webhook + Gatus integration. Already covered by the
   existing config; just needs pinelake to be a registered Komodo
   server.

## Probes to add

### HTTP (Cloudflare-fronted public endpoints)

These need the **Homelab service-token bypass** in the
`*.pinelake.haus` Access policy chain (open question #5 in the
[index](index.md) — recommendation: add it). Without bypass, Gatus
gets a 302 to the Access login page, not a real probe of the backend.

```yaml
# in gatus/config.yaml
endpoints:
  - name: pinelake-home-ssh
    group: pinelake
    url: "https://home.pinelake.haus"
    method: GET
    conditions:
      - "[STATUS] == 200"   # cloudflared ssh app returns 200 on root probe
                            # unauthenticated when service token sends correct header
      - "[RESPONSE_TIME] < 2000"
    headers:
      CF-Access-Client-Id: "[[OP__KOMODO__CF_ACCESS_HOMELAB_TOKEN__CLIENT_ID]]"
      CF-Access-Client-Secret: "[[OP__KOMODO__CF_ACCESS_HOMELAB_TOKEN__CLIENT_SECRET]]"

  - name: pinelake-flood
    group: pinelake
    url: "https://torrent.pinelake.haus/"
    conditions:
      - "[STATUS] == 200"
      - "[RESPONSE_TIME] < 3000"
      - "[BODY].length() > 100"   # Flood UI HTML
    headers:
      CF-Access-Client-Id: "[[OP__KOMODO__CF_ACCESS_HOMELAB_TOKEN__CLIENT_ID]]"
      CF-Access-Client-Secret: "[[OP__KOMODO__CF_ACCESS_HOMELAB_TOKEN__CLIENT_SECRET]]"

  - name: pinelake-syncthing
    group: pinelake
    url: "https://sync.pinelake.haus/rest/system/status"
    conditions:
      - "[STATUS] == 200"
      - "[BODY].myID != null"
    headers:
      CF-Access-Client-Id: "[[OP__KOMODO__CF_ACCESS_HOMELAB_TOKEN__CLIENT_ID]]"
      CF-Access-Client-Secret: "[[OP__KOMODO__CF_ACCESS_HOMELAB_TOKEN__CLIENT_SECRET]]"
```

Note: the Syncthing REST API requires an API key for most endpoints.
`/rest/system/status` is unauthenticated by default; if it isn't,
fall back to `GET /` which returns the GUI HTML.

### Tailnet probes (parallel path)

Add a second probe per service via the tailnet name, so Gatus
distinguishes Cloudflare-path failures from backend failures:

```yaml
  - name: pinelake-syncthing-tailnet
    group: pinelake-tailnet
    url: "http://pinelake:8384/rest/system/status"   # tailscale MagicDNS
    conditions:
      - "[STATUS] == 200"
```

(No Access headers — direct via tailnet.) When the Cloudflare probe
fails but the tailnet probe is green, that's a CF/cloudflared issue
not a service issue. Network-resiliency detail in
[Network resiliency](network-resiliency.md).

For this to work, bilby's Gatus container needs to be on the tailnet.
Currently bilby itself is on the tailnet; the Gatus container would
need either `network_mode: host` (would conflict with existing setup)
or a sidecar. Defer this — it's a nice-to-have on top of the
Cloudflare-path probes. Implement once both paths are stable.

### Push heartbeats (Backrest plans)

Five push endpoints, one per Backrest plan on pinelake. The Gatus
push pattern is documented under `gatus/config.yaml`:

```yaml
  - name: backrest-pinelake-flood
    group: backup-pinelake
    url: ""        # push
    conditions:
      - "[BODY].success == true"
    alerts:
      - type: email
        conditions: ["[BODY].success == false"]
        send-on-resolved: true
    client:
      ignore-redirect: true
    token: "[[OP__KOMODO__GATUS_BACKREST_PINELAKE_PUSH_TOKEN__CREDENTIAL]]"
```

Repeat for `backrest-pinelake-syncthing`, `backrest-pinelake-plex`,
`backrest-pinelake-cloudflared`, `backrest-pinelake-state`.

The push token is shared across all five (one 1Password item,
`Gatus Backrest pinelake push token`). Backrest's
`CONDITION_SNAPSHOT_SUCCESS` / `_FAILURE` hooks POST to
`https://gatus.pod.haus/api/v1/endpoints/<name>/external?token=…&success=…`.

### Komodo deploy alerts

Komodo Core's existing webhook fires into Gatus on stack deploy
success/failure. Once pinelake is a registered server in
`komodo/sync/servers.toml`, this is automatic — no Gatus config
change needed beyond optionally adding a group filter for `pinelake`
deploys in the uptime dashboard.

### Tailscale health (optional)

If `tailscaled` LaunchDaemon is in place (see
[Host bootstrap](host-bootstrap.md)), add a probe checking that the
node is up:

```yaml
  - name: pinelake-tailscale-presence
    group: network
    url: "https://api.tailscale.com/api/v2/tailnet/<tailnet>/devices"
    method: GET
    headers:
      Authorization: "Bearer [[OP__KOMODO__TAILSCALE_API_KEY__CREDENTIAL]]"
    conditions:
      - "[STATUS] == 200"
      - "[BODY].devices[?(@.hostname == 'pinelake')].lastSeen >= now - 5m"
```

Requires a Tailscale API key in 1Password. Defer until tailscaled
daemon migration completes.

## Dashboard

The uptime dashboard (recreated in HyperDX at `watch.pod.haus` from
Gatus `/metrics`, or Gatus's own status page — VictoriaLogs + Grafana
were decommissioned with the ClickStack migration) renders Gatus
endpoints by group. Adding a `pinelake` group surfaces the new
probes automatically. No dashboard change needed.

If desired, add a "pinelake-only" dashboard variant filtering on
`group=~"pinelake|backup-pinelake"`.

## Alert routing

Same as today — Gatus alerts via Postmark to the user's email. Add
the `pinelake` and `backup-pinelake` groups to whatever alert routing
logic exists in the Gatus config.

## Cross-references

- [Stack conventions — autoheal + Gatus](/stack-conventions.html)
- [Monitoring](/monitoring.html) — steady-state docs
- [Platform stacks](platform-stacks.md) — Backrest pinelake plans

## Acceptance criteria

- 3 HTTP probes on `pinelake` group, all green from bilby Gatus
- 5 push heartbeats on `backup-pinelake` group, all green after first
  Backrest snapshot
- Email alert fires when a probe is forced to fail (test: stop a
  container, wait for retry threshold, confirm alert)
- Komodo deploy events for pinelake stacks visible in the uptime
  dashboard (HyperDX at `watch.pod.haus`)

## Open items deferred

- Tailnet parallel probes (depends on bilby Gatus reaching tailnet)
- Tailscale API key probe
- Whether to alert on "Cloudflare path down but tailnet up" vs just
  "service down" — useful but adds Gatus complexity
