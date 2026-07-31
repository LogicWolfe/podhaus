# ssh.pod.haus — browser-rendered SSH to bilby's host sshd, gated by
# Cloudflare Access (Family). Lets a shell reach bilby from any
# browser (e.g. iPad Safari) with no SSH client and no Cloudflare/
# Tailscale app — the use case being able to run `op-unlock` remotely.
#
# Shape mirrors the proven `pine_lake_ssh` app in access.tf: an inline
# `type = "ssh"` Access application (the type value IS the browser-
# rendering switch — there is no separate toggle in the API/provider),
# not the pod_haus_service module (which models HTTP self_hosted apps
# via `destinations`; SSH apps use `domain`/`self_hosted_domains`).
#
# Auth is passwordless via a short-lived SSH certificate: Cloudflare
# mints a cert whose principal is the user's email prefix. Nathan's browser
# terminal therefore maps directly to the `nathan` unix account. Sky uses a
# native SSH client through `cloudflared access ssh`, explicitly selects the
# `nathan` account, and authenticates with her provisioned public key. bilby's
# sshd trusts the CA via TrustedUserCAKeys and installs Sky's key via
# bilby/host-sshd/install.sh. Password auth stays enabled as a fallback.
#
# Browser-rendered apps support only Allow/Block policies — service-
# token bypass is unsupported, so this uses the Allow-only Family policy
# directly, not the default service-token-bypass chain.
#
# Reference docs:
#   - zero_trust_access_application (type enum incl. "ssh"):
#     https://registry.terraform.io/providers/cloudflare/cloudflare/latest/docs/resources/zero_trust_access_application
#   - zero_trust_access_short_lived_certificate:
#     https://registry.terraform.io/providers/cloudflare/cloudflare/latest/docs/resources/zero_trust_access_short_lived_certificate
#   - browser-rendered terminal + legacy short-lived certs:
#     https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/use-cases/ssh/ssh-browser-rendering/

resource "cloudflare_dns_record" "ssh_pod_haus" {
  zone_id = local.zones["pod.haus"]
  name    = "ssh.pod.haus"
  type    = "CNAME"
  content = local.tunnels.pod_haus
  proxied = true
  ttl     = 1
  settings = {
    flatten_cname = false
    ipv4_only     = false
    ipv6_only     = false
  }
}

resource "cloudflare_zero_trust_access_application" "bilby_ssh" {
  account_id          = var.account_id
  name                = "Bilby SSH"
  type                = "ssh"
  domain              = "ssh.pod.haus"
  self_hosted_domains = ["ssh.pod.haus"]
  session_duration    = "730h"

  auto_redirect_to_identity  = false
  enable_binding_cookie      = false
  options_preflight_bypass   = false
  app_launcher_visible       = true
  http_only_cookie_attribute = false

  policies = [
    { precedence = 1, id = cloudflare_zero_trust_access_policy.pod_haus_family_allow.id },
  ]
}

# CA whose short-lived certs bilby's sshd trusts. public_key → the
# OpenSSH CA line installed at /etc/ssh/cloudflare_ca.pub on bilby.
resource "cloudflare_zero_trust_access_short_lived_certificate" "bilby_ssh" {
  account_id = var.account_id
  app_id     = cloudflare_zero_trust_access_application.bilby_ssh.id
}

output "ssh_ca_public_key" {
  description = "Cloudflare Access SSH CA public key for ssh.pod.haus. Install on bilby as TrustedUserCAKeys (bilby/host-sshd/install.sh)."
  value       = cloudflare_zero_trust_access_short_lived_certificate.bilby_ssh.public_key
}
