# Voltaire SSH tunnel — regularize or tear down

**TODO for the home agent.** On 2026-07-27 a Cloudflare tunnel for SSH
access to voltaire (Nathan's office workstation) was stood up *by hand,
outside Terraform*, to meet a same-day deadline: Nathan needed SSH into
the machine from home for roughly one week (until ~2026-08-03). This
plan records exactly what was created and what remains to bring it in
line with fleet convention — or remove it cleanly when the week is up.

## What voltaire is

- Office workstation, Fedora (kernel fc44), x86_64, hostname `voltaire`.
- **Off-LAN**: `192.168.0.113/24` at the office — NOT on the home
  `10.0.0.0/24` LAN, so bilby's cloudflared container can't reach it.
  That's why it got its own tunnel instead of an ingress rule on the
  `pod_haus` tunnel.
- Non-homelab chezmoi profile (`homelab = false` in
  `~/.config/chezmoi/chezmoi.toml`), so `podhaus-tf.fish` is
  .chezmoiignore'd → **no Terraform credentials on the machine**, and
  `~/repos/podhaus/OP_SERVICE_ACCOUNT_TOKEN` doesn't exist there.
  `op` is not signed in. This is why the change couldn't be applied
  through `terraform/` from voltaire.
- No docker (podman only), not a Komodo host, no stacks.
- sshd: `PasswordAuthentication yes`, `PubkeyAuthentication yes`, one
  key in `~nathan/.ssh/authorized_keys` (the chezmoi machine key).

## What was created by hand (2026-07-27)

All via `cloudflared tunnel login` (cert scoped to the pod.haus zone,
saved at `~nathan/.cloudflared/cert.pem` on voltaire) — none of it in
TF state:

Tunnel UUID: `ee341c8d-8eb2-4c9c-9fcb-f10d524fed90`.

| Thing | Where | Note |
|---|---|---|
| Named tunnel `voltaire` | Cloudflare account | credentials JSON in `~nathan/.cloudflared/ee341c8d-….json`, copied to `/etc/cloudflared/` |
| DNS CNAME `voltaire.pod.haus` → `ee341c8d-8eb2-4c9c-9fcb-f10d524fed90.cfargotunnel.com` | pod.haus zone | created by `cloudflared tunnel route dns`, proxied |
| `/etc/cloudflared/config.yml` | voltaire | locally-managed ingress: `ssh://localhost:22` + `http_status:404` catch-all |
| `cloudflared.service` | voltaire systemd | installed via `cloudflared service install`, enabled |

Edge auth: no dedicated Access app — the hostname is gated by the
existing `*.pod.haus` wildcard app (`pod_haus_wildcard` in
`terraform/access.tf`): Homelab service-token bypass + **Family**
allow. Client side uses `ProxyCommand cloudflared access ssh
--hostname %h`; sshd auth is machine key or password.

## Corners cut, in security order

1. **Family-wide edge policy.** The wildcard gates it to the whole
   Family group; the fleet precedent for SSH (`ssh.pod.haus`,
   `home.pinelake.haus`) is Nathan-only. sshd auth still applies, but
   the edge gate is broader than it should be.
2. **Nothing is in Terraform** — tunnel, DNS record, and (absent)
   Access app all drift from the "TF is the source of truth" rule.
3. **Locally-managed tunnel config** (`config.yml` on the host) rather
   than `source = "cloudflare"` — same drift the pinelake migration
   plan exists to close.
4. **Password auth enabled** on sshd (Fedora default, kept as
   fallback; matches bilby's stance so arguably not a corner).

## Follow-up — pick ONE of these

### Option A: tear down (if the access is no longer needed)

On voltaire:

```sh
sudo systemctl disable --now cloudflared
sudo cloudflared service uninstall
sudo rm -rf /etc/cloudflared
cloudflared tunnel delete voltaire        # needs ~/.cloudflared/cert.pem, still present
rm -f ~/.cloudflared/cert.pem
```

Then delete the `voltaire.pod.haus` CNAME (dashboard or API — it is
not in TF state, so TF won't touch it). Verify `terraform plan` in
podhaus is still clean (it should be — nothing TF-managed was changed).

### Option B: regularize into Terraform (if keeping)

Design was already scoped against the repo on 2026-07-27; the pieces:

1. **TF-managed tunnel** — first use of these resource types in the
   repo (per the hard rule, re-read the provider docs; repo pins
   cloudflare provider `~> 5.0`):
   - `cloudflare_zero_trust_tunnel_cloudflared.voltaire` with
     `config_src = "cloudflare"`. Either **import** the hand-made
     tunnel (`terraform import ...
     7e660ed6610dce078359713b3cacdea0/ee341c8d-8eb2-4c9c-9fcb-f10d524fed90`)
     or create fresh and re-enroll voltaire — fresh is cleaner, brief
     cutover acceptable.
   - `data cloudflare_zero_trust_tunnel_cloudflared_token` → output
     for the connector token (replaces the credentials-file flow).
2. **Tunnel config in CF, not on host** — a second
   `cloudflare_zero_trust_tunnel_cloudflared_config` resource in
   `terraform/tunnel.tf` (mirroring `.pod_haus`): ingress
   `{ hostname = "voltaire.pod.haus", service = "ssh://localhost:22" }`
   + `http_status:404` catch-all. Then remove `--config`/config.yml
   from the voltaire service so it pulls from the API (same flip the
   pinelake plan describes: `docs/plans/pinelake-migration/cloudflare-tunnel.md`).
3. **DNS** — `cloudflare_dns_record` in a new
   `terraform/ssh_voltaire_pod_haus.tf`, shaped exactly like
   `ssh_pod_haus.tf` (explicit `settings` block, `proxied = true`,
   `ttl = 1`). Import the hand-created record or delete + recreate.
4. **Nathan-only Access app** — copy the `bilby_ssh` shape from
   `terraform/ssh_pod_haus.tf`: `type = "ssh"`,
   `domain`/`self_hosted_domains = ["voltaire.pod.haus"]`, policy
   `cloudflare_zero_trust_access_policy.nathan` (browser-rendered apps
   are Allow/Block only — do NOT use the `pod_haus_service` module).
   More-specific app overrides the wildcard → replaces the Family
   gate. Optionally add the
   `cloudflare_zero_trust_access_short_lived_certificate` + a
   `voltaire/host-sshd/install.sh` (copy `bilby/host-sshd/`) for
   passwordless browser SSH.
5. **Where to apply from** — voltaire can't run TF today. Either run
   the apply from a homelab machine, or flip voltaire's chezmoi
   `homelab` flag to true + provision
   `~/repos/podhaus/OP_SERVICE_ACCOUNT_TOKEN` + `op` signin, per the
   "TF runs from any machine" contract. Flipping the flag also pulls
   homelab `.claude.json` telemetry onto voltaire — decide
   deliberately (the flag was false on purpose: "general-purpose
   agent host").
6. **Docs** — add voltaire to `docs/hosts.html` if it's now a
   fleet-adjacent host; per docs contract, fold the end state into
   `docs/networking.html` and delete this plan.

Open questions for Nathan: keep access past the week at all? If
keeping, is voltaire becoming a homelab machine (chezmoi flag) or
staying arms-length? Browser-rendered SSH wanted, or is ProxyCommand
enough?
