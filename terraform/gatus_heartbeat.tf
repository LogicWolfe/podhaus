# Sky's laptop is outside the Cloudflare Access session boundary, so expose
# only its Gatus push endpoint. The wildcard application continues to protect
# the dashboard and every other Gatus route; Gatus authenticates this POST with
# the shared heartbeat bearer token before accepting it.
resource "cloudflare_zero_trust_access_application" "gatus_sky_laptop_heartbeat" {
  account_id       = var.account_id
  name             = "gatus.pod.haus Sky laptop backup heartbeat"
  type             = "self_hosted"
  session_duration = "730h"

  destinations = [
    {
      type = "public"
      uri  = "gatus.pod.haus/api/v1/endpoints/backup_sky-laptop/external"
    },
  ]

  auto_redirect_to_identity  = false
  enable_binding_cookie      = false
  options_preflight_bypass   = false
  app_launcher_visible       = false
  http_only_cookie_attribute = true

  policies = [
    { precedence = 1, id = cloudflare_zero_trust_access_policy.public_bypass.id },
  ]
}
