# Provider configurations for the consolidated podhaus root.
#
# `op-vault dev -- op run --env-file=terraform/terraform.env.op` supplies the
# standard provider variables only to Terraform's process tree. The selected
# machine service account grants Homelab access only on Podhaus operators; the
# AWS credentials are limited to the terraform-state bucket.

data "onepassword_vault" "homelab" {
  name = "Homelab"
}

provider "cloudflare" {
  # api_token from CLOUDFLARE_API_TOKEN env var (explicit op run boundary).
}

provider "unifi" {
  # Reach the controller through unifi.pod.haus from every machine.
  # Off-LAN this is Numbat; split DNS sends LAN callers through bilby Caddy,
  # so both paths present a valid certificate. api_key comes from env.
  api_url = "https://unifi.pod.haus"
}

provider "github" {
  owner = "LogicWolfe"
  # token from GITHUB_TOKEN env var.
}

provider "tailscale" {
  # OAuth client credentials from TAILSCALE_OAUTH_CLIENT_ID /
  # TAILSCALE_OAUTH_CLIENT_SECRET env vars. It deliberately has the broad
  # `all` scope for current and future Terraform ownership. tailnet is omitted;
  # it defaults to the tailnet that owns the OAuth client.
}

data "onepassword_item" "binarylane_api_token" {
  vault = data.onepassword_vault.homelab.uuid
  title = "BinaryLane podhaus-terraform"
}

provider "binarylane" {
  api_token = data.onepassword_item.binarylane_api_token.credential
}

provider "minio" {
  # RustFS's S3-compatible API preserves the existing MinIO-provider bucket,
  # versioning, and anonymous-policy resources. IAM uses the native provider.
  minio_server   = "storage.pod.haus"
  minio_ssl      = true
  minio_region   = "us-east-1"
  minio_user     = var.minio_user
  minio_password = var.minio_password
}

# Standard login fields make this newly-created root credential readable by
# the 1Password data source. Both aliased providers use the public endpoint,
# preserving the from-any-machine Terraform contract.
data "onepassword_item" "pouch_minio_root" {
  vault = data.onepassword_vault.homelab.uuid
  title = onepassword_item.pouch_minio_root.title

  depends_on = [onepassword_item.pouch_minio_root]
}

provider "minio" {
  alias = "pouch"

  minio_server   = "pouch.pod.haus"
  minio_ssl      = true
  minio_region   = "us-east-1"
  minio_user     = data.onepassword_item.pouch_minio_root.username
  minio_password = data.onepassword_item.pouch_minio_root.password
}

provider "rustfs" {
  endpoint      = "storage.pod.haus:443"
  ssl           = true
  access_key    = var.minio_user
  access_secret = var.minio_password
}

provider "rustfs" {
  alias = "pouch"

  endpoint      = "pouch.pod.haus:443"
  ssl           = true
  access_key    = data.onepassword_item.pouch_minio_root.username
  access_secret = data.onepassword_item.pouch_minio_root.password
}

# The 1Password provider is deliberately selective. Backend and provider
# credentials use the op run environment file; data sources and managed items stay here when
# their field shapes are stable, as with Pocket ID, Pouch RustFS, and Forgejo.

provider "pocketid" {
  # Public by design: OIDC relying parties and Terraform must reach the
  # issuer without Cloudflare Access in front. The API token is resolved
  # from 1Password at plan time and never committed.
  base_url  = "https://id.pod.haus"
  api_token = data.onepassword_item.pocket_id_api_key.credential
}
