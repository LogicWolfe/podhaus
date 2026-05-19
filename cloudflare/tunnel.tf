# pod.haus Cloudflare Tunnel configuration — single source of truth for
# every ingress rule cloudflared serves. Replaces the bind-mounted
# `cloudflare-tunnel/conf/config.yml` once `source = "cloudflare"` is
# active and the cloudflared compose stops passing `--config`.
#
# Reference docs:
#   - cloudflare_zero_trust_tunnel_cloudflared_config:
#     https://registry.terraform.io/providers/cloudflare/cloudflare/latest/docs/resources/zero_trust_tunnel_cloudflared_config
#
# Order matters: cloudflared evaluates rules top-to-bottom; first match
# wins. The last rule must be a catch-all (no hostname) returning 404.
# Module-managed services come first, legacy explicit entries after,
# then the catch-all. Hostnames are mutually exclusive so the relative
# order between matchable rules is cosmetic.

locals {
  # Every pod.haus service exposes its ingress rule via
  # module.<name>.ingress_rule. Adding a `module "<name>"` block in
  # services_pod_haus.tf grows this list automatically.
  pod_haus_module_ingress = [
    module.gatus.ingress_rule,
    module.bugsink.ingress_rule,
    module.backup.ingress_rule,
    module.fenwick.ingress_rule,
    module.kangaroo_backup.ingress_rule,
    module.kangaroo.ingress_rule,
    module.komodo.ingress_rule,
    module.torrents.ingress_rule,
    module.home_assistant.ingress_rule,
    module.plex.ingress_rule,
    module.watch.ingress_rule,
    module.docs.ingress_rule,
    module.minio.ingress_rule,
    module.syncthing.ingress_rule,
    module.paperless.ingress_rule,
    module.unifi.ingress_rule,
  ]
}

resource "cloudflare_zero_trust_tunnel_cloudflared_config" "pod_haus" {
  account_id = var.account_id
  tunnel_id  = local.tunnel_ids.pod_haus

  # `cloudflare` source moves authority from the bind-mounted YAML into
  # CF's API. cloudflared has to be launched without `--config` for
  # the change to actually flip; until then cloudflared keeps using
  # its local config and this resource is just CF-side metadata.
  source = "cloudflare"

  # The for-loops reshape each entry into a fresh object literal —
  # works around a provider type-inference quirk where module outputs
  # passed directly to ingress[] fail schema validation with
  # "config.ingress[0].service required."
  config = {
    ingress = concat(
      [for r in local.pod_haus_module_ingress : { hostname = r.hostname, service = r.service, path = r.path, origin_request = r.origin_request }],
      # nathanbaxter.com public Publii site → Caddy (NOT a pod.haus
      # module / NOT Access-gated; cloudflared serves any zone). Caddy
      # maps it to the nathanbaxter-com bucket. See
      # docs/plans/nathanbaxter-com-publii.md.
      [
        { hostname = "nathanbaxter.com", service = "http://caddy:80", path = null, origin_request = null },
        { hostname = "www.nathanbaxter.com", service = "http://caddy:80", path = null, origin_request = null },
      ],
      [
        { service = "http_status:404" },
      ],
    )
  }
}
