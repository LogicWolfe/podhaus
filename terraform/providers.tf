# Provider configurations for the consolidated podhaus root.
#
# Credentials come from the PWD-scoped chezmoi-rendered fish env
# (~/.config/fish/conf.d/podhaus-tf.fish, loaded by the
# __podhaus_tf_load function on cd into ~/repos/podhaus). All values
# resolve from 1Password's Homelab vault. The 1P service-account
# token is the ONE secret raw on disk (see AGENTS.md); MinIO bucket
# creds (AWS_*) are least-priv-scoped to the terraform-state bucket;
# the rest will move to onepassword TF provider data sources in a
# follow-up (see /docs/plans/terraform-foundation.md — the
# credential-source swap is a separate gated step so it can be
# verified as zero-diff).

provider "cloudflare" {
  # api_token from CLOUDFLARE_API_TOKEN env var.
}

provider "unifi" {
  # Reach the controller via its public tunnel hostname (module.unifi
  # publishes unifi.pod.haus → the controller), so Terraform runs from
  # any machine, not just the LAN. api_key from UNIFI_API_KEY env var.
  # The tunnel presents a valid Cloudflare edge cert, so no
  # allow_insecure needed.
  api_url = "https://unifi.pod.haus"
}

provider "github" {
  owner = "LogicWolfe"
  # token from GITHUB_TOKEN env var.
}

provider "tailscale" {
  # OAuth client credentials from TAILSCALE_OAUTH_CLIENT_ID /
  # TAILSCALE_OAUTH_CLIENT_SECRET env vars. Same OAuth client the
  # tailscale-cleanup init uses; scope auth_keys:write mints the
  # rotating tailnet key. tailnet arg omitted — defaults to the
  # tailnet that owns the OAuth client.
}

provider "digitalocean" {
  # token from DIGITALOCEAN_TOKEN env var.
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
