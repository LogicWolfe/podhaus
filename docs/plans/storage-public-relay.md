# Storage public ingress relay — DigitalOcean + rathole

**Status: PLANNED (detailed/complete, ready for review). Nothing
applied, deployed, or pushed. All `apply` / deploy / DNS steps gated;
`terraform plan` is fine.**

> **DEPENDS ON [`terraform-foundation.md`](plan-viewer.html?file=terraform-foundation.md)
> — do that first.** The relay is **not** a separate Terraform root.
> Its resources (DigitalOcean provider, droplet, reserved IP,
> firewall, project attach) are added to the **single consolidated
> `terraform/` root** the foundation establishes. Provider creds come
> from the **1Password provider** (`data "onepassword_item"`), not a
> chezmoi dump. The reserved-IP → `storage.pod.haus` A record is a
> **direct intra-root reference** (`digitalocean_reserved_ip.x
> .ip_address`) — the old cross-root literal-copy seam is gone.

## Why this exists

`storage.pod.haus` is unreachable for genuine external clients: the
**UDM Pro SE / UniFi OS binds WAN tcp/443 and shadows the
port-forward** — it TCP-accepts the client, swallows the ClientHello,
and never reaches Caddy (no ServerHello, any MTU, any SNI). It only
ever worked via NAT-hairpin from inside the LAN, so every prior
"external works" check (incl. "VPN off") was a false positive. Full
evidence + the dead-ended options 1–3 are in
`nathanbaxter-com-publii.md` → OPEN ISSUE. The **same bug also breaks
remote `terraform` to the `storage.pod.haus` S3 state backend** — the
from-anywhere TF hard rule has been silently violated for every root;
only on-LAN split-horizon ever worked. This relay restores **both**
(Publii publish *and* from-anywhere Terraform), without Cloudflare
(preserves SigV4) and without any home inbound (sidesteps the UDM).

## Architecture

```
            PUBLIC, OUTWARD-DIALED rathole tunnel (no Tailscale)
clients / Sky ─DNS storage.pod.haus─▶ kookaburra :443   (rathole SERVER)
                                       kookaburra :2333  (control)
                                              ▲
                       bilby rathole CLIENT dials OUT ───┘  (noise + token;
                       zero home inbound)                    relayed bytes
                                              │              flow back down
                                              ▼              this conn
                              bilby: rathole client ─▶ caddy:443
                              (TLS terminates at Caddy — existing LE wildcard) ─▶ MinIO

        ┌──── PRIVATE FABRIC (Tailscale) — MANAGEMENT PLANE ONLY ────┐
        │   Komodo Core → Periphery (:8120)   •   log ship-back      │
        └────────────────────────────────────────────────────────────┘

LAN clients ── UniFi split-horizon (unchanged) ──▶ bilby 10.0.0.119 directly
```

Key properties:

- **Pure outward rathole — the model we already use.** The rathole
  *server* runs on kookaburra (public `:443` data + `:2333` control);
  the *client* runs on bilby and **dials outbound** to the control
  port, and the relayed traffic flows back down that one connection.
  Home network: **zero inbound**. The control port is public *by
  design* — its boundary is rathole's mandatory per-service **token +
  `noise` transport** (encrypted, authenticated), **not** an IP-pinned
  firewall and **not** Tailscale. This is the same principle as the
  "MinIO SigV4 is the boundary, not an edge block" hard rule — the
  credential/transport is the boundary; wrapping rathole in Tailscale
  would be that exact rejected anti-pattern (an earlier draft did
  this; reverted — see *Rejected alternatives*).
- **L4 (raw TCP) passthrough.** rathole forwards bytes untouched; TLS
  still terminates at bilby's Caddy with its existing LE wildcard. The
  droplet only ever sees **ciphertext** — it cannot MITM, holds no
  certs/creds, and the SigV4-signed request + `Host` are intact. MinIO
  per-request SigV4 stays the sole access boundary.
- **bilby dials out.** UDM `storage.pod.haus` WAN:443 forward and the
  `cloudflare-ddns` updater for that name are **deleted** (no home
  inbound, static reserved IP).
- **Fail-closed:** tunnel down ⇒ kookaburra `:443` simply refuses.
- **Tailscale is scoped to the management plane ONLY** — Komodo
  Core→Periphery and log ship-back. Those are bilby→kookaburra (rathole
  is the other direction) and are sensitive (Periphery is an RCE
  control surface), so they must not face the internet. The rathole
  data tunnel does **not** use Tailscale.
- **Sky/clients never touch Tailscale** — they hit the public `:443`
  like any S3 endpoint. `[[project_sky_publii_zero_client]]` holds.
  The earlier "no Tailscale" decision was scoped to *end clients*; the
  mgmt-plane tailnet is the inter-host fabric you pre-flagged for
  off-LAN hosts (and reused later for pinelake).

## Components (config-as-code)

Conventions verified against the live repo. linked-repo host stacks
use `linked_repo = "podhaus"`, **repo-relative** `run_directory`,
`file_paths = ["compose.yaml","../compose.shared.yaml"]`, and a
host-prefixed name; secrets are `[[OP__KOMODO__ITEM__FIELD]]` (item
title + field label → UPPER, spaces/hyphens→`_`).

### 1. Relay resources in the consolidated `terraform/` root

**Not a new root.** Per `terraform-foundation.md`, there is one
`terraform/` root with one state (`podhaus.tfstate`) and the
`onepassword` provider as the sole credential mechanism. The relay
adds the DigitalOcean provider + resources to it:

- `providers.tf` (foundation root): add
  `digitalocean = { source = "digitalocean/digitalocean", version =
  "~> 2.0" }` to `required_providers`, and:

  ```hcl
  data "onepassword_item" "do" {
    vault = local.homelab_vault_uuid
    title = "DigitalOcean Personal Access Token"
  }
  provider "digitalocean" {
    token = data.onepassword_item.do.credential   # field "token"
  }
  ```
  No `TF_VAR_do_token`, no chezmoi, no tfvars — the only secret at
  rest is the 1P service-account token (foundation §2). Backend,
  `.gitignore`, lockfile policy are all inherited from the root.

A relay `.tf` file (e.g. `terraform/relay.tf`) holds the resources
(schemas verified against the DO v2 provider):

- `data "digitalocean_project" "podhaus" { name = "podhaus" }` —
  reuse the **existing** project; never create one.
- `digitalocean_ssh_key "kookaburra"` — `public_key` = the existing
  ed25519 key from bilby `~/.ssh/authorized_keys`, committed as a
  non-secret file (`ssh_authorized_key.pub`, read via `file()`). A
  public key is not a secret and is consumed by Terraform — **not** a
  Komodo Variable, **not** 1Password. No new keypair (you hold the
  private key) — net subtractive.
- `digitalocean_droplet "kookaburra"` — `image` = current Fedora slug
  (resolve the exact slug at plan time via the DO images API / a
  `data` lookup; consistent with bilby's Fedora), `region = "syd1"`,
  `size = "s-1vcpu-512mb-10gb"`, `ssh_keys = [digitalocean_ssh_key
  .kookaburra.fingerprint]`, `monitoring = true`, `ipv6 = false`,
  `tags = ["podhaus","relay"]`, `user_data` = a minimal cloud-init
  that installs Docker + the Tailscale prerequisites and the
  one-shot Periphery bring-up (see §6/§7). `ipv4_address` is the
  attribute for the public IP (used only for sanity; DNS uses the
  reserved IP).
- `digitalocean_reserved_ip "kookaburra" { region = "syd1" }` +
  `digitalocean_reserved_ip_assignment` (`ip_address =
  digitalocean_reserved_ip.kookaburra.ip_address`, `droplet_id =
  digitalocean_droplet.kookaburra.id`) — stable public IP across
  droplet rebuilds.
- `digitalocean_firewall "kookaburra"` — `droplet_ids =
  [digitalocean_droplet.kookaburra.id]`:
  - `inbound_rule { protocol="tcp" port_range="443"
    source_addresses=["0.0.0.0/0","::/0"] }` — public data.
  - `inbound_rule { protocol="tcp" port_range="2333"
    source_addresses=["0.0.0.0/0","::/0"] }` — rathole control;
    public **by design**, secured by noise+token, **not** pinned to
    bilby's (dynamic) home IP.
  - **`outbound_rule`s are mandatory** — a DO firewall with no
    outbound block blocks *all* egress (breaks Tailscale + dnf
    updates). Allow outbound `tcp`/`udp`/`icmp` to `0.0.0.0/0,::/0`
    (single-purpose box; the control objective is inbound). This DO
    firewall footgun is called out so it isn't missed.
  - **No inbound 8120 (Periphery)** — Periphery rides Tailscale only,
    never the public internet.
- `digitalocean_reserved_ip.kookaburra.ip_address` is referenced
  **directly** by the `storage.pod.haus` A record in the same root
  (§4) — no output-and-copy, no `terraform_remote_state`. An
  `output` is optional (visibility only).
- `digitalocean_project_resources` — attach the droplet + reserved IP
  URNs to `data.digitalocean_project.podhaus.id` (pre-existing
  project resources untouched).
- Bootstrap caveat: this root's state backend *is*
  `storage.pod.haus`, only reachable on-LAN until the relay is live →
  the first `apply` runs from bilby/LAN (split-horizon). Once the
  relay is up, every root (incl. this one) works from anywhere again.

### 2. `tailscale/` — private fabric (Komodo-managed stack)

Shared-service layout: `tailscale/compose.shared.yaml` +
`tailscale/{bilby,kookaburra}/`. One `tailscale/tailscale` container
per host as its own Komodo stack (config-as-code; **not** host-level
`tailscaled`). **Tailscale SaaS free tier** as the control plane.

- Auth: a Tailscale **auth key** — pre-authorized + **tagged
  `tag:podnet`** — in 1Password Homelab → komodo-op
  `OP__KOMODO__TAILSCALE_AUTHKEY__*`. Tagged nodes are tailnet-owned
  (non-expiring, no user identity bound — correct for headless
  servers). The rathole data tunnel is **not** on the tailnet.
- **ACL (asymmetric blast-radius model, managed as code):** your own
  devices may initiate into podnet (full admin reach); podnet nodes
  flow freely among themselves; podnet nodes **cannot initiate** to
  your personal/untagged devices (a compromised droplet can't pivot
  into your laptop — it can only answer connections you start, via
  Tailscale's stateful replies). This is a *replace-the-default* ACL:

  ```jsonc
  {
    "tagOwners": { "tag:podnet": ["autogroup:admin"] },
    "acls": [
      { "action": "accept", "src": ["autogroup:member"], "dst": ["tag:podnet:*"] },
      { "action": "accept", "src": ["tag:podnet"],        "dst": ["tag:podnet:*"] }
      // intentionally NO  src tag:podnet -> dst autogroup:member
    ]
  }
  ```

  Managed via the Tailscale Terraform provider / an ACL file in the
  repo (config-as-code), not hand-edited in the Tailscale console.
  "Untagged devices" = *your own* user-owned devices only (single
  tailnet); strangers are never in scope (public surface is solely
  kookaburra `:443`/`:2333`, off-tailnet).
- Container shape (env/volume schema **to be confirmed against
  `tailscale.com/kb/1282/docker` + the docker-params KB at scaffold
  time** — that page is JS-gated to WebFetch and I will not write it
  from memory): persistent state volume (`/var/lib/tailscale`),
  userspace mode to avoid `NET_ADMIN`/`/dev/net/tun` where possible,
  `TS_HOSTNAME` per host (`bilby` / `kookaburra`), `TS_AUTHKEY` from
  the env var above. Other containers reach the tailnet via the
  documented sidecar pattern (`network_mode: service:tailscale`) or
  the node address — exact choice finalized with that doc.
- Scope: **only** Komodo Core→Periphery and log ship-back. rathole
  (control + data) is independent and public-outward — never on the
  tailnet.
- bilby + kookaburra now; pinelake later joins the same fabric (this
  is the reusable inter-host fabric, not a per-target hack).

### 3. `relay/` — rathole stacks (shared-service layout)

`relay/compose.shared.yaml` + `relay/{kookaburra,bilby}/`. Official
image `rapiz1/rathole`, config passed as the container arg
(`rathole /etc/rathole/<file>.toml`). Transport `noise` (rathole has
no TLS-less token confidentiality otherwise; defence-in-depth even
though the channel is already inside Tailscale WG).

- **kookaburra = rathole server** (`relay/kookaburra/`, linked-repo
  stack `kookaburra-relay`):

  ```toml
  [server]
  bind_addr = "0.0.0.0:2333"                      # control: public, noise+token
  [server.transport]
  type = "noise"
  [server.services.storage]
  type = "tcp"
  bind_addr = "0.0.0.0:443"                       # public data
  ```

- **bilby = rathole client** (`relay/bilby/`, `files_on_host` stack
  `relay` — Stage 1 `*` covers it):

  ```toml
  [client]
  remote_addr = "storage.pod.haus:2333"          # kookaburra reserved IP,
  [client.transport]                              # public; dials OUTBOUND
  type = "noise"
  [client.services.storage]
  type = "tcp"
  local_addr = "caddy:443"                        # dockernet → Caddy
  ```
  (`remote_addr` resolves to the kookaburra reserved IP — bilby's
  split-horizon will point `storage.pod.haus` at bilby, so the client
  uses the reserved IP literal or a dedicated name to avoid the
  hairpin; finalized at scaffold once the reserved IP exists.)

- **Secret/token handling (rathole has NO env interpolation —
  confirmed):** the token must not be a literal in committed source.
  Pattern: commit a `rathole.toml.template` (token as
  `${RATHOLE_TOKEN}`), bind its **directory** read-only (never a
  single-file bind — hard rule), and an `entrypoint` wrapper does
  `envsubst < /etc/rathole/rathole.toml.template > /run/rathole.toml
  && exec rathole /run/rathole.toml`. The rendered file lives only
  inside the container (tmpfs/`/run`). No separate init service ⇒ no
  `ignore_services` needed. `RATHOLE_TOKEN` (+ the noise keypair)
  come from 1Password→komodo-op (`OP__KOMODO__RATHOLE_*`); the
  1Password item field layout is the variable contract; both
  endpoints reference the same token/keys.
- Healthcheck: rathole has an application-layer heartbeat
  (`heartbeat_timeout` client default 40s / `heartbeat_interval`
  server 30s). The container healthcheck must prove the *tunnel*
  (e.g. the client healthcheck = a TCP probe through
  `local_addr`→Caddy, or the rathole process + an established control
  conn), not merely "process up" — so Komodo health reflects reality.

### 4. DNS cutover (`cloudflare/`)

- The `storage.pod.haus` A record (now in the consolidated
  `terraform/` root): set `content =
  digitalocean_reserved_ip.kookaburra.ip_address` — a **direct
  same-root reference**, not a literal or remote-state. Atomic: the
  droplet, its reserved IP, and the DNS record converge in one plan.
  **Remove `lifecycle.ignore_changes = [content]`** — that ignore
  only existed because `cloudflare-ddns` mutated `content`; with DDNS
  retired (§5) Terraform owns it. `*.storage.pod.haus` CNAME
  unchanged.
- `cloudflare/dns_unifi_split_horizon.tf`: **unchanged**. LAN keeps
  resolving `storage.pod.haus` (+ per-site vhosts) → `10.0.0.119` and
  hitting Caddy directly; the relay is the off-LAN path only.
- Read the Cloudflare/UniFi provider resource docs before editing
  (hard rule).

### 5. Decommissions (net subtractive)

- Delete the `unifi_port_forward "minio_caddy_https"` resource
  (WAN:443→10.0.0.119:443; lives in the consolidated `terraform/`
  root post-foundation) — no home inbound needed any more.
- Retire `cloudflare-ddns` for `storage.pod.haus`: it existed only to
  track the dynamic home WAN IP for this record; the relay IP is a
  static reserved IP. (`cloudflare-ddns`'s `DOMAINS` is *only*
  `storage.pod.haus` → the whole stack is removed, not just an entry.)
- Update `minio-public-caddy.md`, `AGENTS.md` (key-files +
  architecture + the relevant hard rules), and the docs architecture
  page so the public path is documented as the relay, not the WAN
  port-forward (docs-as-first-class so the stale model can't mislead).

### 6. Komodo: kookaburra as a third linked-repo host

- `komodo/sync/servers.toml`: append a `[[server]]` `kookaburra`,
  `[server.config] address = "https://<kookaburra-tailnet-addr>:8120"`
  (Periphery reachable **only over Tailscale**, never the public IP;
  the firewall has no inbound 8120), `enabled = true`, same
  disk thresholds.
- `komodo/sync/repos.toml`: extend the existing linked-repo `podhaus`
  (it already names "future pinelake"); add a `server = "kookaburra"`
  clone analogous to kangaroo's (`git_account = "LogicWolfe"`, repo
  `LogicWolfe/podhaus`, branch `main`).
- `komodo/sync/procedures.toml`: **extend `podhaus-push-deploy`
  Stage 2** so its `BatchDeployStack` pattern also matches the
  kookaburra prefix — either add a second execution
  `{ pattern = "kookaburra-*" }` or broaden the pattern. Stage 1
  (`BatchDeployStackIfChanged "*"`) already no-ops kookaburra (linked
  repo) harmlessly; Stage 2 force-deploys it (the linked-repo
  stale-clone rule). **No `webhook_force_deploy`.** Name kookaburra
  stacks `kookaburra-*` (e.g. `kookaburra-relay`, `kookaburra-logging`,
  the tailscale/periphery stacks).
- Periphery on Fedora: a `kookaburra_bootstrap` script paralleling
  `kangaroo_bootstrap` (idempotent, run from bilby), with the
  Fedora/cloud deltas: normal install dir (e.g.
  `/opt/komodo-periphery`), plain `docker`, **systemd unit** for
  reboot survival (not the QNAP `/etc/config/crontab` mechanism),
  Periphery `.env` (`KOMODO_PASSKEYS` from
  `op://Homelab/Komodo Passkey/password`, `TZ`), and
  `periphery.config.toml` `[[git_provider]]` (GitHub PAT from
  `op://Homelab/Homelab GitHub Personal Access Token/token`) for the
  Linked-Repo private clone. SSH/scp over the **tailnet** address
  (bilby reaches kookaburra via Tailscale; no public SSH needed —
  firewall has no inbound 22). Idempotently appends the
  `[[server]]` block to `servers.toml`.

### 7. `logging/kookaburra/` — log ship-back

Add a per-host overlay to the existing `logging/` shared service
(same mechanism as `logging/kangaroo/`): `logging/kookaburra/
stack.toml` with `linked_repo = "podhaus"`, `run_directory =
"logging/kookaburra"`, `file_paths = ["compose.yaml",
"../compose.shared.yaml"]`, name `kookaburra-logging`, and a
`logging/kookaburra/compose.yaml` overlay redefining only the alloy
config bind (absolute linked-repo path, as kangaroo does). The Alloy
collector ships kookaburra container/system logs to the central
ClickStack/HyperDX **over the tailnet** (bilby's tailnet address as
the ingest endpoint — never internet-exposed). Variable *names* match
the shared contract; *values* are kookaburra-specific
(`OP__KOMODO__CLICKSTACK_INGESTION_KEY__CREDENTIAL`, or a
kookaburra-scoped key item if we want per-host revocability).

### 8. Monitoring / health

- **Container healthchecks** on the rathole client/server (prove the
  tunnel, per §3) and the tailscale + periphery containers, so Komodo
  health is truthful. rathole has no one-shot service ⇒ no
  `ignore_services`.
- **Gatus external probe — the gap-closer.** Add to
  `gatus/conf/config.yaml` an endpoint that hits `storage.pod.haus`
  **forced to the reserved IP** so it exercises the real
  internet→relay→tunnel→Caddy path, not the LAN split-horizon
  (Gatus runs on bilby; a plain `https://storage.pod.haus` check
  would resolve via split-horizon and *still* miss external
  breakage — exactly how the UDM incident hid). Use the liveness path
  (no SigV4): a `<<: *defaults` endpoint with
  `url: https://storage.pod.haus/minio/health/live` plus a
  `client.dns`/host-pin or a dedicated check name making the resolved
  IP the reserved IP (final form set with the Gatus client options at
  scaffold time). Keep the existing direct
  `MinIO S3 (storage.pod.haus)` check too (covers the LAN/Caddy
  layer) — together they distinguish "Caddy down" from "external path
  down."
- Optional: a Gatus heartbeat/`external-endpoints` entry for tunnel
  liveness, and a Periphery `GetServerState` POST check for
  kookaburra (mirrors the existing bilby Periphery check) over the
  tailnet.

### Out of scope (deliberate, not an oversight)

- **Backups: none — *contingent on statelessness*.** kookaburra is
  stateless today (ciphertext-only relay; no MinIO data/certs/creds;
  all state on bilby). Adding it to `backup/` now is additive
  complexity for zero recoverable state. DR = `terraform apply`
  rebuilds it; the reserved IP keeps DNS stable across a rebuild.
  **Revisit trigger (hard, also in `AGENTS.md` +
  `backup-and-recovery.html`):** if *any* meaningful state ever lands
  on kookaburra (a persistent volume, a local key/cert, app data —
  anything not reconstructible from `terraform apply`), the backup
  decision MUST be reopened and kookaburra added to `backup/`. A
  future reader finding state with no backup should treat it as a
  bug, not a deliberate choice.

## Hard-rule compliance checklist

- [ ] Foundation (`terraform-foundation.md`) landed first: single
      `terraform/` root, backend `https://storage.pod.haus`,
      onepassword provider. From-anywhere holds (and is *restored*).
- [ ] No secret in tracked source — only `op://`/env refs; rathole
      token+noise keys & Tailscale authkey via 1Password→komodo-op;
      **DO token via the onepassword provider** (`data
      "onepassword_item"`), no chezmoi/`TF_VAR`. SSH **public** key is
      non-secret and committed (correct).
- [ ] Directory bind mounts only (rathole template dir; alloy conf
      dir) — never single-file binds.
- [ ] linked-repo kookaburra force-deployed via Stage 2 pattern
      extension; `kookaburra-*` stack names; no `webhook_force_deploy`.
- [ ] DO / Cloudflare / UniFi provider resource docs read before
      writing HCL (DO v2 schemas captured here; CF/UniFi per their
      docs at edit time).
- [ ] MinIO SigV4 stays the only access boundary; droplet sees only
      ciphertext; no edge auth/admin block.
- [ ] Net subtractive: removes the UDM port-forward + the entire
      cloudflare-ddns stack; adds only the minimum (relay, fabric).
- [ ] DO firewall has explicit **outbound** rules (egress-all) — the
      no-outbound-blocks-everything footgun.

## Gated execution sequence

Each `apply` / DNS change / deploy individually gated. `plan` is fine.

0. **`terraform-foundation.md` complete first** (single root,
   onepassword provider, komodo-start state-bucket bootstrap, zero-diff
   migration proven). The relay does not start until this is done.
1. Scaffold the relay `.tf` + stacks locally (after confirming the
   one open Tailscale container-schema item). No apply. Review.
2. `cd terraform && terraform plan` → review → **(gated)** `apply`
   from bilby/LAN. The droplet+reserved IP+DNS A converge atomically.
3. `kookaburra_bootstrap` (Periphery on the droplet over Tailscale);
   register host (servers/repos/procedures); `komodo-sync`;
   **(gated)** deploy `tailscale` (both hosts), then `kookaburra-relay`
   + `relay` (bilby), `kookaburra-logging`. Confirm via a config-level
   signal (rathole control established / pulled hash), not "container
   healthy".
4. **Verify before cutover** with the `vpn-diagnostics` harness (real
   external/VPN client) **forced to the reserved IP**: full SigV4
   PUT/GET + a Publii-style flow must succeed end-to-end; Periphery +
   logs visible over the tailnet.
5. **(gated)** DNS cutover: the `storage.pod.haus` A record →
   `digitalocean_reserved_ip.kookaburra.ip_address`, drop
   `ignore_changes[content]`; `terraform apply` (single root —
   atomic with the relay). Re-verify externally; confirm LAN still
   uses split-horizon.
6. **(gated)** Decommission: remove the `unifi_port_forward`
   resource + the `cloudflare-ddns` stack; `terraform apply`. Update
   `minio-public-caddy.md`, `AGENTS.md`, architecture docs; flip this
   doc + the OPEN ISSUE in `nathanbaxter-com-publii.md` to DONE.

## Rejected alternatives

- **rathole control/transport over Tailscale** (briefly drafted,
  reverted). Rationale for rejecting: it is the *credential-boundary-
  vs-network-boundary* anti-pattern — the same mistake the "MinIO
  SigV4 is the boundary, not an edge block" hard rule exists to
  prevent. rathole's control port is public *by design*, secured by
  its mandatory token + `noise` transport; wrapping it in Tailscale
  added a moving part and a dependency for no security gain, and the
  worry that motivated it (firewall-pinning to bilby's dynamic home
  IP) was unfounded — token+noise is the boundary, not IP filtering.
  bilby still dials out either way, so the outward model (zero home
  inbound) was never actually at stake. Tailscale is kept **only**
  for the genuinely-private mgmt plane (Periphery is RCE; logs).
- **UDM WAN:443 relocation / alternate public port / Cloudflare
  Tunnel** — the diagnosis-stage options 1–3; all dead-ended (UDM has
  no console-port knob; non-standard port everywhere; Cloudflare
  re-opens the documented SigV4 rewrite). Full reasoning in
  `nathanbaxter-com-publii.md` → OPEN ISSUE.
- **Scoped per-port tailnet ACL** vs the chosen `podnet` asymmetric
  model — rejected in favour of "your devices → podnet freely; podnet
  ↮ your devices" (blast-radius containment; a popped droplet can't
  pivot into personal devices) rather than enumerating mgmt ports.
- **Host-level `tailscaled`** vs a Komodo-managed Tailscale stack —
  rejected; containerized keeps the fabric config-as-code.

## Rollback

DNS A back to the home WAN IP instantly reverts to the prior
(broken-external but LAN-working) state; stop the relay stacks; a
**targeted** `terraform destroy -target` of the DigitalOcean relay
resources (single root — scope the destroy, don't nuke the root)
removes the droplet. No data path through the droplet (ciphertext
only) ⇒ nothing to clean.

## Credential ledger (pre-"go")

**You acquire (only Tailscale; order matters — tag owned before key):**
1. Tailscale account/tailnet (free tier).
2. Seed the ACL by hand once: `"tagOwners": {"tag:podnet":
   ["autogroup:admin"]}` + the two `podnet` ACL rules (breaks the
   ACL-as-code chicken-and-egg; TF owns it after).
3. Auth key — **reusable, pre-approved, non-ephemeral, tag
   `tag:podnet`** → 1P Homelab item `Tailscale Auth Key` field
   `credential` → komodo-op `OP__KOMODO__TAILSCALE_AUTH_KEY__
   CREDENTIAL` (consumed by the Tailscale Komodo stacks).
4. OAuth client (scopes `acl`, `auth_keys`/`devices`) → 1P Homelab
   item `Tailscale OAuth Client` (`client_id`, `client_secret`) →
   consumed by the **onepassword TF provider** for the Tailscale TF
   provider (ACL-as-code).

**Generated & stored at build time (no user action):** rathole
control token (`openssl rand`) + `noise` keypair (`rathole
--genkey`) → 1P Homelab item `rathole relay`
(`token`/`noise_private_key`/`noise_public_key`), written via the
service-account token.

**Already exist, verify only:** 1P service-account token (the sole
at-rest secret); Cloudflare/UniFi/GitHub/MinIO-root/DigitalOcean
items; Komodo Passkey + GitHub PAT (Periphery linked-repo); `NordVPN`
(verification harness); the committed ed25519 public key.
Non-credential precondition: DO account active/billable + the
existing `podhaus` DO project.

## Open items (must close before scaffolding)

- **One verification:** exact `tailscale/tailscale` container env/
  volume/networking schema — confirm against
  `tailscale.com/kb/1282/docker` + the Docker-params KB (JS-gated to
  WebFetch; do **not** write from memory — get it via the rendered
  page or `gh`/an authenticated fetch at scaffold time).
- Tailnet addressing form for kookaburra (MagicDNS name vs `100.x`)
  to use in `servers.toml` (Periphery) and the log ingest endpoint —
  pick once the tailnet exists. (rathole uses the *public* reserved
  IP, not the tailnet — settled.)
- Current DO **Fedora image slug** — resolve via the DO images API /
  a `data` source at plan time (don't hardcode a stale slug).

## Decided

Host `kookaburra`; region `syd1`; size `s-1vcpu-512mb-10gb`; Fedora
image; existing `podhaus` DO project (data-sourced); reused ed25519
public key (committed non-secret); DO token
`op://Homelab/DigitalOcean Personal Access Token/token`; **rathole
pure public-outward** (kookaburra exposes `:443` + `:2333`, bilby
dials out, noise transport + token via komodo-op — **not** on
Tailscale); Tailscale Komodo-managed stack (SaaS free tier) scoped to
the **management plane only** with `tag:podnet` + the asymmetric
ACL-as-code (your devices → podnet; podnet ↮ your devices); Periphery
linked-repo host; logging overlay; external Gatus probe; backups out
(conditional, enshrined in long-term docs).
