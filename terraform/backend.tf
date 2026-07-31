# Consolidated podhaus Terraform root. One state, one apply, every
# provider for the whole fleet — replaces the historical split between
# cloudflare/, minio/terraform/, and the relay-only terraform/. See
# /docs/terraform.html for the bootstrap story (komodo-start guarantees
# the terraform-state bucket; one apply needs only the 1P service-
# account token + the PWD-scoped MinIO bucket creds).
terraform {
  required_version = ">= 1.10.0"

  required_providers {
    cloudflare = {
      # DNS, Access apps + policies, Tunnel config, GitHub webhook
      # bypass, the whole pod.haus wildcard.
      source  = "cloudflare/cloudflare"
      version = "~> 5.0"
    }
    unifi = {
      # Community fork — the upstream paultyng/unifi provider doesn't
      # expose a dns_record resource. ubiquiti-community has feature
      # parity plus the UniFi DNS records the controller added more
      # recently.
      # Docs: https://registry.terraform.io/providers/ubiquiti-community/unifi/latest/docs
      source = "ubiquiti-community/unifi"
      # Pin to the MINOR (~> 0.53.0 = >=0.53.0 <0.54.0). This is a 0.x
      # provider, so minor bumps carry breaking changes (0.41 → 0.53 moved
      # dns_record.ttl from an int to a Go duration string). A two-segment
      # ~> 0.53 would still allow those breaks; bump deliberately + test.
      version = "~> 0.53.0"
    }
    github = {
      # Used only for the Komodo deploy webhook on LogicWolfe/podhaus.
      # Docs: https://registry.terraform.io/providers/integrations/github/latest/docs
      source  = "integrations/github"
      version = "~> 6.0"
    }
    tailscale = {
      # Mints the rotating tag:podnet tailnet auth key (cloudflare/
      # was the interim home; now native here).
      # Docs: https://registry.terraform.io/providers/tailscale/tailscale/latest/docs
      source  = "tailscale/tailscale"
      version = "~> 0.21"
    }
    time = {
      # Drives the 80-day rotation cadence for the tailnet auth key.
      source  = "hashicorp/time"
      version = "~> 0.13"
    }
    digitalocean = {
      # kookaburra relay droplet + reserved IP + firewall + project.
      source  = "digitalocean/digitalocean"
      version = "~> 2.0"
    }
    minio = {
      # MinIO IAM + bucket policies for the public Publii tenants
      # (nathanbaxter-com, future skycroeser-net …). Server is
      # storage.pod.haus (Caddy → MinIO; full API including admin).
      # Docs: https://registry.terraform.io/providers/aminueza/minio/latest/docs
      source  = "aminueza/minio"
      version = "~> 3.0"
    }
    onepassword = {
      # Resolves provider credentials from 1Password's Homelab vault at
      # plan time, so nothing except the SA token itself sits raw on
      # disk. service_account_token from OP_SERVICE_ACCOUNT_TOKEN env.
      # 3.x adds section_map (we need it for items with root-level
      # custom fields like "credential", "client id"/"client secret").
      # Docs: https://registry.terraform.io/providers/1Password/onepassword/latest/docs
      source  = "1Password/onepassword"
      version = "~> 3.1" # section_map/field_map (v3.1.0+) for the access.tf Pocket ID OIDC data source
    }
    pocketid = {
      # Pocket ID is authoritative for human identities, application
      # access groups and OIDC claims (including Forgejo SSH keys).
      # Pin the minor: this is a young community provider and schema
      # changes must be reviewed deliberately.
      # Docs: https://registry.terraform.io/providers/Trozz/pocketid/latest/docs
      source  = "Trozz/pocketid"
      version = "~> 2.1.0"
    }
  }

  backend "s3" {
    endpoints = {
      # Public endpoint so Terraform runs from any machine. Path goes
      # storage.pod.haus → (split-horizon on LAN / kookaburra rathole
      # off-LAN) → bilby Caddy → MinIO. SigV4 is the boundary; nothing
      # is host- or LAN-pinned.
      s3 = "https://storage.pod.haus"
    }
    bucket                      = "terraform-state"
    key                         = "podhaus.tfstate"
    region                      = "us-east-1"
    use_path_style              = true
    skip_credentials_validation = true
    skip_region_validation      = true
    skip_metadata_api_check     = true
    skip_requesting_account_id  = true
    use_lockfile                = true
    encrypt                     = false
  }
}
