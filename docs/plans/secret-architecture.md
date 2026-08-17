# Secret architecture: longer-term goals

Captures the target state for how secrets reach each host, and the gaps
between that and what runs today. A `chezmoi update` failure on bilby exposed
the old dependency on an interactive 1Password session and widened the audit
into where secrets live at rest across the homelab. The Linux development-auth
migration now uses `op-vault`; the longer-term storage gaps remain here.

## Threat model

The scenario we want to defend: **an attacker takes physical possession
of a machine and its hardware token, but cannot log in.** Success means
they do not obtain secret data.

Explicitly *not* in scope, and deliberately tolerated for now:

- Live compromise: code execution as `nathan` on a running host. Any
  scheme that supports unattended operation loses here by construction,
  because the credential that unlocks the hardware must itself be
  reachable without a human.
- Evil-maid attacks on unencrypted `/boot`.

## Governing conclusion

**Full-disk encryption is the load-bearing control, and hardware-backed
secret storage is not a substitute for it.**

On a host with no disk encryption, an attacker who takes the machine does
not need to log in. They pull the disk or boot external media and read
the filesystem. At that point the mechanism protecting a secret is
irrelevant: a plaintext file, a YubiKey PIV data object, and an
age-encrypted blob are equally compromised, because the PIN or identity
material that unlocks the hardware is on the same unencrypted disk.

Hardware-backed storage defends a *different* case: theft of a disk,
backup, or snapshot **without** the accompanying hardware token. That is
worth having, but it is defense in depth layered on encryption, not a
replacement for it.

## Per-host target state

| Host | Class | Secret path | Rests on |
|---|---|---|---|
| MacBook Air | macOS personal development client | per-machine Dev service accounts, pending local implementation | planned device-bound Data Protection Keychain rows protected by Secure Enclave + FileVault |
| bilby | Asahi (Apple Silicon), YubiKey PIV SSH identity | per-machine Dev and Homelab service account through `op-vault` | mode `0600` token file on an unencrypted disk *(accepted gap)* |
| kangaroo | QNAP QTS appliance | Komodo variable interpolation | network auth only |
| numbat | BinaryLane Rocky Linux VM | Komodo interpolation + Terraform-managed 1P handoffs | provider disk + rendered stack env *(gap)* |
| fractal | Fedora WSL2, encrypted `/home` | per-machine Dev, Homelab, and Switch Dev service accounts through `op-vault`; Ansible 1P lookups + Komodo interpolation | mode `0600` token files in LUKS `/home`; Periphery and rendered stack env under unencrypted `/opt` *(gap)* |
| voltaire | Fedora Workstation development host | per-machine Dev service accounts through `op-vault` | TPM NV for tokens; rendered stack env on disk |

Kangaroo already receives service secrets through the
`1P Homelab → komodo-op → Komodo Variables → [[VARIABLE]]` path
documented in [`docs/secrets.html`](../secrets.html).

## Workstreams

Ordered by dependency, not by schedule. Each is independently useful.

### Disk encryption

The prerequisite for the threat model above. Undecided whether this is
full-disk or a partial scheme covering only the paths that hold secrets
because that choice drives everything else here.

**bilby has no encryption today** (verified: no LUKS volumes, no
`/etc/crypttab`; `/home` is plain btrfs on `nvme0n1p6`). It also has **no
TPM**. Apple Silicon does not expose one to Linux, which is why it uses
a YubiKey for machine-ssh. So TPM-bound auto-unlock is unavailable and
some other unlock method is required.

The constraint that makes this non-trivial is unattended reboot. Options,
none yet chosen:

- **Clevis + Tang (network-bound).** Unlocks only when the host can reach
  a Tang server on the LAN; a stolen machine taken off-network stays
  encrypted, and reboots stay unattended. Fails if the whole rack is
  taken together. Mitigate that by hosting Tang somewhere not co-located, or
  an SSS policy requiring 2-of-N.
- **Remote unlock via SSH in initramfs** (dracut + dropbear). Strongest
  of the practical options and depends on no server that might be stolen
  alongside, but reboots become semi-attended.
- **YubiKey FIDO2 with user verification.** Since the attacker has the
  key, security rests entirely on a FIDO2 PIN that must not be on disk.
  The retry counter makes that respectable, but it needs a human at every
  boot.

Retrofitting means either in-place `cryptsetup reencrypt` or a
backup-and-restore cycle on a 159 GB `/home`, with real risk and real
downtime either way. `/boot` stays unencrypted regardless.

kangaroo cannot participate: QTS is an appliance OS. Its secrets are
protected by the next item instead.

### Secrets at rest on periphery hosts

Komodo writes a rendered `.env`, containing resolved secrets plus the stamped
`STACK_CONTENT_HASH`, into each stack's `run_directory` at deploy time.
So the Komodo path distributes secrets from 1Password without a bespoke
channel, but it **does not keep them off disk**.

For kangaroo, rendered environment files are the main at-rest exposure because the
appliance can't use guest-managed full-disk encryption. Numbat has the same exposure
on its provider-managed disk. Fractal encrypts `/home`, but Periphery state and linked-repo
stack environments live under `/opt`, outside that encrypted volume.

Candidate fix: a **tmpfs `run_directory`** on kangaroo, so resolved
secrets exist only in RAM. The QNAP boot-DOM autorun hook starts Container
Station's Docker engine, but it doesn't currently repopulate Komodo run
directories. **Unverified:** check Komodo's deploy assumptions, QTS tmpfs
sizing, and the cold-boot ordering before treating this as viable.

Each remote host's Periphery private key also lives on disk. Moving rendered stack
environment into tmpfs would not protect those keys. A stolen host could still
authenticate to Core, so the design also needs a clear public-key revocation and
replacement runbook. Bilby's copies make replacement possible; they do not revoke
the stolen key.

### Service account token on disk

The Linux migration is implemented and its MacBook work is tracked in
[Unified development identity and limited MacBook management](hardware-sealed-op-tokens.md).
The nine repo-root-token consumers now cross one explicit `op-vault` boundary.
Voltaire uses TPM NV; bilby uses the accepted mode `0600` file on its
unencrypted disk; fractal uses mode `0600` files inside its encrypted home.
Automatic Personal-vault fallbacks have been removed. The MacBook's Keychain
backend and limited management boundary are the remaining implementation.

The `OP_SERVICE_ACCOUNT_TOKEN` passed to the `onepassword` stack is a different
Komodo variable carrying the 1Password Connect token. It is outside that
migration. Nathan owns the placement of recovery copies in 1Password. The
machine runner's contract is limited to selecting the configured service
account and enforcing its granted vaults.

## Known caveats

**Secret rotation does not auto-redeploy.** `hashDir` excludes the
deploy-written `.env`, so `STACK_CONTENT_HASH` does not change when a
1Password value changes. Only committed in-stack content triggers a
redeploy. AGENTS.md records this as a deliberate non-goal, but it means
rotating a credential silently leaves stale values running until the next
committed change. This directly weakens the "rotate rather than keep
secret" mitigation relied on for kangaroo above.

## Open questions

- Full-disk or partial encryption, and which unlock method.
- Does a tmpfs `run_directory` work on kangaroo under Komodo and QTS?
- Is the rotation-doesn't-redeploy behaviour worth revisiting given it
  undercuts rotation as a mitigation?
