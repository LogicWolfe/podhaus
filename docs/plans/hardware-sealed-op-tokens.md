# Unified development identity and limited MacBook management

## Goal

Make ordinary development authentication the same on bilby, fractal, voltaire,
and the MacBook Air:

- Git, SSH, commit signing, chezmoi, 1Password CLI use, and Podhaus operations
  use a machine identity and per-machine 1Password service accounts.
- Nathan's personal 1Password account is a short, explicit override that only
  Nathan starts. Agents never invoke it, recommend it as a fallback, or depend
  on an override that happened to be open.
- `op-vault` is the only public service-account interface in every shell and on
  every operating system.
- The MacBook joins only the managed development surface. It gets outbound SSH,
  service accounts, managed SSH configuration, and a locally opened temporary
  inbound maintenance window. It does not join Podhaus runtime, container, or
  logging management.
- The final implementation has fewer authentication systems and fewer lines of
  non-generated source and configuration than the starting state.

The MacBook is the final work unit for both authentication and management. No
Mac-specific implementation or inventory change lands until the shared Linux
contract and all three Linux machines pass their closeout checks. At that point
the remaining work is handed to a local agent on the MacBook.

## Completion rules

The work is complete only when all of these are true:

1. One executable, `op-vault`, owns service-account selection, token retrieval,
   environment cleanup, command execution, and human-only token enrolment.
2. Bash and fish call the same executable. Neither shell owns an authentication
   function, startup hook, or repository-directory hook.
3. No repository or dotfiles consumer reads a shared token file. No
   compatibility wrapper preserves `op-homelab` or `op-vault-mint`.
4. Automatic paths use the machine SSH key and never start personal 1Password
   authentication.
5. Every machine has a separately revocable service account in each 1Password
   account it uses. Vault grants match the table below exactly.
6. Missing hardware, a locked backend, or a missing vault grant fails closed.
   The error names the failed identity or grant and does not suggest a personal
   fallback.
7. Mac inbound SSH is off by default, can be opened only by Nathan locally, and
   closes automatically.
8. The total touched non-generated code, tests, templates, shell configuration,
   and Ansible/Terraform configuration ends net negative in lines. Documentation
   and this temporary plan are reported separately and cannot hide source
   growth.
9. Durable documentation describes the resulting system, then this plan is
   deleted.

## Audited starting point

Audit date: 2026-08-17.

| Machine | Current identity and token state | Required change |
|---|---|---|
| **voltaire** | Live verified. TPM NV `0x01800052` holds a `my/Dev` service token, `0x01800051` holds a `switchtechnologies/Dev` service token, and the TPM machine SSH key is loaded. The old repo-root token file is absent. | Complete after the common runner and legacy-path removal deployed successfully. |
| **bilby** | Live verified. The YubiKey PIV machine SSH key is active. The disk has no LUKS or encrypted home, and the old shared Homelab token remains until its replacement account passes verification. | Enrol only `bilby-dev` in the mode `0600` file backend, verify consumers, then delete the shared token. Bilby has no Switch access. Full-disk encryption remains separate security debt. |
| **fractal** | Live verified. Its software machine SSH key is active and its home is LUKS-backed. The old shared Homelab token remains until replacement accounts pass verification. | Enrol the two per-machine accounts in the encrypted-home file backend, verify consumers, then delete the shared token. |
| **MacBook Air** | Darwin currently has `machine-key-mode=none`, uses the 1Password desktop SSH agent for Git and SSH, and has no fleet or Ansible entry. It is intentionally unreachable inbound. | Audit and implement locally after Linux closeout. Add only the limited client surface described below. |

The current warning on voltaire is a lookup bug, not a missing TPM token.
`op-homelab` only checks `~/repos/podhaus/OP_SERVICE_ACCOUNT_TOKEN`; it does not
call the working TPM-backed `op-vault` path.

## Implementation status

The common Linux implementation landed in dotfiles commit `d6211b7` and is
deployed on voltaire, bilby, and fractal. The three hosts pass the shared runner
tests, use their machine SSH keys, and no longer install the legacy automatic
personal-authentication commands. Voltaire passes both live service-account
identity checks from its TPM backend.

The Podhaus consumer migration is implemented in this change. Nine scripts now
require the service-account environment from `op-vault dev`, Terraform uses one
committed `op run` environment file, and operator and agent guidance names the
same explicit boundary. The shared token files on bilby and fractal are
deliberately still present because deleting them before their new accounts are
created would remove the only recovery copy available on those machines.

Linux closeout is waiting only on human-controlled 1Password state: create and
paste the three per-machine service-account tokens, move the work item to its Dev
vault, move and rename the existing client-side HyperDX item into Dev, add the
gateway client token to it, and revoke the old shared account after verification.
No Mac-specific implementation has started.

The source audit found these overlapping systems to remove or collapse:

- `op-homelab` and `.chezmoitemplates/op-homelab-ready`;
- the separate `op-vault-mint` program;
- `op-pty-signin`, `op-ensure`, `op-ssh-key`, `op-unlock-auto.fish`, and the
  personal SSH-agent/refcounting parts of `op-unlock` and `op-lock`;
- automatic personal authentication in `__chezmoi_update.fish`;
- the fish-only `podhaus-tf.fish` directory hook;
- nine Podhaus scripts that read the repo-root token directly;
- role inference spread across `headless`, `homelab`, desktop-agent detection,
  and whether a checkout happens to exist;
- Ansible and agent guidance that still names `op-unlock` as the normal path.

The directly deletable dotfiles paths total 708 lines today:

| Legacy path | Lines |
|---|---:|
| `op-homelab` | 42 |
| `op-vault-mint` | 52 |
| `op-pty-signin` | 116 |
| `op-unlock-auto.fish` | 92 |
| `op-ensure.fish` | 44 |
| `op-ssh-key.fish` | 32 |
| current `op-unlock.fish` and `op-lock.fish` implementation | 168 |
| `podhaus-tf.fish` | 113 |
| `op-homelab-ready` | 49 |

That is the initial budget for the common runner, tests, the final Swift
adapter, and the small Mac SSH role. Further reductions should come from the
chezmoi role/template cleanup and removing token boilerplate from Podhaus.

## Target authorization model

1Password account boundaries require two service accounts per machine for
machines that do both personal and Switch development. Each account is named
for its machine. Losing one machine revokes only that machine.

| Machine | `my` account grants | `switchtechnologies` grants | Podhaus operator | Runtime host |
|---|---|---|---|---|
| bilby | Dev, Homelab | none | yes | existing |
| fractal | Dev, Homelab | Dev | yes | existing |
| voltaire | Dev | Dev | no | existing |
| MacBook Air | Dev | Dev | no | no |

`my/Dev` is the routine personal-development vault. `my/Homelab` is added to
the same machine account only where Podhaus administration requires it.
`switchtechnologies/Dev` is the routine work-development vault on fractal,
voltaire, and later the MacBook. Bilby has no account or token in
`switchtechnologies`. No service account receives Personal, Employee, or
another broad vault.

Move the work `AUTH0_CLIENT_SECRETS` item from Employee to the work Dev vault
after confirming its consumers. The Homelab `clickstack-hyperdx-mcp-key` item
already holds the client-side HyperDX access key and is not a Komodo runtime
input. Move it to `my/Dev`, rename it `Podhaus HyperDX`, keep its existing
`credential` field, and update the stale Cloudflare Access description. Add
the existing `hyperdx_mcp` gateway client token as `gateway token`; keep that
token's Homelab copy because Komodo supplies it to Caddy. This reuses the
credential already made for Claude MCP and avoids a second HyperDX API key or
gateway-token path.

Keep the 1Password Connect token used inside the Podhaus `onepassword` stack
out of this migration. It is runtime infrastructure, not a developer service
account.

## The one public interface

The installed contract is:

```text
op-vault <dev|switch> -- <command> [arguments...]
op-vault mint <dev|switch>
```

Examples:

```text
op-vault dev -- op read 'op://Dev/GitHub/token'
op-vault switch -- op run --env-file=.env.op -- make deploy
op-vault mint dev
```

`dev` selects the machine account in `my`; `switch` selects the machine account
in `switchtechnologies`. Callers name `op` when they want the CLI. The runner
can also execute Terraform, chezmoi, or a repository script with the selected
service token.

The public runner remains a small POSIX `sh` program because Bash and fish can
both pass it an unchanged argument vector. A Rust program would add builds,
packages, platform targets, macOS Security bindings, and signing for a contract
that is mostly `env` plus `exec`. Use a compiled component only for the narrow
Mac Keychain operation that system shell tools cannot express correctly.

The runner must:

- reject unknown identities and malformed invocation before reading a token;
- remove inherited `OP_SERVICE_ACCOUNT_TOKEN`, `OP_CONNECT_HOST`,
  `OP_CONNECT_TOKEN`, and `OP_SESSION_*` values;
- select one explicit host backend without a plugin framework or config
  language;
- read the token into the child environment without putting it in arguments,
  files, stdout, or diagnostics;
- replace itself with the child process;
- make `mint` interactive, refuse stdin that is not a terminal, validate the
  `ops_` prefix, confirm it is a service-account identity before writing, and
  delegate only the backend write;
- print recovery instructions that name `op-vault mint`, never `op-unlock`.

Internal adapters live under `libexec/op-vault/` and expose only read and write.
Backend selection is a short explicit case over the managed host, not a generic
extension system.

## Token and machine-key backends

| Machine | Service-token backend | Machine SSH identity |
|---|---|---|
| voltaire | Existing TPM NV indices `0x01800052` for `dev` and `0x01800051` for `switch` | Existing TPM key |
| bilby | One mode `0600` file for `dev`; no `switch` backend | Existing YubiKey PIV key |
| fractal | Two mode `0600` files inside the LUKS-backed home | Existing software Ed25519 key inside the encrypted home |
| MacBook Air | Two device-bound Data Protection Keychain items, implemented last | New mode `0600` software Ed25519 machine key inside FileVault |

This deliberately allows more than one storage mechanism but keeps one public
interface. The host security boundary chooses the backend. Consumers never do.

### Bilby security gate

Do not put a service token in an arbitrary YubiKey PIV data object. Yubico's
[PIV object documentation](https://docs.yubico.com/yesdk/users-manual/application-piv/piv-objects.html)
states that undefined data tags do not require PIN verification, and its
[command documentation](https://docs.yubico.com/yesdk/yubikey-api/Yubico.YubiKey.Piv.Commands.PutDataCommand.html)
identifies only four PIV-defined tags that require a PIN to retrieve data.
Other data objects can be read by anyone holding the YubiKey. Storing the PIN
on bilby's unencrypted disk would only move the bearer secret.

The live bilby audit is therefore a required decision point:

1. Reconfirm the disk and home encryption state, PIV firmware and policies, and
   whether a user-session secret store already provides a post-login,
   through-lock boundary without adding a daemon.
2. If bilby gains encrypted storage as part of the already documented disk
   encryption work, use the same mode `0600` file adapter as fractal. This is
   the preferred outcome because it removes a backend.
3. If encryption is not part of this effort, present Nathan with the real
   tradeoff before enrolment:
   - accept a mode `0600` file as no worse than the current unencrypted shared
     token and record the physical-theft gap;
   - add a YubiKey private-key envelope, knowing that unattended PIN-free use
     protects disk-only theft but not theft of bilby with its YubiKey;
   - require a human PIN after each reboot, giving up fully unattended token
     access.
4. Do not continue to the MacBook until Nathan chooses one and bilby passes its
   machine checks.

The existing YubiKey machine SSH key remains in every option. Token storage
does not need a second YubiKey abstraction merely because SSH already uses it.

### Mac Data Protection Keychain adapter

The final Mac-only component is a small native Swift command under
`libexec/op-vault/`. It uses `SecItemAdd`, `SecItemCopyMatching`, and
`SecItemUpdate` for two `kSecClassGenericPassword` items with:

- `kSecUseDataProtectionKeychain = true`;
- `kSecAttrSynchronizable = false`;
- `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`.

This makes tokens available after Nathan's first unlock following a restart,
keeps them usable while the screen is locked, and makes them unavailable again
after restart until the first unlock. `ThisDeviceOnly` prevents migration to a
replacement Mac. Any process running as Nathan after first unlock can invoke
`op-vault`; that is the intended unattended-agent boundary.

Apple's [Keychain data protection](https://support.apple.com/guide/security/keychain-data-protection-secb0694df1a/web)
documentation says the secret value has a per-row encryption key whose use
always requires a Secure Enclave round trip. This is the Mac parallel to the
TPM boundary without making the token depend on the 1Password desktop app.

The Swift program owns only Keychain read/write. The common shell runner still
owns identity selection, environment cleanup, and child execution. There is no
Mac daemon, vault application, plugin protocol, or patched upstream dependency.

## Machine roles and ownership

Use one existing fleet data source to declare user-level purpose. Add only two
properties to each known development machine:

- `development = true`: install the machine identity, both Dev account paths,
  development secret consumers, and agent guidance;
- `podhaus_operator = true`: permit `my/Homelab` consumers and Podhaus operator
  commands.

Bilby and fractal have both properties. Voltaire and the MacBook have only
`development`. Unknown hosts default to neither and receive a clear bootstrap
instruction. Remove the `homelab` prompt and stop inferring authorization from
a desktop socket, an installed CLI, or a checkout. Keep UI-specific facts only
where a UI template genuinely needs them. Runtime membership remains solely in
Ansible and Komodo inventory.

The ownership boundary remains:

- chezmoi owns user SSH and Git configuration, machine key helpers,
  `op-vault`, shell behaviour, secret-consuming user configuration, and agent
  guidance;
- Ansible owns root configuration and services;
- 1Password owns service-account grants and secret items;
- Terraform owns tailnet policy;
- Komodo owns runtime hosts and stacks.

## Tailnet audit result

No ACL change is planned.

`terraform/tailscale.tf` is authoritative and overwrites tailnet policy. Its
current member-to-member grant already allows Nathan's normal member devices to
reach another normal member device on TCP 22 when that device is listening.
Pocket ID grants tailnet membership to Nathan, not Sky. A `tag:dev-client` would
add policy and enrolment state without narrowing the existing member grant.

The Mac therefore enrols as Nathan's normal member device. The local Remote
Login service, its Tailscale-only bind, and the shields timer are the access
boundary.

Before the Mac work starts, run `terraform plan` for the tailnet stack using the
new bilby or fractal service-account path. The expected ACL delta is empty. If
the plan reports drift, proposes an ACL change, or normal-member enrolment does
not work for the Mac, stop and flag Nathan. Do not apply an ACL mutation as part
of this effort without a new decision.

## Work units

The units are ordered by dependency. Each unit starts with its black-box or
configuration test, makes the smallest implementation change, then deletes the
superseded path. Do not carry temporary compatibility code into the next unit.

### 1. Freeze the contract and the reduction ledger

Goal: make simplification measurable before changing behaviour.

Changes:

- Record the baseline line counts for every touched non-generated executable,
  test, template, shell config, Ansible file, and Terraform file in dotfiles
  and Podhaus.
- Record deletions and additions by work unit. Keep documentation and this plan
  in a separate total.
- Write failing executable-boundary tests for argument preservation,
  environment cleanup, backend selection, token non-disclosure, enrolment
  validation, and fail-closed behaviour.
- Add static checks that ban direct reads of the repo-root token and automatic
  calls to personal authentication.

Exit check:

- Tests fail for the known current behaviours.
- The ledger lists every legacy file intended for deletion.
- The proposed common runner and tests still project a net source/config
  reduction. If they do not, simplify the design before implementation.

### 2. Establish the Linux `op-vault` contract on voltaire

Goal: generalise the known-working TPM path before touching another host.

Changes:

- Change `op-vault` from an `op`-argument wrapper into the command-execution
  contract above.
- Fold enrolment into `op-vault mint` and delete `op-vault-mint`.
- Move TPM read/write details into the smallest useful internal adapter, or
  keep them inline if separation increases code without improving a second
  backend.
- Validate both existing Voltaire identities and exact vault grants.

Exit check:

- Bash and fish pass the same adversarial argument-vector tests.
- Both existing NV tokens authenticate as Voltaire's service accounts.
- Personal and Homelab reads fail through the `dev` identity.
- Token bytes are absent from process arguments, output, temporary files, and
  test diagnostics.

### 3. Audit and enrol bilby

Goal: close the unresolved Linux hardware/storage case before building more
around it.

Changes:

- Complete the parked Voltaire to bilby approval, then inspect the live machine
  key, disk encryption, current token, installed PIV tools, PIV object policy,
  shell, and service-account grants.
- Resolve the Bilby security gate with Nathan if encrypted storage is still
  absent.
- Implement only the selected backend. Prefer reusing fractal's encrypted-file
  adapter if the encryption work lands.
- Create `bilby-dev` in `my` with Dev and Homelab. Nathan performs token
  creation and the one-time local paste. Do not create a Bilby account in
  `switchtechnologies`.
- Verify machine SSH use independently of any personal agent.

Exit check:

- The account reports the expected identity and exact grants. `op-vault
  switch` refuses Bilby before reading a token.
- Personal reads fail; Homelab succeeds only through `dev`.
- Reboot/lock/absence behaviour matches the backend decision and is recorded
  accurately.
- No plaintext compatibility token is copied into a new location.

### 4. Audit and enrol fractal

Goal: reuse the simplest software backend inside an existing encrypted boundary.

Changes:

- Reach fractal from bilby and inspect the live machine key, LUKS mount,
  current token, home permissions, shell, and grants.
- Add the mode `0600` file adapter inside the encrypted home.
- Create `fractal-dev` in `my` with Dev and Homelab and `fractal-switch` in
  `switchtechnologies` with Dev. Nathan performs token creation and paste.
- Verify the software machine SSH key remains the only automatic SSH identity.

Exit check:

- The same identity and negative-vault checks pass as bilby.
- Token files are inside the verified encrypted mount, mode `0600`, excluded
  from chezmoi and Git, and never printed.
- Removing or locking the encrypted mount fails closed.

### 5. Replace chezmoi roles and secret consumers

Goal: make a fresh apply describe intended access once and use the common path.

Changes:

- Add `development` and `podhaus_operator` to the known Linux fleet entries.
- Remove the overloaded `homelab` prompt and unrelated authorization inference.
- Replace `op-homelab-ready` with the smallest direct capability check at the
  template call site. A first apply may skip a secret target with one clear
  message; after `op-vault mint`, the second apply must render it.
- Change `.claude.json`, work-secret rendering, and Homelab-derived SSH data to
  call `op-vault` with the declared identity and required vault.
- Move or replace the two broad-vault secret items before changing references.
- Delete `op-homelab` and `.chezmoitemplates/op-homelab-ready` in the same
  change. Do not leave a compatibility wrapper.

Exit check:

- `chezmoi apply` succeeds without `OP_SESSION_*`, an interactive prompt, or a
  repo-root token on all three Linux machines.
- A fresh-token-missing fixture skips only the targets that need a token and
  tells the operator to run `op-vault mint`.
- A valid Dev-only account cannot satisfy a Homelab capability check.
- A second real apply is clean.

### 6. Replace Podhaus token consumers

Goal: remove the shared bearer file and fish-only ambient environment.

Changes:

- Put the ten Terraform `op://Homelab/...` references in one committed
  `op run` environment file in Podhaus.
- Document and test the explicit form:

  ```text
  op-vault dev -- op run --env-file=terraform/terraform.env.op -- \
    terraform -chdir=terraform <command>
  ```

- Delete `podhaus-tf.fish`. Do not replace it with a Bash or fish function.
- Remove direct token reads from `komodo-start`, `komodo-sync`,
  `komodo-upgrade`, `kangaroo_bootstrap`, and the five Paperless maintenance
  commands. Their supported invocation is `op-vault dev -- <script>`.
- Add one shared preflight only if the scripts need more than the missing
  environment variable error. Do not add self-reexecution boilerplate to nine
  files.
- Update playbook headers and operator docs to use the caller's machine SSH key
  and explicit `op-vault` invocation.

Exit check:

- Static search finds no Podhaus executable reading the repo-root token.
- Terraform init/validate/plan receives all ten credentials only for the child
  process and leaves none in the parent shell.
- Each maintenance command reaches a harmless preflight through the wrapper.
- Commands fail clearly when invoked without the required identity.

### 7. Remove automatic personal-account machinery

Goal: make personal access a small human override instead of a shadow machine
identity system.

Changes:

- Make Git, commit signing, SSH, Ansible, and chezmoi use the machine key on
  bilby, fractal, and voltaire.
- Remove personal SSH extraction and `op-unlock` calls from
  `__chezmoi_update.fish`.
- Delete `op-unlock-auto.fish`, `op-ssh-key`, `op-ensure`, and `op-pty-signin`.
- Reduce `op-unlock` to an explicit human command that signs into exactly the
  requested personal account with `op-unlock [my|switchtechnologies]`,
  defaulting to `my`. It does not create an SSH agent or sign into both
  accounts as a side effect.
- Reduce `op-lock` to clearing the requested personal session, or all personal
  sessions when no account is named.
- Remove desktop-agent availability as a Git/signing authorization decision.
- Update `dot_claude/commands/ssh.md`, rendered agent guidance, dotfiles README,
  Podhaus `AGENTS.md`, Ansible comments, and playbook headers together.
- Re-scan the source for Claude/Codex prompts, commands, and skills that mention
  `op`, secrets, SSH identity, or personal fallback. Keep the rule in the two
  existing authoritative guidance surfaces. Do not create a new authentication
  skill or copy policy into generated caches.

The durable agent rule is:

> Use `op-vault dev -- <command>` or `op-vault switch -- <command>` for ordinary
> development. Missing hardware or a missing grant is an authorization
> boundary. Never invoke, request, or recommend `op-unlock`, a personal
> 1Password session, or a Personal-vault read unless Nathan explicitly asks for
> that personal operation in the current conversation.

Exit check:

- Non-interactive fish and Bash startup, chezmoi update, Git, SSH, and Ansible
  never execute `op signin`, `op-unlock`, or a Personal-vault read.
- Source search finds no agent prompt or skill that recommends personal
  authentication for routine work.
- A plain fetch, signed test commit, and Podhaus SSH connection use each
  machine's recorded machine-key fingerprint.
- Nathan can explicitly run the reduced override and `op-lock` removes it.
- The deletion ledger remains net negative.

### 8. Retire the shared service account and close Linux

Goal: prove the common system is complete before exposing any Mac-specific work.

Changes:

- Search both repositories, ignored operational paths, shell environments, and
  durable docs for the old shared account and token filename.
- Remove the repo-root token from bilby and fractal only after every intended
  consumer passes through `op-vault`.
- Revoke the old shared service account in 1Password.
- Rotate any credential if its token value appeared in output, history, or an
  unexpected file during migration.
- Run the tailnet Terraform plan. Require zero ACL change.

Linux closeout gate:

- All three Linux hosts pass the full machine matrix below.
- The shared account is revoked and its files are absent.
- Source/config/tests are net negative at this point.
- Tailnet plan is clean. Any ACL finding is flagged to Nathan and pauses the
  Mac handoff.

### 9. Hand off the only remaining work to a local MacBook agent

Goal: add the Mac as a limited managed client without reopening the common
design.

The local agent starts only after the Linux closeout gate. Its packet contains
the already-landed `op-vault` contract, expected fleet fields, exact grant
matrix, tests, and these Mac-only tasks:

1. Audit the local hostname, macOS version, FileVault state, active Tailscale
   distribution and member identity, Python path, Homebrew prefix, 1Password
   CLI/app state, SSH configuration, Remote Login state, and existing listeners.
   Stop if FileVault is off or the Mac is not Nathan's normal tailnet member.
2. Add the Mac to chezmoi's fleet with `development = true` and
   `podhaus_operator = false`. Do not add it to a Podhaus runtime group.
3. Create a mode `0600` Mac-specific Ed25519 machine key under FileVault. It is
   a machine credential, so it does not get a passphrase or a second agent
   system. Register the public key with GitHub, Forgejo, Pomerium, and the three
   Linux hosts. Make it the default for Git authentication, signing, and
   outbound Podhaus SSH.
4. Write the failing Keychain attribute, lock-state, and non-disclosure tests,
   then implement the narrow Swift adapter and run the common backend contract
   tests locally.
5. Create `macbook-dev` in `my` with Dev and `macbook-switch` in
   `switchtechnologies` with Dev. Nathan creates the accounts and pastes each
   token through `op-vault mint` locally.
6. Add a separate Ansible inventory group and dedicated MacBook playbook. It
   may own only root-level SSH maintenance policy, the automatic-close
   mechanism, and assertions such as FileVault. It must not join `provisioned`,
   Docker, Periphery, Alloy, Komodo, or logging groups. Chezmoi continues to own
   all user files.
7. Add `shields-down <duration>` and `shields-up`. `shields-down` requires
   local sudo, enables native Remote Login for Nathan only, binds OpenSSH to the
   stable Tailscale address, and schedules a root-owned automatic close.
   `shields-up` closes it immediately. There is no passwordless sudo rule,
   public route, Pomerium route, rathole service, or Tailscale SSH dependency.
8. Do not invoke `shields-down` on Nathan's behalf. An agent may use an already
   open window but may not open one, extend one, change the ACL, or treat closed
   inbound SSH as a fault.
9. Run the Mac verification below, then run the Ansible play in check mode and
   require `changed=0` after the real apply.

Bootstrap the first Ansible run without adding a second provisioning path:
Nathan enables Remote Login locally for one initial bounded window, bilby runs
the dedicated playbook with its machine key, and the play installs the shields
mechanism and closes Remote Login. Every later window uses `shields-down`.

The local agent may change Mac-specific dotfiles and the dedicated inventory,
role, and playbook. It must stop and ask before changing the common runner,
Linux behaviour, tailnet policy, runtime inventory, or the authorization model.

### 10. Close the four-machine migration

Goal: leave durable truth and no temporary architecture document.

Changes:

- Run the complete verification matrix from the appropriate local host.
- Update the dotfiles README, Podhaus host provisioning, secrets,
  disaster-recovery, and inventory documentation to describe only the final
  paths.
- Remove stale Personal-agent, shared-token, PIV-object, and Mac tag guidance.
- Record final source/config/test and documentation line totals against the
  baseline.
- Delete this plan after the durable documentation is reviewed.

Exit check:

- All four machines pass.
- The final non-generated source/config/test total is net negative.
- No active documentation refers to a deleted compatibility path.
- Both repositories are clean after their normal formatting and validation
  commands.

## Verification matrix

Write failing checks before each behavioural change. Use temporary homes and
fake `op`, TPM, and file commands for the Linux contract tests, then add the
fake Keychain boundary only in the final Mac work unit. Verify the real
boundary on each machine.

### Common executable checks

- Bash and fish preserve the same child argument vector, including empty
  values, spaces, wildcard characters, newlines, and literal `--` values.
- Each backend selects only the requested identity.
- Inherited service, Connect, and personal-session variables cannot change the
  selected identity.
- Token bytes never appear on stdout, stderr, command arguments, generated
  files, test snapshots, or shell history.
- A missing backend, empty token, malformed token, unavailable hardware,
  pre-first-unlock Keychain, or denied vault fails before the requested child.
- No failure starts or recommends personal authentication.
- Mint refuses non-terminal input and cannot overwrite an existing token
  without explicit human confirmation.

### Per-machine identity checks

On each machine, for every identity in its grant-matrix row:

1. `op-vault <identity> -- op whoami` reports that machine's service account.
2. Vault listing matches the grant matrix exactly. Personal reads fail on all
   machines. Homelab reads fail on Voltaire and the MacBook.
3. `chezmoi apply` succeeds without a personal session, interactive prompt, or
   shared token file. A second apply reports no change.
4. A plain Git fetch, signed test commit, and Podhaus SSH connection use the
   recorded machine-key fingerprint.
5. A new non-interactive shell creates no personal session or personal SSH
   agent.

On Bilby, `op-vault switch` fails as an unsupported identity even if a stray
`switch.token` file exists.

On bilby and fractal only:

1. A harmless Homelab read succeeds through `op-vault dev`.
2. Terraform init and plan receive their environment through explicit
   `op-vault dev -- op run` execution.
3. Each migrated maintenance command passes its non-destructive preflight.
4. Ansible reaches managed hosts with the machine SSH identity.

On the MacBook only:

1. Keychain items have the exact accessibility, device-only, and
   non-synchronising attributes.
2. Token access fails before first unlock after restart, succeeds after first
   unlock, continues through screen lock, and fails to migrate to another Mac.
3. With shields up, TCP 22 is unreachable over Tailscale, wifi, and ethernet.
4. `shields-down 10m` makes TCP 22 reachable only through the Tailscale-bound
   listener. Both the root timer and `shields-up` close it.
5. No Docker, Periphery, Alloy, Komodo, Podhaus log shipper, or other new
   inbound listener is installed or enabled.

## Human actions and stop conditions

Nathan must perform or approve:

- the parked Pomerium connection needed for the bilby audit;
- the Bilby storage tradeoff if it remains unencrypted;
- creation, grant review, and one-time paste for each new 1Password service
  account;
- registration or revocation of public machine keys;
- revocation of the old shared service account;
- the first local Mac sudo approval and every future `shields-down` action.

Stop instead of improvising if:

- a required vault grant would broaden beyond the matrix;
- Bilby cannot meet the chosen storage boundary;
- a token is exposed outside the selected backend and child environment;
- the tailnet plan is not empty or normal-member Mac enrolment is unavailable;
- FileVault is disabled;
- Mac management would require joining a runtime or logging group;
- the source/config/test line total is no longer net negative.
