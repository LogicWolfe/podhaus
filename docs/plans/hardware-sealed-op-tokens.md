# Hardware-sealed per-machine 1Password service tokens

Design sketch only — captured so future agents know what "the TPM token
plan" refers to. Nothing here is built, and no current work depends on
it. Details are deliberately unspecified until an iteration picks this
up.

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

## Shape of the fix

- **Per-machine service accounts, vault-scoped at creation.** 1Password
  service accounts natively scope to chosen vaults, so each machine gets
  its own account granted exactly the vault(s) it deserves. Revoking a
  machine = deleting its service account.
- **Curated vaults as the grant currency.** The judgement call per
  machine is *which vault*: full **Homelab**, or a lesser shared
  dev-box vault constructed for that purpose (expected default for dev
  machines — voltaire would likely get the lesser vault, not Homelab).
- **Hardware-sealed at rest.** Where the machine has a TPM (or YubiKey),
  the token is sealed to it (e.g. `tpm2 unseal` at point of use) —
  no plaintext at rest. Where no hardware exists (fractal: WSL, no TPM,
  no USB passthrough), fall back to a file on encrypted disk — the
  current fractal arrangement becomes the documented fallback tier, not
  the norm. This mirrors the machine-key `hardware > soft > none`
  probe-and-rank pattern in chezmoi.
- **`op-homelab` is the single consumer.** Its token branch swaps
  `cat $token_file` for the unseal; call sites don't change.

## Non-goals / notes

- Not needed for any host to be provisioned (stack secrets flow
  Komodo-side from bilby; chezmoi's `op-homelab-ready` probe already
  defers `.claude.json` gracefully where no token answers).
- The lesser shared-dev vault doesn't exist yet; creating and curating
  it is part of this work, and is Nathan's call.
