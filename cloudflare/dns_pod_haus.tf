# pod.haus DNS records.
#
# Tunnel-routed CNAMEs share the same target (`local.tunnels.pod_haus`)
# and proxied=true so cloudflared sees the request; external CNAMEs
# (Fastmail DKIM, Postmark, Railway) sit unproxied with ttl=300 because
# they need DNS-level pass-through.

locals {
  # Tunnel-routed subdomains. Adding a new service? Drop its short name
  # in this set, run `../tf plan` — record is created automatically.
  pod_haus_tunnel_cnames = toset([
    "backup",
    "docs",
    "gatus",
    "grafana",
    "home",
    "kangaroo",
    "kangaroo-backup",
    "komodo",
    "logs",
    "minio",
    "paperless",
    "plex",
    "sync",
    "torrent",
    "unifi",
  ])

  # External CNAMEs: { name => { content, ttl } }. proxied=false on all.
  pod_haus_external_cnames = {
    "fm1._domainkey" = { content = "fm1.pod.haus.dkim.fmhosted.com" }
    "fm2._domainkey" = { content = "fm2.pod.haus.dkim.fmhosted.com" }
    "fm3._domainkey" = { content = "fm3.pod.haus.dkim.fmhosted.com" }
    "pm-bounces"     = { content = "pm.mtasv.net" }
    "doggos.indigo"  = { content = "x0y6bs3z.up.railway.app" }
    "yiayia"         = { content = "06r38qgz.up.railway.app" }
  }
}

resource "cloudflare_dns_record" "pod_haus_tunnel" {
  for_each = local.pod_haus_tunnel_cnames
  zone_id  = local.zones["pod.haus"]
  name     = "${each.key}.pod.haus"
  type     = "CNAME"
  content  = local.tunnels.pod_haus
  proxied  = true
  ttl      = 1
  settings = {
    flatten_cname = false
    ipv4_only     = false
    ipv6_only     = false
  }
}

resource "cloudflare_dns_record" "pod_haus_external_cname" {
  for_each = local.pod_haus_external_cnames
  zone_id  = local.zones["pod.haus"]
  name     = "${each.key}.pod.haus"
  type     = "CNAME"
  content  = each.value.content
  proxied  = false
  ttl      = 300
  settings = {
    flatten_cname = false
    ipv4_only     = false
    ipv6_only     = false
  }
}

# MX records — apex, Fastmail primary + secondary.
resource "cloudflare_dns_record" "pod_haus_mx" {
  for_each = {
    "10" = "in1-smtp.messagingengine.com"
    "20" = "in2-smtp.messagingengine.com"
  }
  zone_id  = local.zones["pod.haus"]
  name     = "pod.haus"
  type     = "MX"
  content  = each.value
  priority = tonumber(each.key)
  ttl      = 300
}

# TXT records.
resource "cloudflare_dns_record" "pod_haus_txt_spf" {
  zone_id = local.zones["pod.haus"]
  name    = "pod.haus"
  type    = "TXT"
  content = "\"v=spf1 include:spf.messagingengine.com ?all\""
  ttl     = 300
}

# Fastmail empty-DKIM placeholder. Lives at the apex for rotation; the
# active DKIM keys are the fm1/fm2/fm3 CNAMEs above.
resource "cloudflare_dns_record" "pod_haus_txt_dkim_rotation" {
  zone_id = local.zones["pod.haus"]
  name    = "pod.haus"
  type    = "TXT"
  content = "\"k=rsa;p=\""
  ttl     = 300
}

# Postmark DKIM. Selector encodes the date it was issued.
resource "cloudflare_dns_record" "pod_haus_txt_postmark_dkim" {
  zone_id = local.zones["pod.haus"]
  name    = "20260118155237pm._domainkey.pod.haus"
  type    = "TXT"
  content = "\"k=rsa;p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCIH3KJg5M/6mLqrDZYGuTlo/giMs3jPAOQTDo0P98+Nn4/9+bJci69Gn+i+TUgJDtzftYVi+532+di1NQn2uaZiaw2IjSk1/kanoiexsSrge0oVXCGgAuMXkrWdHk5OO2S90dpmDho+enbWbuxdrOob7BfyZIkSmz6m9s37lW2fQIDAQAB\""
  ttl     = 300
  comment = "Postmark DKIM"
}
