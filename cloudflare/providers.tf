provider "cloudflare" {
  # api_token from CLOUDFLARE_API_TOKEN — set by the chezmoi-rendered
  # ~/.config/fish/conf.d/podhaus-tf.fish (no wrapper).
}

provider "unifi" {
  # Reach the controller via its public tunnel hostname (module.unifi
  # publishes unifi.pod.haus → the controller), so Terraform runs from
  # any machine, not just the LAN. api_key from UNIFI_API_KEY (chezmoi
  # env file). The tunnel presents a valid Cloudflare edge cert, so no
  # allow_insecure needed.
  api_url = "https://unifi.pod.haus"
}

provider "github" {
  owner = "LogicWolfe"
  # token from GITHUB_TOKEN (chezmoi env file).
}

provider "tailscale" {
  # OAuth client credentials from TAILSCALE_OAUTH_CLIENT_ID /
  # TAILSCALE_OAUTH_CLIENT_SECRET (chezmoi env file). Same OAuth client
  # the tailscale-cleanup init uses; scope auth_keys:write is what mints
  # the rotating tailnet key. tailnet arg omitted — defaults to the
  # tailnet that owns the OAuth client.
}
