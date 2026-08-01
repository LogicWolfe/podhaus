# Inputs for a single pod.haus service exposure.
#
# Reference docs (read before changing anything here):
#   - cloudflare_dns_record:
#     https://registry.terraform.io/providers/cloudflare/cloudflare/latest/docs/resources/dns_record
#   - cloudflare_zero_trust_access_application:
#     https://registry.terraform.io/providers/cloudflare/cloudflare/latest/docs/resources/zero_trust_access_application
#   - cloudflare_zero_trust_tunnel_cloudflared_config (the aggregator consumes
#     the `ingress_rule` output):
#     https://registry.terraform.io/providers/cloudflare/cloudflare/latest/docs/resources/zero_trust_tunnel_cloudflared_config

variable "account_id" {
  description = "Cloudflare account ID."
  type        = string
}

variable "zone_id" {
  description = "Cloudflare zone ID that owns the DNS record (pod.haus)."
  type        = string
}

variable "tunnel_target" {
  description = "Tunnel CNAME target the DNS record points at (e.g. <uuid>.cfargotunnel.com). The DNS proxied=true flag is what makes Cloudflare route requests through the tunnel — the target hostname itself isn't network-reachable."
  type        = string
}

variable "edge_ipv4" {
  description = "Optional DNS-only IPv4 target used during the Pomerium migration. Null retains the proxied Cloudflare Tunnel record for rollback."
  type        = string
  default     = null
}

variable "hostname" {
  description = "Short hostname under pod.haus (no zone suffix). 'gatus' → 'gatus.pod.haus'."
  type        = string
}

variable "backend" {
  description = "Tunnel ingress `service:` value — protocol+address of the origin behind the tunnel. e.g. 'http://gatus:8080' or 'https://10.0.0.1:443'."
  type        = string
}

variable "origin_request" {
  description = "Optional tunnel ingress origin-request overrides (no_tls_verify for self-signed origins, http_host_header, etc.). Null = use cloudflared defaults. Schema mirrors cloudflare_zero_trust_tunnel_cloudflared_config's config.ingress.origin_request — see https://registry.terraform.io/providers/cloudflare/cloudflare/latest/docs/resources/zero_trust_tunnel_cloudflared_config"
  type = object({
    access = optional(object({
      aud_tag   = optional(list(string))
      team_name = optional(string)
      required  = optional(bool)
    }))
    ca_pool                  = optional(string)
    connect_timeout          = optional(number)
    disable_chunked_encoding = optional(bool)
    http2_origin             = optional(bool)
    http_host_header         = optional(string)
    keep_alive_connections   = optional(number)
    keep_alive_timeout       = optional(number)
    match_sn_ito_host        = optional(bool)
    no_happy_eyeballs        = optional(bool)
    no_tls_verify            = optional(bool)
    origin_server_name       = optional(string)
    proxy_type               = optional(string)
    tcp_keep_alive           = optional(number)
    tls_timeout              = optional(number)
  })
  default = null
}

variable "ingress_path" {
  description = "Optional path that the tunnel ingress rule scopes to. Use for path-scoped Access apps (e.g. the Komodo webhook). Null = match all paths."
  type        = string
  default     = null
}

# ---- Access ----

variable "access_policy_ids" {
  description = "Override list of cloudflare_zero_trust_access_policy IDs to attach to this app, in ascending precedence (first entry = precedence 1). Null = use the locked-by-default chain (var.default_bypass_policy_id, var.default_allow_policy_id)."
  type        = list(string)
  default     = null
}

variable "default_bypass_policy_id" {
  description = "Reusable Access policy ID used as precedence 1 by default — typically the Homelab service-token bypass. Required when var.access_policy_ids is null."
  type        = string
  default     = null
}

variable "default_allow_policy_id" {
  description = "Reusable Access policy ID used as precedence 2 by default — typically the Family-allow policy. Required when var.access_policy_ids is null."
  type        = string
  default     = null
}

variable "app_type" {
  description = "Cloudflare Access application type. Default 'self_hosted'. Use 'ssh' for SSH services, etc."
  type        = string
  default     = "self_hosted"
}

variable "session_duration" {
  description = "Access session length. Default 730h (~ 1 month) for normal services."
  type        = string
  default     = "730h"
}

variable "app_launcher_visible" {
  description = "Whether to show the app in the Cloudflare Access App Launcher."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Optional tags on the Access app."
  type        = set(string)
  default     = []
}
