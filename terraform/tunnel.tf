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
    module.music.ingress_rule,
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
      # ssh.pod.haus → bilby host sshd over the dockernet bridge gateway
      # (same 172.18.0.1 host-reach pattern as Plex/Home Assistant).
      # Inline rather than a module rule because it's a `type = "ssh"`
      # browser-rendered app — see ssh_pod_haus.tf.
      [
        { hostname = "ssh.pod.haus", service = "ssh://172.18.0.1:22", path = null, origin_request = null },
      ],
      # nathanbaxter.com public static site → Caddy (NOT a pod.haus
      # module / NOT Access-gated; cloudflared serves any zone). Caddy
      # maps it to the nathanbaxter-com bucket.
      # dev.nathanbaxter.com → nathanbaxter-dev Astro dev container
      # (Access-gated to Nathan; see access.tf + nathanbaxter-dev/).
      [
        { hostname = "nathanbaxter.com", service = "http://caddy:80", path = null, origin_request = null },
        { hostname = "www.nathanbaxter.com", service = "http://caddy:80", path = null, origin_request = null },
        { hostname = "dev.nathanbaxter.com", service = "http://nathanbaxter-dev:4321", path = null, origin_request = null },
      ],
      # pets.indigopod.au public game → the pets engine
      # container. NOT Access-gated (her friends sign in to the game
      # itself, not at the edge); cloudflared serves any zone. DNS CNAME
      # in dns_indigopod_au.tf.
      [
        { hostname = "pets.indigopod.au", service = "http://pets:8000", path = null, origin_request = null },
      ],
      [
        { service = "http_status:404" },
      ],
    )
  }
}
