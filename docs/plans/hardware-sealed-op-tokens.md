# Hardware-sealed per-machine 1Password service tokens

First iteration landed on voltaire 2026-08-11 (see "Built" below).
The remaining work is consumer rewiring and the other hosts.

## Problem

Today one podhaus 1Password **service-account token** serves every
machine-key host, stored as a plaintext file
(`~/repos/podhaus/OP_SERVICE_ACCOUNT_TOKEN`, gitignored; on fractal it
sits on the LUKS-encrypted `/home` as a stopgap). Two things are wrong
with that end state:

- **The token is on disk in plaintext.** The machine *SSH* keys already
  live in hardware (TPM via tpm2-pkcs11, YubiKey PIV on bilby); the op
  token is the straggler.
- **One token = one blast radius and one trust level.** Every holder
  gets the same vault access; there is no per-machine grant or
  per-machine revocation.

Threat-model framing (what hardware residency buys and what it does
not) lives in [secret-architecture](secret-architecture.md): FDE is the
load-bearing control; this is defense in depth for the stolen
disk/backup case plus the per-machine grant/revocation structure.

## Shape of the fix

- **Per-machine service accounts, vault-scoped at creation.** Each
  machine gets its own account granted exactly the vault(s) it
  deserves; revoking a machine = deleting its service accounts.
  Because a service account is scoped to ONE 1Password account and can
  only be granted shared vaults, a machine needing vaults from both
  the personal (`my`) and work (`switchtechnologies`) accounts holds
  one token per account — chosen deliberately over consolidating the
  vaults into a single 1P account, preserving the work/personal
  boundary.
- **Curated vaults as the grant currency.** The per-machine judgement
  is *which vault*: full **Homelab**, or the lesser shared dev vault.
- **Raw token in TPM NV storage — nothing on disk.** Not a sealed
  blob (that leaves `.pub`/`.priv` artifacts to manage): the token is
  written once into a TPM NV index and read back at use time. Data
  lives in 1Password, the token lives in the TPM, no file in between.
  Honest scope: with an empty auth value, any local `tss`-group
  process that knows the index can read it — comparable local exposure
  to a 0600 file; the wins are machine-boundness and zero disk
  artifacts. An NV auth value would need its own storage, recreating
  the file problem — deliberately omitted. Where no TPM exists,
  fall back per the machine-key `hardware > soft > none` rank:
  fractal (WSL, no TPM) keeps the encrypted-disk file tier; bilby has
  no TPM (Apple Silicon) — a YubiKey PIV data object is feasible
  (853-byte token fits; retired slots free; PIN-gating needs empirical
  verification) but per secret-architecture, reassess after FDE.

## Built (voltaire, 2026-08-11)

- **Vaults/accounts**: shared **Dev** vault created in `my`; the
  switch-side grant is the vault named "Dev" in `switchtechnologies`
  (different vault ID; rename there is cosmetic and optional).
- **Tokens minted**: two per-machine service accounts
  (`voltaire-dev` → my/Dev read+write; `voltaire-switch` →
  switchtechnologies read), written into NV indices — `switch` at
  `0x01800051`, `dev` at `0x01800052`. Verified: `op-vault dev --
  whoami` / `vault list` see exactly the granted vault; same for
  switch.
- **Tooling** (chezmoi `dot_local/bin/`, uncommitted):
  - `op-vault <name> [--] <op args…>` — `tpm2_nvread` the well-known
    index → token into child env only → `exec op`. Missing token is
    fatal with a pointer to the mint command; no interactive fallback
    (op-homelab's stance).
  - `op-vault-mint <name>` — token via stdin (echo off on a tty),
    validates the `ops_` prefix, sizes the NV index to the exact
    token length, undefine+redefine on re-mint. Rotation = run again.
  - Minting is a deliberate human act (machine-key pattern); probes
    discover what it wrote.
- **TPM facts** (voltaire): NV index max 2048 bytes, buffer 1024
  (tools chunk); `0x01800050+` range free; avoid `0x1410001-3`,
  `0x1800100`, `0x1880001/11`, `0x1C*` (firmware/TCG) and persistent
  handles `0x81000001/2` (orphans). `systemd-creds --user` refuses
  `--with-key=tpm2` (uid-scoped mode) — rejected.

## Remaining

- [ ] chezmoi: probe template for which NV tokens a machine holds
      (mirrors `machine-key-mode`; needed when the first template
      gates on token presence)
- [ ] Rewire voltaire consumers: work-secret provisioning
      (`secrets.fish` is gated on `has1Password`, which voltaire
      fails — the switch token is the headless path work secrets have
      never had); split the `homelab` flag when the first consumer
      needs it (see [machine-roles](machine-roles.md))
- [ ] `op-homelab` consumer swap: its token branch reads the NV
      `homelab` token where one is minted, file otherwise — call
      sites unchanged
- [ ] Homelab-vault tokens per machine (retiring the shared
      `OP_SERVICE_ACCOUNT_TOKEN` file needs the nine consumer paths
      listed in secret-architecture § "Service account token on disk")
- [ ] bilby (YubiKey PIV object; after FDE decision) and fractal
      (documented encrypted-disk tier) answers
- [ ] Fold end state into dotfiles README + `docs/secrets.html`;
      delete this plan
