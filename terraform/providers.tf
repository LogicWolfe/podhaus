# Provider configurations for the consolidated podhaus root.
#
# The chezmoi-installed fish hook runs `op inject` when the shell enters
# ~/repos/podhaus, exports the standard provider variables, and unsets them on
# exit. The Homelab-scoped 1P service-account token is the only raw secret on
# disk; the AWS credentials are limited to the terraform-state bucket.

provider "cloudflare" {
  # api_token from CLOUDFLARE_API_TOKEN env var (PWD-scoped op inject).
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
  # TAILSCALE_OAUTH_CLIENT_SECRET env vars. Same OAuth client the
  # tailscale-cleanup init uses. It deliberately has the broad `all`
  # scope for current and future Terraform ownership. tailnet arg
  # omitted; it defaults to the tailnet that owns the OAuth client.
}

provider "digitalocean" {
  # token from DIGITALOCEAN_TOKEN env var.
}

data "onepassword_item" "binarylane_api_token" {
  vault = data.onepassword_vault.homelab.uuid
  title = "BinaryLane podhaus-terraform"
}

provider "binarylane" {
  api_token = data.onepassword_item.binarylane_api_token.credential
}

provider "minio" {
  # MinIO admin API (for IAM resources) is served on storage.pod.haus
  # alongside S3 — Caddy proxies the full API; SigV4 is the boundary.
  # Provider auths as MinIO root (full reach; scoped admin creds are
  # escalation-capable anyway). Creds from TF_VAR_minio_user /
  # TF_VAR_minio_password env vars (op://Homelab/MinIO Root).
  minio_server   = "storage.pod.haus"
  minio_ssl      = true
  minio_region   = "us-east-1"
  minio_user     = var.minio_user
  minio_password = var.minio_password
}

# Standard login fields make this newly-created root credential readable by
# the 1Password data source. The aliased provider reaches the full admin API
# through the public endpoint, preserving the from-any-machine TF contract.
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

# The 1Password provider is deliberately selective. Backend and provider
# credentials use the PWD hook; data sources and managed items stay here when
# their field shapes are stable, as with Pocket ID, Pouch MinIO, and Forgejo.

provider "pocketid" {
  # Public by design: OIDC relying parties and Terraform must reach the
  # issuer without Cloudflare Access in front. The API token is resolved
  # from 1Password at plan time and never committed.
  base_url  = "https://id.pod.haus"
  api_token = data.onepassword_item.pocket_id_api_key.credential
}
