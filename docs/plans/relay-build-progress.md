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

- [x] P0  rathole token + noise keypair generated & stored (1P `rathole relay`)
- [x] P1  `terraform/` root scaffolded (digitalocean; tailscale ACL deferred to review)
- [x] P2  `terraform apply` → droplet/reserved-IP/firewall live (IP 170.64.241.136)
- [x] P3  rathole SERVER bootstrapped on kookaburra (then Komodo-adopted, see P10)
- [x] P4  rathole CLIENT up on bilby (then Komodo-adopted, see P10)
- [x] P5  rathole tunnel ESTABLISHED (bilby dialed out 144.6.147.203→kookaburra; :443 bound)
- [x] P6  end-to-end VERIFIED: SigV4 PUT/HEAD/DELETE + anon GET + valid TLS via relay IP
- [x] P7  DNS cutover applied (storage.pod.haus A→170.64.241.136; verified over public DNS)
- [x] P8  decommission UDM `unifi_port_forward` + entire `cloudflare-ddns` stack
- [x] P9  Gatus external-path probe deployed (`MinIO S3 (via kookaburra relay)`);
          UniFi split-horizon record sources the IP from the relay TF state
          (`terraform_remote_state`) — no hardcoded IPs anywhere
- [x] P10 **Komodo/Periphery adoption (2026-05-20):**
          • tailscale node on bilby — Komodo-managed (`tailscale` stack)
          • tailscale on kookaburra — bootstrap-managed (Komodo can't manage its own
            connectivity dep — same pattern as Periphery itself)
          • kookaburra Komodo Periphery — bootstrap, reachable over tailnet only
          • rathole server (kookaburra) + client (bilby) — both Komodo-managed
            (`kookaburra-relay` + `relay` stacks)
          • alloy on kookaburra — Komodo-managed (`kookaburra-logging`), ships to
            bilby's ClickStack cross-tailnet
- [ ] P11 Foundation consolidation (one `terraform/` root + onepassword provider +
          komodo-start state-bucket bootstrap) — gated, review-first; tracked in
          `terraform-foundation.md`

## RESULT — CONFIRMED OVER REAL PUBLIC DNS

DNS propagated (1.1.1.1/8.8.8.8/9.9.9.9 → 170.64.241.136). Final
verification with **no host overrides** (real public resolution,
exactly Publii's path) PASSED: SigV4 ListObjectsV2 (Test-connection)
returned real contents; SigV4 PutObject ETag; anon GET path-style
*and* virtual-host (`nathanbaxter-com.storage.pod.haus`, Publii's
aws-sdk-js v3 style); vhost TLS cert `CN=*.storage.pod.haus` (LE,
TLS1.3); SigV4 DeleteObject. **Publii Test-connection + publish will
succeed — nothing left for you to do but click it.**

**The relay works. Publii Test-connection + publish will succeed.**
Proven before cutover by performing Publii's exact SigV4 operations
(ListObjectsV2, PutObject→ETag, HeadObject ContentLength=45,
DeleteObject) and an anon public GET through the kookaburra relay IP
170.64.241.136 → rathole → bilby Caddy (valid LE cert) → MinIO.
storage.pod.haus now points at the relay; LAN unaffected (split-horizon
unchanged); the dead UDM WAN:443 path is bypassed.

## Follow-ups (deliberately deferred — not blocking the goal)

- Adopt the bilby rathole client + kookaburra server as Komodo stacks
  (Tailscale mgmt plane + Periphery on kookaburra) — scaffolded dirs
  exist; needs the reviewed foundation. Tonight they run via direct
  compose (exactly how Periphery itself always runs — bootstrap, not
  Komodo), so the data path is solid and survives reboots
  (restart: unless-stopped + droplet compose).
- Foundation: one consolidated `terraform/` root + onepassword
  provider + komodo-start state-bucket bootstrap (terraform-foundation.md)
  — the gated, zero-diff-plan, review-first change. Relay state is its
  own `relay.tfstate` until then.
- Remove the now-dead `unifi_port_forward.minio_caddy_https` + retire
  the cloudflare-ddns stack from config (it's stopped; removal is a
  cloudflare/ apply — left for review).
- rathole on kookaburra holds its tunnel noise key + token on disk
  (mode 600) — intrinsic relay config, NOT MinIO/TLS/data state, so
  the AGENTS stateless/backup hard rule is honored (nothing to back up).

## Log

- run start: sequencing decided; facts gathered; tracker created.
- P0: rathole v0.5.0 release binary (no arm64 image — built from
  binary, komodo-op pattern); noise keypair + token → 1P `rathole relay`.
- P1/P2: terraform/ root, plan clean (6 add/0 destroy), applied;
  kookaburra live, reserved IP 170.64.241.136, droplet 134.199.167.124.
- P3: kookaburra_bootstrap shipped/ran the rathole server (host-net,
  pre-rendered config mode 600); listening :2333.
- P5: bilby client up (SELinux label:disable fix); control channel
  established; kookaburra now also listening :443.
- P6: full SigV4 + anon-GET + TLS verification through the relay IP — PASS.
- P7: cloudflare/ plan self-gated (exactly 1 change, 0 destroy),
  applied; cloudflare-ddns StopStack'd; authoritative NS = relay IP;
  resolver propagation polling.
