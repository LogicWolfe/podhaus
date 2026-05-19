<!DOCTYPE html><html><head>
<meta name="doc-group" content="Plans">
<meta name="doc-title" content="Storage public relay">
<title>Storage public ingress relay (DigitalOcean + rathole)</title>
</head><body><!--
NOTE: kept as Markdown-in-HTML-shell only to satisfy the docs sidebar
convention; the body below is plain Markdown and reads fine raw.
-->

# Storage public ingress relay — DigitalOcean droplet + rathole

**Status: PLANNED (not started). All build steps gated.**

## Why this exists

`storage.pod.haus` is unreachable for genuine external clients: the
UDM Pro SE / UniFi OS binds WAN tcp/443 and shadows the port-forward
(full evidence + the dead-ended options 1–3 in
`nathanbaxter-com-publii.md` → OPEN ISSUE). The *same* bug means
remote `terraform` to the `storage.pod.haus` S3 state backend is also
broken from anywhere — the from-anywhere TF hard rule has been
silently violated for every root; only on-LAN split-horizon ever
worked. This relay fixes **both** (Publii publish *and* from-anywhere
Terraform) without Cloudflare (preserves SigV4) and without any home
inbound (sidesteps the UDM entirely).

## Architecture

```
Sky / anywhere ──DNS storage.pod.haus──▶ droplet reserved IP :443
        │                                  (raw TCP — no TLS here)
        ▼  rathole reverse tunnel  (bilby dials OUT; zero home inbound)
   bilby Caddy :443  ── TLS terminates here (existing LE wildcard) ──▶ MinIO
LAN clients ── split-horizon (unchanged) ──▶ bilby 10.0.0.119 directly
```

- **L4 (raw TCP) passthrough.** rathole forwards bytes; TLS still
  terminates at bilby's Caddy with its existing LE wildcard. The
  droplet only ever sees ciphertext — it cannot MITM, holds no certs
  or creds, and the SigV4-signed request + `Host` are untouched.
  MinIO's per-request SigV4 remains the sole access boundary (honors
  that hard rule).
- **bilby dials out** to the droplet's rathole control port. The home
  network needs *no* inbound: the UDM WAN:443 forward and the
  `cloudflare-ddns` updater for `storage.pod.haus` are **deleted**.
- Fail-closed: if the tunnel is down the droplet's :443 simply refuses
  — no degraded/insecure path.

## Components (config-as-code)

Organised by component, following the existing multi-host service
convention (`backup/`, `autoheal/`, `logging/`).

### 1. `relay/terraform/` — new Terraform root

Mirrors `cloudflare/` / `minio/terraform/`. Honors the from-anywhere
hard rule: `backend.tf` S3 → `https://storage.pod.haus`
(`key = "relay.tfstate"`), no LAN IP / loopback / dockernet anywhere.

- `digitalocean` provider; token = `op://Homelab/<DO item>/token`
  rendered into the chezmoi TF env (`podhaus-tf.fish`) beside
  `CLOUDFLARE_API_TOKEN` (TF runs from a workstation — not komodo-op).
- Resources: `digitalocean_droplet` — **`syd1`** (Sydney; lowest AU
  latency), size **`s-1vcpu-512mb-10gb`** (smallest; ample for a
  single-purpose rathole+Periphery relay — bump only if Docker+
  Periphery memory pressure shows), **Fedora image** (current
  DO-supported slug resolved via a `digitalocean_image` data source
  at plan time, consistent with bilby's Fedora). Plus
  `digitalocean_reserved_ip` + assignment (stable A across rebuilds),
  `digitalocean_ssh_key`, `digitalocean_firewall` — inbound **443/tcp
  from `0.0.0.0/0`** + the **rathole control port from bilby's WAN IP
  only**; SSH 22 restricted (or off, favour Periphery/console).
  Output: reserved IP (feeds the DNS record).
- **Reuse the existing podhaus DO project** (do *not* create one): a
  `data "digitalocean_project" "podhaus"` lookup by name +
  `digitalocean_project_resources` attaches only the new droplet +
  reserved IP — pre-existing project resources are left untouched.
- **SSH: public key only, reuse the existing one** (`ssh-ed25519
  AAAAC3NzaC1lZDI1NTE5AAAAIIZSaoga8/dYnCgeiOSaV+3Xe5Tl6AkBpqO0T863ZajR`
  from bilby `~/.ssh/authorized_keys`). A public key is **not a
  secret** and is consumed by *Terraform* (`digitalocean_ssh_key`),
  not a Komodo stack — so it is committed as a non-secret file/tfvar
  in `relay/terraform/`, **not** a Komodo Variable and **not** a
  1Password item. No new keypair, no new secret to manage (you already
  hold the private key) — net subtractive.
- Bootstrap caveat: this root's state backend *is* `storage.pod.haus`,
  which is only reachable on-LAN until the relay is live → the first
  `apply` runs from bilby/LAN (split-horizon). Once the relay is up,
  every root (incl. this one) works from anywhere again.

### 2. Komodo: the droplet as a third linked-repo host

- `komodo/sync/servers.toml`: add the relay host (off-LAN; reached via
  its public/tunnel address). `komodo/sync/repos.toml`: linked-repo
  clone like kangaroo (off-LAN, no bind-mount).
- Periphery installed on the droplet (one-time bring-up script
  paralleling `kangaroo_bootstrap`).
- **Push-deploy interaction (hard rule):** linked-repo hosts must be
  force-deployed via `podhaus-push-deploy` Stage 2. Name the droplet
  stack with the host prefix and extend Stage 2's pattern in
  `komodo/sync/procedures.toml` (currently `kangaroo-*`) to also match
  the relay host prefix. No `webhook_force_deploy`.
- Host name: **TBD by user** (bilby/kangaroo/pinelake theme). Used as
  the stack-name prefix and the servers.toml entry.

### 3. `relay/` — rathole stacks (shared-service layout)

- `relay/compose.shared.yaml` — common rathole bits + the contract
  (control port, service = tcp/443, token via 1Password).
- `relay/<relay-host>/compose.yaml` (`include` shared) — **rathole
  server**: listens public :443, control port; bind tightly. Komodo
  stack on the droplet host (linked-repo, run_build only if needed).
- `relay/bilby/compose.yaml` (`include` shared) — **rathole client**:
  dials the droplet, forwards the tunneled :443 → `caddy:443` over
  dockernet (Caddy stays as-is; no Caddy change needed). `files_on_host`
  bilby stack.
- Shared secret (rathole control-channel token): 1Password Homelab
  item → komodo-op `OP__KOMODO__*`; the item field layout is the var
  contract (per the komodo-op credential-split convention). Both
  endpoints reference the same token var.
- No single-file bind mounts (directory binds only) per the hard rule.

### 4. DNS cutover (`cloudflare/`)

- `dns_storage.tf`: `storage.pod.haus` grey-cloud A → **droplet
  reserved IP** (was home WAN). `*.storage.pod.haus` CNAME unchanged.
- `dns_unifi_split_horizon.tf`: LAN split-horizon records
  (`storage.pod.haus` + per-site vhosts → 10.0.0.119) **unchanged** —
  LAN keeps hitting Caddy directly, never the relay.
- Read the provider resource docs before editing (hard rule).

### 5. Decommissions

- Delete the UDM `storage.pod.haus` WAN:443 port-forward (via the
  UniFi provider / wherever it's defined — confirm it is TF-managed;
  `minio-public-caddy.md` says `unifi_port_forward`).
- Retire `cloudflare-ddns` for `storage.pod.haus` (it only existed to
  track the home WAN IP for this record; the relay IP is static).
- Update `minio-public-caddy.md` + `AGENTS.md` key-files/architecture
  so the public path is documented as the relay, not the WAN forward
  (docs-as-first-class so the stale "WAN port-forward" model can't
  mislead later).

## Hard-rule compliance checklist

- [ ] `relay/terraform/` backend = `https://storage.pod.haus`; no LAN
      IP / loopback / dockernet in any TF root. From-anywhere holds.
- [ ] No secret in tracked source — only `op://` refs; rathole token
      via 1Password→komodo-op; DO token via chezmoi TF env.
- [ ] Directory bind mounts only.
- [ ] Linked-repo droplet force-deployed via Stage 2 pattern (no
      `webhook_force_deploy`); host-prefixed stack names.
- [ ] Provider resource docs read before writing DO/UniFi/CF HCL.
- [ ] MinIO SigV4 remains the only access boundary; droplet sees only
      ciphertext (no edge auth/admin block — honors that hard rule).
- [ ] No new owned script/CI service (subtractive where possible: this
      *removes* the WAN forward + cloudflare-ddns/storage).

## Gated execution sequence

Each `apply` / DNS change / deploy is individually gated (explicit
go-ahead). `terraform plan` is always fine.

1. Scaffold all config-as-code locally (no apply). Review.
2. Provision: `cd relay/terraform && terraform plan` → review →
   **(gated)** `apply` from bilby/LAN. Capture reserved IP.
3. Bring up Periphery on the droplet; register host (servers/repos);
   `komodo-sync`; deploy the rathole server + bilby client stacks
   **(gated)**. Verify tunnel established (config-level signal, not
   "container healthy").
4. **Verify before cutover** with the `vpn-diagnostics` harness
   (real external/VPN client): direct to the droplet IP, full SigV4
   PUT/GET + a Publii-style flow must succeed end-to-end.
5. **(gated)** DNS cutover: `storage.pod.haus` A → reserved IP.
   Re-verify externally; confirm LAN still uses split-horizon.
6. **(gated)** Decommission: remove UDM WAN:443 forward +
   cloudflare-ddns/storage; update docs (`minio-public-caddy.md`,
   `AGENTS.md`, this doc → DONE).

## Rollback

DNS A back to home WAN reverts to the (broken-external but
LAN-working) prior state instantly; the relay stack can be stopped;
`terraform destroy` on `relay/terraform/` removes the droplet. No
data path through the droplet (ciphertext only) ⇒ nothing to clean.

## Decided

Region `syd1`; size `s-1vcpu-512mb-10gb`; Fedora image; existing
`podhaus` DO project (data-sourced); existing ed25519 public key
(committed non-secret); rathole tunnel; Periphery linked-repo host.

## Open items for the user

- **Relay host name** (servers.toml entry + stack-name prefix; the
  bilby/kangaroo/pinelake theme). The only true blocker.
- ~~Exact 1Password item for the DO token~~ — resolved:
  `op://Homelab/DigitalOcean Personal Access Token/token`.
</body></html>
