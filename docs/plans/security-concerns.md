# Security concerns

Open findings, most from the post-migration review of the Numbat edge. Each
item is a real defect with a scoped remediation, not a design preference.

Two areas are deliberately **out of scope here** because they are being
reworked separately: anything in the host bootstrap / rebuild path, and
Voltaire's Cloudflare tunnel and DNS entanglement.

Pre-existing debt not introduced by the migration — the flat `dockernet`
trust domain, the Terraform-only 1Password items — lives in
[tech debt](tech-debt.md) and is not repeated here.

## UniFi controller is directly internet-exposed

- [ ] Move `unifi.pod.haus` behind Pomerium.

`terraform/services_pod_haus.tf` maps `unifi` to `local.numbat_relay_ipv4`
as a DNS-only A record, so there is no Cloudflare proxy in the path.
`caddy/Caddyfile` then proxies it straight to the LAN gateway:

```
unifi.pod.haus, unifi.pod.haus:4444 {
	tls { dns cloudflare {env.CLOUDFLARE_API_TOKEN} }
	reverse_proxy https://10.0.0.1 {
		transport http { tls_insecure_skip_verify }
	}
}
```

No `client_auth`, no gateway-token matcher, no Pomerium route. Every other
`:4444` site enforces Cloudflare Authenticated Origin Pulls; this one cannot,
because it is not proxied.

The "UniFi has its own login" decision is older than this migration — the
pre-migration hostname carried an Access application whose only policy was
`unifi_bypass`. What changed is that the Cloudflare proxy in front of it is
gone: no WAF, no bot management, no rate limiting, no origin-IP concealment.
The remaining boundary is a session login form on `10.0.0.1`, the LAN
gateway itself. That is not the same class of boundary as RustFS's
per-request SigV4, which is the justification `AGENTS.md` uses for keeping a
raw endpoint on the relay address.

`id.pod.haus` is the other raw name on the relay IP and is genuinely forced:
a Pomerium-gated identity provider deadlocks its own login. UniFi has no
equivalent constraint.

**Fix**

1. Move `unifi` from `numbat_relay_ipv4` to `numbat_application_ipv4` in
   `terraform/services_pod_haus.tf`.
2. Add a `*nathan_route` entry for `https://unifi.pod.haus` in
   `pomerium/config.yaml`.
3. Move the Caddy block out of `:4444` and into the `:4443` protected
   section alongside the other host matchers.

If something non-browser needs the controller API, the
`paperless-api.pod.haus:4444` gateway-token pattern already in the Caddyfile
is the in-repo precedent — do not reopen the unauthenticated path for it.

**Verify:** `dig +short unifi.pod.haus` returns the application address;
`curl -sI https://unifi.pod.haus/` returns Pomerium's 302 to `id.pod.haus`
rather than the UniFi UI.

## One shared build context couples all four relay stacks

- [ ] Narrow each relay stack's build context.
- [ ] Document that a `numbat-relay` redeploy severs Numbat's control path.

`relay/{bilby,fractal,kangaroo,numbat}/compose.yaml` all declare
`context: ..`, so every context resolves to the whole `relay/` tree.
`hashDir` in `komodo/sync/actions.toml` recurses that tree excluding only
files named `.env` — **it does not read `.dockerignore`**. So an edit to
`relay/bilby/numbat-client.toml.tmpl` changes `BUILD_HASH_RATHOLE_SERVER`,
Stage 1 sees the running container's label is stale, and it force-deploys
`numbat-relay`.

That is load-bearing because `numbat-relay` carries Numbat's own control
path. Periphery dials `wss://core-connect.pod.haus/ws/periphery`;
`core-connect.pod.haus` is an A record to the relay address, which the local
rathole `public_tls` service carries to `caddy:4444` on bilby. A Komodo
deploy of `numbat-relay` tears down the transport that deploy arrived on.

The repo already applies the opposite rule one layer up — Periphery is
deliberately kept out of Komodo's hands on every outbound host precisely
because "a Komodo-driven redeploy of it would sever the path it runs on"
([hosts](../hosts.html#numbat),
[host provisioning](../host-provisioning.md)). The relay one layer *below*
Periphery is Komodo-managed and this property is recorded nowhere.

Failure shape: an unrelated edit under `relay/kangaroo/` drops public TLS,
protected HTTP, all four host-SSH services, Periphery, and log shipping for
the restart window, and the deploy call itself reports failure because its
own transport vanished. If the edit is also bad, the relay does not come
back, Komodo has no path to Numbat at all, and recovery needs the Tailscale
plane.

**Fix**

1. Move the shared build inputs to `relay/image/{Dockerfile,entrypoint.sh}`
   and point all four `context:` at `../image`. A `.dockerignore` will not
   work — `hashDir` does not read one.
2. Add a sentence to [hosts → Numbat](../hosts.html#numbat) recording that
   redeploying `numbat-relay` cuts Numbat's own control path, and that the
   recovery plane is the fallback.

**Verify:** edit a comment in `relay/bilby/numbat-client.toml.tmpl` and push
it to `main` — Stage 1 should list `bilby-relay` and not `numbat-relay`.

## Fractal gets no telemetry heartbeat, by decision

Decided: fractal gets no telemetry heartbeat and no further alert. It is down
intermittently by design (a Windows desktop running Fedora under WSL), and the
*Docs (fractal, via Komodo)* check is the one fractal alert wanted. Gatus
carries five telemetry heartbeats, for kangaroo, Numbat, Pinelake, bandicoot
and voltaire, and Periphery checks for bilby, kangaroo, Numbat, fractal,
voltaire and Pinelake.

- [ ] Decide whether *Fractal Periphery (via Komodo)* keeps its alerts. It
  alerts through the shared Gatus alert list today, a second fractal alert
  beside the docs check, against the decision above. Trade-off: it reports a
  dead fractal Periphery (deploys to fractal failing quietly) sooner, at the
  cost of an alert every time the desktop is off.

## HyperDX MCP credentials sit in the log store

- [ ] Decide whether to rotate the HyperDX MCP client's two credentials.
- [ ] Decide whether to delete the 60 rows that hold them.

For six minutes on 2026-08-08, 13:14:10 to 13:20:12 UTC, Pomerium's Envoy
proxy logged whole request headers (`proxy_log_level: debug` at the time;
`pomerium/config.yaml` now sets `info`). Sixty `pomerium` rows from that
window in ClickStack's `otel_logs` table carry credentials:

- 10 rows from requests to `watch.pod.haus/api/mcp` carry both of the HyperDX
  MCP client's credentials: the `Authorization: Bearer` header, which is
  Nathan's HyperDX Personal API Access Key (the `credential` field of the
  Dev-vault `Podhaus HyperDX` item), and the `X-Podhaus-Gateway-Token` header,
  which is the `hyperdx_mcp` field of the Homelab `Pomerium Gateway Tokens`
  item. Neither expires.
- 50 rows carry a Pomerium session cookie. `cookie_expire` is 720 h, so these
  sessions expired by 2026-09-07 and need no action.

No other day in the 180-day log retention holds these headers (counted on
2026-10-04 by matching header names in the body; values were not read).
`otel_logs` keeps rows for 180 days, so they stay readable to every HyperDX
user, and to anything holding the MCP key, until about 2027-02-04.

**Recommendation:** rotate both credentials and delete the rows. Rotation is
what closes the exposure; deleting alone cannot undo a read that already
happened, and the rows would keep turning up as live-looking secrets in any
later audit. Rotation costs a client re-registration: a new key in HyperDX
Team Settings, the new values in the Homelab `Pomerium Gateway Tokens` item and
the Dev-vault `Podhaus HyperDX` item, a manual Caddy redeploy for the gateway
check (a secret change does not redeploy on its own), and an updated MCP client
on each development machine. Deleting is a ClickHouse mutation on
one day's data:

```
ALTER TABLE otel_logs DELETE
WHERE ServiceName = 'pomerium'
  AND TimestampTime BETWEEN toDateTime('2026-08-08 13:14:00', 'UTC')
                        AND toDateTime('2026-08-08 13:21:00', 'UTC')
  AND (positionCaseInsensitive(Body, '_pomerium') > 0
       OR positionCaseInsensitive(Body, 'x-podhaus-gateway-token') > 0
       OR (positionCaseInsensitive(Body, 'authorization') > 0
           AND positionCaseInsensitive(Body, 'bearer') > 0))
```

**Verify:** requests to `https://watch.pod.haus/api/mcp` with the old key or
the old gateway token are refused; a count over the same filter returns 0.

## Alloy's API shows the ingestion key to its dockernet neighbours

- [ ] Decide whether Alloy's HTTP API stays reachable from `dockernet`.

Every host's Alloy listens on `0.0.0.0:12345` (`--server.http.listen-addr` in
`logging/compose.shared.yaml`) and joins that host's `dockernet`. Its API needs
no credentials, and `/api/v0/web/components/<component>` returns a
component's arguments as evaluated. For the shipping exporter,
`podhaus.ship.run/otelcol.exporter.otlphttp.clickstack`, those include the
`authorization` header: the ClickStack ingestion key, in plain text. A local
probe of all seven host configs with stand-in keys (2026-10-05) read each key
back this way. Every host uses the same key, the Homelab item behind the
Komodo variable `OP__KOMODO__CLICKSTACK_INGESTION_KEY__CREDENTIAL`. Port 12345
is published nowhere and no Caddy or Pomerium route reaches it, so the
exposure is to containers on the same host's `dockernet`.

This predates the shipping module: the key sat in each host config's exporter
before. The key grants ingestion only. Whoever holds it can write rows into
ClickStack under any host and service name, including rows that would keep a
dead host's telemetry heartbeat green, but cannot read anything. On the home
LAN the key alone is enough, because bilby and kangaroo ship to bandicoot's
port 4318 over plain HTTP; through `logs-ingest.pod.haus` a host's client
certificate is needed as well.

**Option:** listen on `127.0.0.1:12345` instead. The healthcheck connects from
inside the container to `127.0.0.1`, and nothing else reads port 12345 today.
Trade-off: Alloy's UI and API are then reachable only from inside its own
container (`docker exec`), never from a neighbouring debugging container.

## Configuration that describes a system that no longer exists

Not exploitable, but every item below will mislead the next reader about
where a boundary is.

- [ ] Delete the dead `http://` site blocks in `caddy/Caddyfile` for
      `nathanbaxter.com`, `www.nathanbaxter.com`, `skycroeser.net`, and
      `www.skycroeser.net`. `caddy/compose.yaml` publishes only `443:443`,
      so port 80 is unreachable and these are unreachable config. The
      `:4444` AOP blocks are the live ones.
- [ ] Fix the header comment in `terraform/dns_pod_haus.tf`, which still
      describes `services_pod_haus.tf` as holding `module.<name>` calls that
      own "the CNAME alongside its Access app and tunnel ingress rule".
      It is now a plain DNS map.
- [ ] Fix the cloudflare provider comment in `terraform/backend.tf`, which
      still credits it with "Access apps + policies, Tunnel config, GitHub
      webhook bypass, the whole pod.haus wildcard". The wildcard and the
      webhook bypass are gone.
- [ ] Remove the three "Kookaburra rollback" / "Cloudflare Tunnel paths
      remain configured separately for rollback" notes in `caddy/Caddyfile`.
- [ ] Remove `gatus/config.yaml` — it is an empty **directory**, a
      Docker-created stub from a bind whose source did not exist. This is
      the exact failure `AGENTS.md` warns about. The live config is
      `gatus/conf/config.yaml`.
- [ ] Remove the leftover empty directories: `relay/kookaburra/`,
      `kookaburra/*`, `logging/kookaburra/alloy-conf/`,
      `terraform/modules/pod_haus_service/`, and `docs/plans/pomerium-edge/`.
      The last one reads as an in-flight workstream.
- [x] Fix the stale doc path in `ansible/inventory/hosts.yml`. Resolved
      by the plan's retirement: the inventory now points at
      `docs/host-provisioning.md`, which is durable.

The kookaburra references in `komodo/sync/procedures.toml` and
`tools/lint-stack-toml.py` are legitimate rationale for a live rule. Leave
those.
