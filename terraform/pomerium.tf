resource "random_password" "pomerium_shared_secret" {
  length  = 32
  special = false
}

resource "random_password" "pomerium_cookie_secret" {
  length  = 32
  special = false
}

resource "random_password" "pomerium_gateway_tokens" {
  for_each = toset([
    "hyperdx_mcp",
    "paperless_api",
  ])

  length  = 64
  special = false
}

resource "random_password" "numbat_rathole_tokens" {
  for_each = toset([
    "bilby_ssh",
    "forgejo_ssh",
    "protected_http",
    "public_tls",
    "voltaire_ssh",
  ])

  length  = 64
  special = false
}

resource "tls_private_key" "pomerium_ssh_user_ca" {
  algorithm = "ED25519"
}

resource "tls_private_key" "pomerium_ssh_host" {
  algorithm = "ED25519"
}

resource "tls_private_key" "pomerium_origin_ca" {
  algorithm = "RSA"
  rsa_bits  = 3072
}

resource "tls_self_signed_cert" "pomerium_origin_ca" {
  private_key_pem = tls_private_key.pomerium_origin_ca.private_key_pem

  subject {
    common_name  = "podhaus Pomerium origin CA"
    organization = "podhaus"
  }

  is_ca_certificate     = true
  validity_period_hours = 87600
  allowed_uses = [
    "cert_signing",
    "crl_signing",
    "digital_signature",
  ]
}

resource "tls_private_key" "pomerium_origin_client" {
  algorithm = "RSA"
  rsa_bits  = 3072
}

resource "tls_private_key" "pomerium_origin_server" {
  algorithm = "RSA"
  rsa_bits  = 3072
}

resource "tls_cert_request" "pomerium_origin_server" {
  private_key_pem = tls_private_key.pomerium_origin_server.private_key_pem
  dns_names       = ["pomerium-origin.pod.haus"]

  subject {
    common_name  = "pomerium-origin.pod.haus"
    organization = "podhaus"
  }
}

resource "tls_locally_signed_cert" "pomerium_origin_server" {
  cert_request_pem   = tls_cert_request.pomerium_origin_server.cert_request_pem
  ca_private_key_pem = tls_private_key.pomerium_origin_ca.private_key_pem
  ca_cert_pem        = tls_self_signed_cert.pomerium_origin_ca.cert_pem

  validity_period_hours = 43800
  allowed_uses = [
    "server_auth",
    "digital_signature",
    "key_encipherment",
  ]
}

resource "tls_private_key" "pomerium_signing" {
  algorithm   = "ECDSA"
  ecdsa_curve = "P256"
}

resource "tls_cert_request" "pomerium_origin_client" {
  private_key_pem = tls_private_key.pomerium_origin_client.private_key_pem
  dns_names       = ["pomerium.numbat.pod.haus"]

  subject {
    common_name  = "pomerium.numbat.pod.haus"
    organization = "podhaus"
  }
}

resource "tls_locally_signed_cert" "pomerium_origin_client" {
  cert_request_pem   = tls_cert_request.pomerium_origin_client.cert_request_pem
  ca_private_key_pem = tls_private_key.pomerium_origin_ca.private_key_pem
  ca_cert_pem        = tls_self_signed_cert.pomerium_origin_ca.cert_pem

  validity_period_hours = 43800
  allowed_uses = [
    "client_auth",
    "digital_signature",
    "key_encipherment",
  ]
}

resource "tls_private_key" "log_ingest_ca" {
  algorithm = "RSA"
  rsa_bits  = 3072
}

resource "tls_self_signed_cert" "log_ingest_ca" {
  private_key_pem = tls_private_key.log_ingest_ca.private_key_pem

  subject {
    common_name  = "podhaus log ingestion CA"
    organization = "podhaus"
  }

  is_ca_certificate     = true
  validity_period_hours = 87600
  allowed_uses = [
    "cert_signing",
    "crl_signing",
    "digital_signature",
  ]
}

resource "tls_private_key" "numbat_log_client" {
  algorithm = "RSA"
  rsa_bits  = 3072
}

resource "tls_cert_request" "numbat_log_client" {
  private_key_pem = tls_private_key.numbat_log_client.private_key_pem
  dns_names       = ["numbat.pod.haus"]

  subject {
    common_name  = "numbat.pod.haus"
    organization = "podhaus"
  }
}

resource "tls_locally_signed_cert" "numbat_log_client" {
  cert_request_pem   = tls_cert_request.numbat_log_client.cert_request_pem
  ca_private_key_pem = tls_private_key.log_ingest_ca.private_key_pem
  ca_cert_pem        = tls_self_signed_cert.log_ingest_ca.cert_pem

  validity_period_hours = 43800
  allowed_uses = [
    "client_auth",
    "digital_signature",
    "key_encipherment",
  ]
}

resource "onepassword_item" "numbat_rathole" {
  vault    = data.onepassword_vault.homelab.uuid
  title    = "Numbat Rathole"
  category = "secure_note"
  tags     = ["terraform-managed"]

  section_map = {
    Tokens = {
      field_map = {
        for name, token in random_password.numbat_rathole_tokens : name => {
          type  = "CONCEALED"
          value = token.result
        }
      }
    }
  }
}

resource "onepassword_item" "pomerium_secrets" {
  vault    = data.onepassword_vault.homelab.uuid
  title    = "Pomerium Secrets"
  category = "secure_note"
  tags     = ["terraform-managed"]

  section_map = {
    Secrets = {
      field_map = {
        shared_secret = {
          type  = "CONCEALED"
          value = base64encode(random_password.pomerium_shared_secret.result)
        }
        cookie_secret = {
          type  = "CONCEALED"
          value = base64encode(random_password.pomerium_cookie_secret.result)
        }
        ssh_user_ca_key_b64 = {
          type  = "CONCEALED"
          value = base64encode(tls_private_key.pomerium_ssh_user_ca.private_key_openssh)
        }
        ssh_host_key_b64 = {
          type  = "CONCEALED"
          value = base64encode(tls_private_key.pomerium_ssh_host.private_key_openssh)
        }
        origin_client_cert_b64 = {
          type  = "CONCEALED"
          value = base64encode(tls_locally_signed_cert.pomerium_origin_client.cert_pem)
        }
        origin_client_key_b64 = {
          type  = "CONCEALED"
          value = base64encode(tls_private_key.pomerium_origin_client.private_key_pem)
        }
        signing_key_b64 = {
          type  = "CONCEALED"
          value = base64encode(tls_private_key.pomerium_signing.private_key_pem)
        }
      }
    }
  }
}

resource "onepassword_item" "pomerium_origin_pki" {
  vault    = data.onepassword_vault.homelab.uuid
  title    = "Pomerium Origin PKI"
  category = "secure_note"
  tags     = ["terraform-managed"]

  section_map = {
    PKI = {
      field_map = {
        ca_cert_b64 = {
          type  = "CONCEALED"
          value = base64encode(tls_self_signed_cert.pomerium_origin_ca.cert_pem)
        }
        ca_key_b64 = {
          type  = "CONCEALED"
          value = base64encode(tls_private_key.pomerium_origin_ca.private_key_pem)
        }
        server_cert_b64 = {
          type  = "CONCEALED"
          value = base64encode(tls_locally_signed_cert.pomerium_origin_server.cert_pem)
        }
        server_key_b64 = {
          type  = "CONCEALED"
          value = base64encode(tls_private_key.pomerium_origin_server.private_key_pem)
        }
      }
    }
  }
}

resource "onepassword_item" "log_ingest_pki" {
  vault    = data.onepassword_vault.homelab.uuid
  title    = "Log Ingest PKI"
  category = "secure_note"
  tags     = ["terraform-managed"]

  section_map = {
    PKI = {
      field_map = {
        ca_cert_b64 = {
          type  = "CONCEALED"
          value = base64encode(tls_self_signed_cert.log_ingest_ca.cert_pem)
        }
        ca_key_b64 = {
          type  = "CONCEALED"
          value = base64encode(tls_private_key.log_ingest_ca.private_key_pem)
        }
        numbat_cert_b64 = {
          type  = "CONCEALED"
          value = base64encode(tls_locally_signed_cert.numbat_log_client.cert_pem)
        }
        numbat_key_b64 = {
          type  = "CONCEALED"
          value = base64encode(tls_private_key.numbat_log_client.private_key_pem)
        }
      }
    }
  }
}

resource "pocketid_group" "pomerium_users" {
  name          = "pomerium-users"
  friendly_name = "Pomerium users"
}

resource "pocketid_client" "pomerium" {
  name      = "Pomerium"
  client_id = "pomerium"

  callback_urls = [
    "https://authenticate.pod.haus/oauth2/callback",
  ]
  logout_callback_urls = [
    "https://authenticate.pod.haus/",
  ]

  launch_url                = "https://edge-canary.pod.haus/"
  is_public                 = false
  pkce_enabled              = true
  requires_reauthentication = false

  allowed_user_groups = [
    pocketid_group.pomerium_users.id,
  ]
}

resource "onepassword_item" "pomerium_oidc" {
  vault    = data.onepassword_vault.homelab.uuid
  title    = "Pomerium OIDC"
  category = "login"
  url      = "https://authenticate.pod.haus"
  username = pocketid_client.pomerium.client_id
  password = pocketid_client.pomerium.client_secret
  tags     = ["terraform-managed"]
}

resource "onepassword_item" "pomerium_gateway_tokens" {
  vault    = data.onepassword_vault.homelab.uuid
  title    = "Pomerium Gateway Tokens"
  category = "secure_note"
  tags     = ["terraform-managed"]

  section_map = {
    Tokens = {
      field_map = {
        for name, token in random_password.pomerium_gateway_tokens : name => {
          type  = "CONCEALED"
          value = token.result
        }
      }
    }
  }
}

resource "cloudflare_dns_record" "pomerium_authenticate" {
  zone_id = local.zones["pod.haus"]
  name    = "authenticate.pod.haus"
  type    = "A"
  content = local.numbat_application_ipv4
  proxied = false
  ttl     = 300
}

resource "cloudflare_dns_record" "pomerium_edge_canary" {
  zone_id = local.zones["pod.haus"]
  name    = "edge-canary.pod.haus"
  type    = "A"
  content = local.numbat_application_ipv4
  proxied = false
  ttl     = 300
}

resource "cloudflare_dns_record" "numbat_core_connect" {
  zone_id = local.zones["pod.haus"]
  name    = "core-connect.pod.haus"
  type    = "A"
  content = local.numbat_relay_ipv4
  proxied = false
  ttl     = 300
}

resource "cloudflare_dns_record" "numbat_logs_ingest" {
  zone_id = local.zones["pod.haus"]
  name    = "logs-ingest.pod.haus"
  type    = "A"
  content = local.numbat_relay_ipv4
  proxied = false
  ttl     = 300
}

resource "cloudflare_dns_record" "numbat_paperless_api" {
  zone_id = local.zones["pod.haus"]
  name    = "paperless-api.pod.haus"
  type    = "A"
  content = local.numbat_relay_ipv4
  proxied = false
  ttl     = 300
}

output "pomerium_ssh_user_ca_public_key" {
  description = "Pomerium User CA public key to trust on SSH target hosts."
  value       = tls_private_key.pomerium_ssh_user_ca.public_key_openssh
}
