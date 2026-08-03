# ssh.pod.haus is Pomerium's native SSH listener on Numbat's relay address.

resource "cloudflare_dns_record" "ssh_pod_haus" {
  zone_id = local.zones["pod.haus"]
  name    = "ssh.pod.haus"
  type    = "A"
  content = local.numbat_relay_ipv4
  proxied = false
  ttl     = 300
}
