# indigopod.au — public host for the pets-alive pet simulator.
# Zone is on Cloudflare (zone id in variables.tf locals.zones).
#
# pets-alive.indigopod.au is intentionally PUBLIC: there is NO Cloudflare
# Access application gating it (her friends authenticate to the game
# itself via the in-app edit password / play sessions, not at the edge).
# Same "public site, no Access app" pattern as nathanbaxter.com. Routing:
# proxied CNAME → pod.haus tunnel; the matching ingress rule lives in
# tunnel.tf.

resource "cloudflare_dns_record" "pets_alive_indigopod" {
  zone_id = local.zones["indigopod.au"]
  name    = "pets-alive.indigopod.au"
  type    = "CNAME"
  content = local.tunnels.pod_haus
  proxied = true
  ttl     = 1
}
