# Security concerns

Open findings from the post-migration review of the Numbat edge. Each item
is a real defect with a scoped remediation, not a design preference.

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
gateway itself. That is not the same class of boundary as MinIO's
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

**Verify:** edit a comment in `relay/bilby/numbat-client.toml.tmpl` and run
`./komodo-sync` — Stage 1 should list `bilby-relay` and not `numbat-relay`.

## Fractal has no monitoring coverage

- [ ] Add a fractal Periphery check to Gatus.
- [ ] Add a fractal telemetry heartbeat to Gatus.

`gatus/conf/config.yaml` carries Periphery checks for bilby, kangaroo, and
numbat, plus telemetry heartbeats for kangaroo and numbat. Fractal has
neither, despite running four stacks and shipping cross-network Alloy the
same way kangaroo does — which is exactly the silent-wedge failure mode the
[2026-06-19 postmortem](../postmortems/2026-06-19-alloy-exporter-keepalive-wedge.md)
documents, and which only the staleness heartbeat caught.
[Monitoring](../monitoring.html) already asserts the fractal pipeline
exists, so the docs claim coverage the config does not provide.

**Fix:** copy the "Numbat Periphery (via Komodo)" endpoint with
`"server":"fractal"` in the body, and the "Numbat Telemetry Pipeline
(heartbeat)" endpoint with `ResourceAttributes['host']='fractal'`.

**Verify:** both endpoints appear green on `gatus.pod.haus` after deploy.

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
      remain configured separately for rollback" notes in `caddy/Caddyfile`,
      and the deleted-stack reference in `minio/stack.toml`.
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
