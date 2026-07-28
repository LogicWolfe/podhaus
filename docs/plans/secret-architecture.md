# Secret architecture — longer-term goals

Captures the target state for how secrets reach each host, and the gaps
between that and what runs today. Written after a `chezmoi update`
failure on bilby surfaced the fact that the 1Password CLI has no session
on machine-ssh hosts; the investigation widened into where secrets live
at rest across the homelab.

Nothing here is urgent. The immediate `chezmoi` breakage is tracked
separately in the dotfiles repo and does not depend on any of this.

## Threat model

The scenario we want to defend: **an attacker takes physical possession
of a machine and its hardware token, but cannot log in.** Success means
they do not obtain secret data.

Explicitly *not* in scope, and deliberately tolerated for now:

- Live compromise — code execution as `nathan` on a running host. Any
  scheme that supports unattended operation loses here by construction,
  because the credential that unlocks the hardware must itself be
  reachable without a human.
- Evil-maid attacks on unencrypted `/boot`.

## Governing conclusion

**Full-disk encryption is the load-bearing control, and hardware-backed
secret storage is not a substitute for it.**

On a host with no disk encryption, an attacker who takes the machine does
not need to log in — they pull the disk or boot external media and read
the filesystem. At that point the mechanism protecting a secret is
irrelevant: a plaintext file, a YubiKey PIV data object, and an
age-encrypted blob are equally compromised, because the PIN or identity
material that unlocks the hardware is on the same unencrypted disk.

Hardware-backed storage defends a *different* case — theft of a disk,
backup, or snapshot **without** the accompanying hardware token. That is
worth having, but it is defense in depth layered on encryption, not a
replacement for it.

## Per-host target state

| Host | Class | Secret path | Rests on |
|---|---|---|---|
| bilby | Asahi (Apple Silicon), YubiKey PIV | 1P Homelab vault, direct | hardware + FDE *(gap)* |
| voltaire | Linux, TPM | 1P Homelab vault, direct | hardware + FDE *(gap)* |
| kookaburra | Komodo periphery | Komodo variable interpolation | FDE *(gap)* |
| kangaroo | QNAP QTS appliance | Komodo variable interpolation | network auth only |

kookaburra and kangaroo need no per-host credential work: as Komodo
periphery hosts they are already on the
`1P Homelab → komodo-op → Komodo Variables → [[VARIABLE]]` path
documented in [`docs/secrets.html`](../secrets.html). "Source secrets
from bilby" is already true for both.

## Workstreams

Ordered by dependency, not by schedule. Each is independently useful.

### Disk encryption

The prerequisite for the threat model above. Undecided whether this is
full-disk or a partial scheme covering only the paths that hold secrets
— that choice drives everything else here.

**bilby has no encryption today** (verified: no LUKS volumes, no
`/etc/crypttab`; `/home` is plain btrfs on `nvme0n1p6`). It also has **no
TPM** — Apple Silicon does not expose one to Linux, which is why it uses
a YubiKey for machine-ssh. So TPM-bound auto-unlock is unavailable and
some other unlock method is required.

The constraint that makes this non-trivial is unattended reboot. Options,
none yet chosen:

- **Clevis + Tang (network-bound).** Unlocks only when the host can reach
  a Tang server on the LAN; a stolen machine taken off-network stays
  encrypted, and reboots stay unattended. Fails if the whole rack is
  taken together — mitigated by hosting Tang somewhere not co-located, or
  an SSS policy requiring 2-of-N.
- **Remote unlock via SSH in initramfs** (dracut + dropbear). Strongest
  of the practical options and depends on no server that might be stolen
  alongside, but reboots become semi-attended.
- **YubiKey FIDO2 with user verification.** Since the attacker has the
  key, security rests entirely on a FIDO2 PIN that must not be on disk.
  The retry counter makes that respectable, but it needs a human at every
  boot.

Retrofitting means either in-place `cryptsetup reencrypt` or a
backup-and-restore cycle on a 159 GB `/home` — real risk and real
downtime either way. `/boot` stays unencrypted regardless.

kangaroo cannot participate: QTS is an appliance OS. Its secrets are
protected by the next item instead.

### Secrets at rest on periphery hosts

Komodo writes a rendered `.env` — resolved secrets plus the stamped
`STACK_CONTENT_HASH` — into each stack's `run_directory` at deploy time.
So the Komodo path distributes secrets from 1Password without a bespoke
channel, but it **does not keep them off disk**.

For kookaburra this is acceptable once FDE lands. For kangaroo it is the
only exposure that matters, since the appliance cannot be encrypted.

Candidate fix: a **tmpfs `run_directory`** on kangaroo, so resolved
secrets exist only in RAM. Komodo redeploys and rewrites `.env` on boot,
and there is already an `@reboot` crontab line installed by
`kangaroo_bootstrap` for Container Station survival. **Unverified** —
needs checking against Komodo's deploy assumptions and against QTS
tmpfs sizing before being treated as viable.

Note also that kangaroo's secrets are only as protected as whatever
authenticates it to Komodo. If that credential lands on its disk, the
problem has moved rather than been solved. Connect tokens are scopeable
and revocable, so the mitigation is tight vault scoping plus rotation
rather than secrecy of the client credential.

### Service account token on disk

`OP_SERVICE_ACCOUNT_TOKEN` at the repo root is plaintext, `0600`, and
gitignored. AGENTS.md documents it as the one secret deliberately allowed
raw on disk.

Removing it is wider than it looks — **13+ files consume it**, including
running infrastructure: `komodo-start` / `komodo-sync` / `komodo-upgrade`
(each `cat`s it directly), `onepassword/compose.yaml` and `stack.toml`,
`terraform/backend.tf` and `tailscale.tf`, five `paperless/*` scripts,
and both `kangaroo_bootstrap` and `kookaburra_bootstrap`.

The token grants exactly the **Homelab** vault and nothing else
(verified: the service account sees one vault). That scoping is already
correct and is what makes the blast radius tolerable.

Hardware-backed storage for it — a YubiKey PIV data object on bilby, a
TPM NV index on voltaire — is feasible: the token is 853 bytes, `ykman`
5.9.0 supports arbitrary PIV object import/export and is already
installed, and only PIV slot 9A is occupied (the machine-ssh key), so the
retired slots are free. Whether a chosen object is PIN-gated on read
needs verifying empirically rather than assumed.

**But per the governing conclusion, most of this value is subsumed by
FDE.** Once the disk is encrypted, moving the token into hardware defends
only the stolen-backup case. Reassess priority after encryption lands
rather than building it first. If a master copy is ever needed for
re-provisioning, it belongs in the **Personal** vault — human-authenticated
and deliberately unreadable by the service account itself.

## Known caveats

**Secret rotation does not auto-redeploy.** `hashDir` excludes the
deploy-written `.env`, so `STACK_CONTENT_HASH` does not change when a
1Password value changes — only committed in-stack content triggers a
redeploy. AGENTS.md records this as a deliberate non-goal, but it means
rotating a credential silently leaves stale values running until the next
committed change. This directly weakens the "rotate rather than keep
secret" mitigation relied on for kangaroo above.

## Open questions

- Full-disk or partial encryption, and which unlock method.
- Does a tmpfs `run_directory` work on kangaroo under Komodo and QTS?
- What hardware does kookaburra actually have? Not checked — it may not
  matter, since the Komodo path means it needs no per-host credential.
- Is the rotation-doesn't-redeploy behaviour worth revisiting given it
  undercuts rotation as a mitigation?
