# ssh.pod.haus — browser-rendered SSH to bilby's host sshd, gated by
# Cloudflare Access (Nathan only). Lets a shell reach bilby from any
# browser (e.g. iPad Safari) with no SSH client and no Cloudflare/
# Tailscale app — the use case being able to run `op-unlock` remotely.
#
# Shape mirrors the proven `pine_lake_ssh` app in access.tf: an inline
# `type = "ssh"` Access application (the type value IS the browser-
# rendering switch — there is no separate toggle in the API/provider),
# not the pod_haus_service module (which models HTTP self_hosted apps).
#
# Auth is passwordless via a short-lived SSH certificate: Cloudflare
# mints a cert whose principal is the user's email prefix (`nathan` ←
# nathan@nathanbaxter.com), which matches the `nathan` unix account on
# bilby, so no `Match`/AuthorizedPrincipals mapping is needed. bilby's
# sshd trusts the CA via TrustedUserCAKeys (installed by
# bilby/host-sshd/install.sh from the ssh_ca_public_key output below).
# Password auth stays enabled on bilby as a fallback.
#
# Browser-rendered apps support only Allow/Block policies — service-
# token bypass is unsupported — so this uses the Allow-only `nathan`
# policy directly, not the default service-token-bypass chain.
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
  type    = "A"
  content = local.numbat_relay_ipv4
  proxied = false
  ttl     = 300
}

resource "cloudflare_zero_trust_access_application" "bilby_ssh" {
  account_id       = var.account_id
  name             = "Bilby SSH"
  type             = "ssh"
  domain           = "ssh.pod.haus"
  destinations     = [{ type = "public", uri = "ssh.pod.haus" }]
  session_duration = "730h"

  auto_redirect_to_identity  = false
  enable_binding_cookie      = false
  options_preflight_bypass   = false
  app_launcher_visible       = true
  http_only_cookie_attribute = false

  policies = [
    { precedence = 1, id = cloudflare_zero_trust_access_policy.nathan.id },
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
