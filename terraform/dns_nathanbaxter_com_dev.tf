# dev.nathanbaxter.com — live-reload Astro dev preview of the
# nathanbaxter.com site, served by the nathanbaxter-dev container on
# bilby (see podhaus/nathanbaxter-dev/). Pomerium protects it; it isn't a
# production endpoint. Separate file from
# dns_nathanbaxter_com{,_web}.tf so production CNAMEs are never
# touched alongside dev-cycle changes.

resource "cloudflare_dns_record" "nathanbaxter_com_dev" {
  zone_id = local.zones["nathanbaxter.com"]
  name    = "dev.nathanbaxter.com"
  type    = "A"
  content = local.numbat_application_ipv4
  proxied = false
  ttl     = 300
}
