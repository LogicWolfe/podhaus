provider "cloudflare" {
  # api_token comes from CLOUDFLARE_API_TOKEN env var (set by `./tf` via op run).
}

provider "unifi" {
  # api_url + api_key + insecure-TLS allowance come from env (UNIFI_API_URL,
  # UNIFI_API_KEY, UNIFI_INSECURE) injected by `./tf` via op run. The
  # controller speaks HTTPS to its own self-signed cert, so allow_insecure
  # is required.
  api_url        = "https://10.0.0.1"
  allow_insecure = true
}

provider "github" {
  owner = "LogicWolfe"
  # token comes from GITHUB_TOKEN env var (set by ./tf via op run).
}
