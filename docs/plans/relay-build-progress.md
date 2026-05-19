# Relay build — overnight autonomous run progress

Live status of the unattended build toward "Publii Test connection works".
Updated as each phase completes. If the run stops, this is the resume point.

## Sequencing decision (autonomous, risk-managed)

The explicit goal is **the relay working / Publii verified**, not the
foundation cleanup. The full `cloudflare/`+`minio/terraform/` → one-root
state migration is the highest-risk unattended op and is **not required**
to reach the goal. So:

- **Relay infra** → NEW `terraform/` root, onepassword provider from day
  one (honors the no-cred-dump principle for all new work).
- **DNS cutover** (the one storage.pod.haus A change + unifi_port_forward
  removal) → done in the **existing `cloudflare/` root** (small, well-
  understood edit in a working root; no blind state surgery).
- **Full root consolidation + komodo-start bootstrap** → scaffolded and
  left **gated for review** (zero-diff plan is the gate; not executed
  unattended). Tracked in `terraform-foundation.md`.
- **rathole** has no arm64 image → built from source via Dockerfile
  (`run_build = true`), same pattern as komodo-op/caddy.

## Resolved facts

- DO Fedora image: `fedora-43-x64`; region `syd1`; size
  `s-1vcpu-512mb-10gb`; DO account active; project `podhaus`
  id `8d248f3c-7adb-4123-b5eb-277d0145ba5f`.
- cloudflare/ + minio/terraform/ state inventories captured (migration
  map for the foundation scaffold).
- All credentials present in 1Password Homelab.

## Phase checklist

- [ ] P0  rathole token + noise keypair generated & stored (1P `rathole relay`)
- [ ] P1  `terraform/` root scaffolded (onepassword + digitalocean + tailscale)
- [ ] P2  `terraform apply` → droplet/reserved-IP/firewall live
- [ ] P3  Periphery bootstrapped on kookaburra (SSH window) + host registered
- [ ] P4  git push → linked-repo + push-deploy; tailscale + relay + logging stacks deployed
- [ ] P5  rathole tunnel established (config-level confirmation)
- [ ] P6  end-to-end verify via vpn-diagnostics (real external SigV4 as Publii)
- [ ] P7  DNS cutover in cloudflare/ root (storage.pod.haus → reserved IP); re-verify
- [ ] P8  decommission UDM forward + cloudflare-ddns; docs updated
- [ ] P9  foundation consolidation scaffolded for review (gated, not applied)

## Log

- (run start) sequencing decided; facts gathered; progress tracker created.
