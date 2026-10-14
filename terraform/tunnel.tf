# The relay PKI for wstunnel, the outbound tunnels that carry every service
# into Numbat.
#
# Both directions are pinned to this CA. Numbat's server requires a client
# certificate it signed, and takes the certificate's common name as the only
# upgrade path the client may use, which its restrictions file maps to the
# listeners that client owns. Clients verify Numbat's certificate against
# this CA alone, by pointing SSL_CERT_FILE at it.

locals {
  # One client certificate per tunnel client, common name = inventory host.
  tunnel_clients = toset([
    "bandicoot",
    "bilby",
    "fractal",
    "kangaroo",
    "nb-macbook-air",
    "pinelake",
    "quokka",
    "voltaire",
  ])
}

resource "tls_private_key" "tunnel_ca" {
  algorithm   = "ECDSA"
  ecdsa_curve = "P256"
}

resource "tls_self_signed_cert" "tunnel_ca" {
  private_key_pem = tls_private_key.tunnel_ca.private_key_pem

  subject {
    common_name  = "podhaus relay tunnel CA"
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

resource "tls_private_key" "tunnel_server" {
  algorithm   = "ECDSA"
  ecdsa_curve = "P256"
}

resource "tls_cert_request" "tunnel_server" {
  private_key_pem = tls_private_key.tunnel_server.private_key_pem
  dns_names       = ["relay.numbat.pod.haus"]

  subject {
    common_name  = "relay.numbat.pod.haus"
    organization = "podhaus"
  }
}

resource "tls_locally_signed_cert" "tunnel_server" {
  cert_request_pem   = tls_cert_request.tunnel_server.cert_request_pem
  ca_private_key_pem = tls_private_key.tunnel_ca.private_key_pem
  ca_cert_pem        = tls_self_signed_cert.tunnel_ca.cert_pem

  validity_period_hours = 43800
  # Any apply in the last 90 days renews it, so expiry never arrives first.
  early_renewal_hours = 2160
  allowed_uses = [
    "server_auth",
    "digital_signature",
    "key_encipherment",
  ]
}

resource "tls_private_key" "tunnel_client" {
  for_each    = local.tunnel_clients
  algorithm   = "ECDSA"
  ecdsa_curve = "P256"
}

resource "tls_cert_request" "tunnel_client" {
  for_each        = local.tunnel_clients
  private_key_pem = tls_private_key.tunnel_client[each.key].private_key_pem

  subject {
    common_name  = each.key
    organization = "podhaus"
  }
}

resource "tls_locally_signed_cert" "tunnel_client" {
  for_each           = local.tunnel_clients
  cert_request_pem   = tls_cert_request.tunnel_client[each.key].cert_request_pem
  ca_private_key_pem = tls_private_key.tunnel_ca.private_key_pem
  ca_cert_pem        = tls_self_signed_cert.tunnel_ca.cert_pem

  validity_period_hours = 43800
  # Any apply in the last 90 days renews it, so expiry never arrives first.
  early_renewal_hours = 2160
  allowed_uses = [
    "client_auth",
    "digital_signature",
    "key_encipherment",
  ]
}

resource "onepassword_item" "numbat_tunnel" {
  vault    = data.onepassword_vault.homelab.uuid
  title    = "Numbat Tunnel"
  category = "secure_note"
  tags     = ["terraform-managed"]

  section_map = {
    PKI = {
      field_map = merge(
        {
          ca_cert_b64 = {
            type  = "CONCEALED"
            value = base64encode(tls_self_signed_cert.tunnel_ca.cert_pem)
          }
          server_cert_b64 = {
            type  = "CONCEALED"
            value = base64encode(tls_locally_signed_cert.tunnel_server.cert_pem)
          }
          server_key_b64 = {
            type  = "CONCEALED"
            value = base64encode(tls_private_key.tunnel_server.private_key_pem)
          }
        },
        { for host in local.tunnel_clients : "${host}_cert_b64" => {
          type  = "CONCEALED"
          value = base64encode(tls_locally_signed_cert.tunnel_client[host].cert_pem)
        } },
        { for host in local.tunnel_clients : "${host}_key_b64" => {
          type  = "CONCEALED"
          value = base64encode(tls_private_key.tunnel_client[host].private_key_pem)
        } },
      )
    }
  }
}
