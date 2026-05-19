# Public ingress for the MinIO S3 endpoint: WAN tcp/443 → bilby:443
# (Caddy). This is the fleet's first deliberate WAN port-forward — the
# rest of pod.haus is Cloudflare-Tunnel-only. Justified because the S3
# data path cannot traverse Cloudflare's HTTP proxy (SigV4 / cert).
# See docs/plans/minio-public-caddy.md.
#
# Schema is the `ubiquiti-community/unifi ~> 0.41` provider's
# unifi_port_forward — `terraform plan` validates against the pinned
# version; adjust if it differs from the registry docs.
resource "unifi_port_forward" "minio_caddy_https" {
  name     = "storage.pod.haus (MinIO via Caddy)"
  protocol = "tcp"

  wan = {
    port = "443"
  }

  forward = {
    ip   = "10.0.0.119"
    port = "443"
  }
}
