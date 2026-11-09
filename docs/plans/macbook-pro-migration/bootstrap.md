# Bootstrapping nb-macbook-pro from the dotfiles

> Investigation report gathered read-only on 2026-11-09 by a subagent; it feeds [the migration plan](../macbook-pro-migration.md). Where a recommendation here differs from the plan, the plan is authoritative.

Source: `~/.local/share/chezmoi` at `b7e4793`, chezmoi v2.70.0. Line references
are into that tree unless another path is given. Everything below was
established read-only. The Air was never changed. On the Pro, one probe had a
visible side effect, described in the note below.

> Side effect on the Pro: running `/usr/bin/git --version` there (to check
> whether the Xcode Command Line Tools stub was present) made macOS show its
> "install Command Line Tools" dialog on the Pro's screen. Nothing was
> installed. Nathan can cancel the dialog, or click Install, which does the
> same job as the Homebrew installer in step N2.

## Background: three facts that decide the order

1. **chezmoi applies in one alphabetical pass.** `run_before_` scripts run
   first. Next, every file and every plain, `run_once_` or `run_onchange_`
   script is applied in target-name order. `run_after_` scripts run last. A
   failing script or template stops the apply at that entry, and nothing
   after it is applied. Evidence: a scratch source tree under
   `scratchpad/order*`. A before-script ran, then an earlier file, then the
   apply stopped at a failing `output` template, and the later file was never
   written. A failing `run_onchange_05` script stopped the apply before
   `a_first`. Dot targets (`.claude.json`, `.config/…`, `.pi/…`) sort before
   `00-…`, so they render **before Homebrew is installed**. `chezmoi managed`
   prints the real order: `.agents … .zshenv`, then `00-ssh-hostkeys`,
   `02-homebrew`, `04-packages`, `05-machine-ssh-agent`, `Library`, then the
   `run_always_*` scripts. chezmoi has no `always` attribute, so those scripts
   are plain `run_` scripts whose target names begin with `always_`, and they
   run after `Library`. The after-scripts follow, and `default-shell` is last.
2. **Some files need secrets and Node.js while they render.**
   - `.chezmoitemplates/mcp-servers.sh:17` runs
     `op-vault dev -- op inject` from the source with `output`. That aborts
     the whole apply when it fails, as its own comment at lines 12-15 says.
     Two files use it. `~/.claude.json` (`modify_private_dot_claude.json.tmpl:17`)
     is ignored on hosts without `development`. `~/.pi/agent/mcp.json`
     (`dot_pi/agent/modify_private_mcp.json.tmpl:13`) is **not ignored on any
     host**.
   - `dot_config/private_fish/conf.d/secrets.fish.tmpl:1` runs
     `op-vault switch -- op inject` on hosts with `switch_development`.
   - `modify_private_dot_claude.json.tmpl:18`,
     `dot_claude-switch/modify_private_dot_claude.json.tmpl:5` and
     `dot_config/zed/modify_private_settings.json.tmpl:11` all `exec node`.
     A stock Mac has no `node`. It has `/usr/bin/jq`, `/usr/bin/timeout`,
     `/usr/bin/curl` and the `/usr/bin/git` stub, all checked on the Pro.
   - I confirmed the abort: with an empty `XDG_STATE_HOME`, rendering
     `mcp-servers.sh` exits 1 with "no 'dev' token … run: op-vault mint dev".
   - **Consequence:** before the first apply, the Pro needs `op` on PATH, the
     `op-vault` tokens on disk, `node` on PATH, and a hostname that `op-vault`
     recognises.
3. **The hostname is read at run time from `uname -n`.**
   - On the Air, `uname -n` is `nb-macbook-air` and so is `.chezmoi.hostname`.
     The LocalHostName (`Nathans-MacBook-Air`) is not used.
   - On the Pro today, `uname -n` is `Mac.localdomain`, so `.chezmoi.hostname`
     is `Mac`. LocalHostName is `NB-MacBook-Pro` and HostName is not set.
   - `op-vault:49-65` dies on an unknown host. So does `ssh-machine:19`, and
     `run_onchange_05-machine-ssh-agent.sh.tmpl:33` exits early.

## Recommended sequence (by dependency)

N = Nathan at the Pro's keyboard or using sudo. H = headless over SSH as
nathan. D = a dotfiles change made on the Air, which Nathan approves before it
is committed.

1. **D1** Teach the dotfiles about `nb-macbook-pro`, keeping every Air entry
   (Q4). Push before step H6.
2. **N1** `sudo scutil --set HostName nb-macbook-pro` (Q3).
3. **N2** Install Homebrew interactively. The installer also installs the
   Xcode Command Line Tools.
4. **N3** Pre-create `/etc/pam.d/sudo_local` with the exact line
   `run_always_07` expects (Q2). Optionally add the key-only sshd drop-in now.
5. **H1** Pre-seed `~/.ssh/known_hosts` on the Pro:
   - the Forgejo line, copied from `run_onchange_00-ssh-hostkeys.sh.tmpl:11`
     (fingerprint `SHA256:XteLtxcKlavlZS+KB4ZmQdwtFAPE4/++P3rxBLQvqzo`,
     verified locally);
   - the Air's `ssh.pod.haus` line, which is public;
   - `ssh-keyscan github.com`.
6. **H2** Copy the `op-vault` tokens from the Air without printing them (Q6).
7. **H3** Copy the Air's `cc-clip` binary (0.9.1) and
   `~/.cache/cc-clip/session.token` (Q5).
8. **H4** Install `chezmoi` and `node` with Homebrew, plus the
   `1password-cli` cask, all with no sudo. `node` is temporary:
   `run_onchange_after_05-mise-tools.sh.tmpl:12-20` uninstalls the Homebrew
   formula once mise has installed its own Node.
9. **H5** Optional: a temporary `~/.ssh/config.d/90-bootstrap.conf`
   containing `Host *` / `IdentityFile ~/.ssh/id_nb-macbook-pro`. It is needed
   only if 1Password's SSH agent is not set up yet when step H7 runs (Q1).
   Do **not** create `~/.ssh/config` itself (Q1).
10. **H6** Run `chezmoi init` with no apply, using the machine key and
    answering both prompts on the command line (Q1).
11. **H7** Run `chezmoi apply` with the Homebrew, `~/.local/bin`, mise-shims
    and cargo directories on PATH (Q2). Run it again if anything was fixed
    in between.
12. **N4** After the apply: set fish as the login shell; open 1Password,
    sign in and enable its SSH agent; open OrbStack and Adrafinil once; do
    the logins (Q7).
13. **H8** After 1Password's agent exists: run `chezmoi init` again and then
    `chezmoi apply`. This turns `has1Password` on. Delete the
    `90-bootstrap.conf` from step H5.
14. **Cutover** (later): stop the Air's docs tunnel. Turn the Pro's docs
    tunnel on by setting `podhaus_operator = true` on the Pro, and install
    Herdr. Remove the Air entries (Q5).

Exact headless commands for steps H1-H7 are in the appendix.

---

## Q1. First clone without 1Password

**The clone works with the machine key alone.**

- `chezmoi init` uses the `git` binary, and `git clone` inherits
  `GIT_SSH_COMMAND`. So this works:
  ```
  GIT_SSH_COMMAND='ssh -i ~/.ssh/id_nb-macbook-pro -o IdentitiesOnly=yes -o IdentityAgent=none'
  chezmoi init --promptBool headless=false --promptString podhausLan=auto git@git.pod.haus:LogicWolfe/dotfiles.git
  ```
  The two prompts are `promptBoolOnce headless` and
  `promptStringOnce podhausLan` (`.chezmoi.toml.tmpl:1` and `:34`). Without
  the flags, init needs a terminal.
- The Command Line Tools must be installed first, because `/usr/bin/git` is
  only a stub until then. The Homebrew installer in step N2 installs them.
- After the first apply, git authenticates by itself. `dot_config/git/config.tmpl:52`
  sets `sshCommand = ssh -i ~/.ssh/id_<hostname>` whenever
  `machine-key-mode` finds `~/.ssh/id_<hostname>`
  (`.chezmoitemplates/machine-key-mode:56`). Signing uses the same file
  (`config.tmpl:12`). Neither needs 1Password.

**Do not use a temporary `~/.ssh/config`, despite what the setup guide says.**

- `private_dot_ssh/create_private_config` is a `create_` file, so chezmoi
  never replaces an existing `~/.ssh/config`.
- `run_after_10-ssh-config-split.sh:53-83` converts an existing config only
  when every line in it also appears in the generated fragment. The guide's
  line `IdentityAgent "~/Library/…"` uses `~`, while the fragment uses the
  absolute path (`private_00-chezmoi.conf.tmpl:18`). So the split prints
  "was not split" and exits 0.
- The result: `~/.ssh/config` stays the temporary one forever, and the whole
  fleet routing in `config.d/00-chezmoi.conf` is never included.
- The setup guide (`~/repos/podhaus/docs/macbook-setup.md:22`) says "chezmoi
  replaces it". That is wrong. It needs a doc fix, which is a decision for
  Nathan.

**Does the apply itself need the 1Password desktop agent, or an interactive
`op` sign-in?**

- No chezmoi `onepassword*` template functions are used. The only matches
  are in comments. `[onepassword] prompt = false` is set
  (`.chezmoi.toml.tmpl:41-42`).
- Every secret read goes through `op-vault`, which uses service-account
  tokens with no interactive sign-in:
  - `mcp-servers.sh:17` and `secrets.fish.tmpl:1`, at render time;
  - `run_always_06-fj-auth.sh.tmpl:32`, from PATH;
  - `run_onchange_00-ssh-hostkeys.sh.tmpl:51-53` and `docs-tunnel-update:16`.
- The desktop agent matters in exactly one place: plain `ssh "$host"` in
  `run_onchange_after_11-cc-clip-devboxes.sh.tmpl:17,27`.
  - On a Mac, the routes that go straight to a host on the LAN pin no
    identity (`private_00-chezmoi.conf.tmpl:100-108`).
  - The Pomerium route offers only `id_personal.pub`
    (`private_00-chezmoi.conf.tmpl:137-142`).
  - With no agent, that script fails for every devbox and exits 1 at line
    45, which stops the apply.
  - With 1Password's agent, each connection may ask for approval on the
    Pro's screen.
  - Step H5's temporary `IdentityFile` adds the machine key to both routes.
    IdentityFile lines add up across matching blocks, and
    `IdentitiesOnly yes` still allows a configured file. The Linux hosts and
    Pomerium already accept that key, so the step runs unattended.
- `ssh-machine`, used by Herdr, never uses an agent (`ssh-machine:24`).

**What `has1Password = false` changes in the rendered output.** It is
computed once, at init time, by checking whether the agent socket file
exists (`.chezmoi.toml.tmpl:9`, `:37-38`). When false:

- `~/.ssh/config.d/00-chezmoi.conf` loses its `Host *` `IdentityAgent` line
  (`private_00-chezmoi.conf.tmpl:16-22`).
- `~/.config/fish/config.fish` stops setting `SSH_AUTH_SOCK` to 1Password
  (`config.fish.tmpl:38-44`).
- Git is unaffected while the machine key exists. The `has1Password` and
  `has1PasswordSigning` branches in `dot_config/git/config.tmpl:16,53,85`
  apply only when there is no machine key.
- Nothing else uses it.

**Switching it on later.** Run `chezmoi init` with no URL, then
`chezmoi apply`.

- `init` renders `.chezmoi.toml.tmpl` again and checks for the socket again.
  `headless` and `podhausLan` are "Once" prompts, so the existing answers
  are kept without asking.
- Only the two files above change. No script content depends on the value,
  so no `run_onchange_` script fires again.
- Editing `~/.config/chezmoi/chezmoi.toml` by hand also works, but the next
  `chezmoi init` overwrites it. Prefer the re-init.

**Recommendation: bootstrap first and switch 1Password on later.**

- Installing 1Password first gains nothing for the apply, and it ties the
  headless apply to approval prompts on the Pro's screen.
- Nathan has to be at the keyboard for the sudo steps anyway (N1-N3).
- He can install and sign in to the 1Password app after step H7, then run
  step H8.

## Q2. Steps that need root, a GUI session, a macOS permission, or a person

"Abort" means the script exits non-zero and the apply stops at that entry.
"Continue" means the script reports the problem and exits 0.

| Script and line | What it needs | On a fresh Mac, headless, without sudo |
|---|---|---|
| `run_onchange_02-homebrew.sh.tmpl:9` | sudo: the installer creates `/opt/homebrew` and installs the Command Line Tools through `softwareupdate`. `NONINTERACTIVE=1` with no cached sudo fails. | **Abort.** Pre-install in step N2. |
| `run_onchange_04-packages.sh.tmpl:40-51`, exits at `:442` | `brew` on PATH. The script does not add `/opt/homebrew/bin` itself. All five casks (`1password-cli`, `codex`, `zed`, `orbstack`, `adrafinil`) install binaries or apps into `/Applications`, which the admin group can write, so no sudo. | **Abort** if any install fails. `brew` missing from PATH makes every install fail, so export PATH (step H7). |
| `run_always_07-sudo-touch-id-macos.sh.tmpl:15-17` | `sudo tee /etc/pam.d/sudo_local`. It skips sudo only when the file already matches `auth       sufficient     pam_tid.so` byte for byte (`:13`). | **Abort, on every apply**, until step N3 creates the file. |
| `run_after_default-shell.sh.tmpl:24,29` | It only *prints* `sudo tee -a /etc/shells` and `chsh -s /opt/homebrew/bin/fish`. | Continue. Nathan runs both commands (step N4). |
| `run_onchange_after_11-cc-clip-devboxes.sh.tmpl:8` | `output "cc-clip" "version"` at render time. | **Abort** if `cc-clip` is not on PATH (step H3). |
| `run_onchange_after_11-cc-clip-devboxes.sh.tmpl:10,17-46` | SSH to every devbox. Line 10 includes **parked** hosts, so quokka is tried. | **Abort** if any devbox is unreachable or rejects the key. Being `run_onchange_`, it then runs again on every apply until it succeeds. See the finding below. |
| `executable_docs-server-update:30-31`, `executable_launchagent-reload:27`, `executable_docs-tunnel-update:44-45`, `executable_lumen-install-macos:32` (`brew services start ollama`) | `launchctl bootstrap` into the user's GUI session. That session exists only while nathan is logged in at the console. It exists now: `/dev/console` is owned by nathan, and `launchctl print gui/501` succeeds. | **Abort** if no one is logged in at the console. FileVault already forces a console login after every boot. |
| `run_onchange_after_15-adrafinil-hooks-macos.sh.tmpl:6` → `adrafinil-hooks-install-macos:8-9` | `/Applications/Adrafinil.app` must exist. It only writes hook files. Approving its privileged helper is a separate GUI step (N4). | **Abort** if the cask failed. |
| `run_after_16-herdr-machines-macos.sh.tmpl:11-29` | `hc`, which comes from the Herdr app, and is not installed by chezmoi. | Continue. It never fails (`:6-8`). |
| `run_always_09-codex-plugin.sh:13` | `claude` on PATH. | Continue. It exits 0 when Claude Code is absent. |
| `run_once_before_01-…teardown.sh.tmpl:8` | `launchctl print`. | Continue. |
| `run_always_06-fj-auth.sh.tmpl:9-34` | `fj`, `jq` and `op-vault`, called from PATH at `:32`. | **Abort** if `~/.local/bin` is not on PATH or the dev token is missing. |
| `modify_private_dot_claude.json.tmpl:17-18`, `dot_pi/agent/modify_private_mcp.json.tmpl:13`, `dot_config/zed/modify_private_settings.json.tmpl:11`, `secrets.fish.tmpl:1` | `op`, the tokens, a hostname `op-vault` knows, and `node`. | **Abort.** These render before Homebrew (Background, fact 1). |

No macOS-side script calls `osascript` or `open`. None calls `defaults`,
`systemsetup` or `scutil`. All other `sudo` lines are Linux-only branches.

**Templates that would abort the apply on a fresh Mac, headless, with the
documented prerequisites only:**

1. `.claude.json`, `.config/zed/settings.json` and `.pi/agent/mcp.json`,
   because there is no `node` and no `op-vault` token.
2. `02-homebrew`, because there is no sudo.
3. `04-packages`, because `brew` is not on PATH.
4. `always_07-sudo-touch-id`.
5. `11-cc-clip-devboxes`, because there is no `cc-clip`, or because SSH to a
   devbox fails.

**Finding to hand Nathan: the setup guide's order cannot work on a
development Mac.**

- What happens: the guide (`macbook-setup.md:58-62`) runs
  `op-vault mint dev` / `op-vault mint switch` *after* the first apply.
- The evidence: `mcp-servers.sh:17` aborts the apply without a token. It is
  reached through `~/.pi/agent/mcp.json`, which every host manages. The guide
  also never mentions that `node` must exist before the apply.
- Why it matters: anyone following the guide on a new Mac hits an apply that
  stops before Homebrew is installed.
- Recommended action: a documentation fix. Move token enrolment and a
  temporary `node` install ahead of the apply. This is mechanical.
- Also stale, and also mechanical: `README.md:220` says `04-packages`
  installs Claude Code through a cask. On macOS it installs Claude Code
  nowhere; the install at `:354-355` is inside the Linux-only block.

**Finding to hand Nathan: the clipboard-tunnel setup script still tries
parked hosts.**

- What it is: `run_onchange_after_11-cc-clip-devboxes.sh.tmpl:10` selects
  every devbox, including quokka, which is marked `parked` because it is
  lent out. The Herdr script (`run_after_16…:9`) already skips parked hosts.
- What happens: on a new Mac, if quokka is unreachable, the script exits 1,
  and every apply stops at that point. Everything after it is skipped:
  Lumen, Adrafinil, Herdr, the docs server and the shell reminder.
- Why it was not seen: on the Air the script last succeeded with its current
  content (`chezmoi status` does not list it), so it has not run again.
- Recommended fix: change the condition to
  `and $host.devbox (not $host.parked)`. This is mechanical.
- Alternative: have this script connect through `ssh-machine`, as Herdr
  does. Then it would never depend on 1Password. That is a design decision
  for Nathan, and its trade-off is that the clipboard setup would then run
  as the machine identity.

## Q3. Hostname

`.chezmoi.hostname` is the part of `uname -n` before the first dot (verified
on the Air, see Background fact 3). On the Pro it is `Mac` until Nathan runs
`sudo scutil --set HostName nb-macbook-pro`. That command changes `uname -n`
immediately. LocalHostName `NB-MacBook-Pro` already answers to
`nb-macbook-pro.local`. Changing LocalHostName or ComputerName is cosmetic.

What depends on the hostname being `nb-macbook-pro` **before** the first
apply:

- Every `fleet.toml` lookup. These are `.chezmoiignore:6-11`; the
  `development`, `switch_development` and `podhaus_operator` checks in
  scripts `00`, `06-fj-auth`, `20`-`24`; and `lumen-enabled`,
  `switch-vault-enabled` and the `oom-order`/`linux-devbox` templates.
- `machine-key-mode:56`, which looks for `~/.ssh/id_<hostname>`. With the
  hostname `Mac` it finds nothing, so git gets no machine key and no signing.
- The run-time `uname -n` users: `op-vault:49`, `ssh-machine:19`, and
  `run_onchange_05-machine-ssh-agent.sh.tmpl:33,130`.

What breaks if the apply runs while the hostname is still `Mac`:

- `op-vault` dies with "no service-account backend is configured for host
  'Mac'".
- So `~/.pi/agent/mcp.json` aborts the apply. That file is not tied to
  `development`, so this cannot be avoided, even with valid tokens.
- If it did get further, the result would be wrong anyway. The Pro would be
  treated as an unknown host: no development identity, no Lumen, no docs
  server, no Forgejo login, and no git machine identity.

`chezmoi init` by itself does not depend on the hostname, because
`.chezmoi.toml.tmpl` never reads it. Running init before the rename is
harmless. Running apply before it is not.

## Q4. Dotfiles edits before the Pro's first apply (D1)

Keep every Air entry while both machines are live. If `[fleet.nb-macbook-air]`
or `nb-macbook-air` in `op-vault` were removed, the Air's next apply would
abort at `.pi/agent/mcp.json`, by the same mechanism as Q3.

1. **`.chezmoidata/fleet.toml`**: add the Pro's entry.
   ```toml
   [fleet.nb-macbook-pro]
   user = "nathan"
   lan = false                     # true once Podhaus has a UniFi reservation + split-DNS record for it
   mdns_host = "nb-macbook-pro.local"
   host_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIO9kCdfWWKkCjHGss6J40w5VOUZuEHX/hYswV/64tLxA"
   devbox = false
   development = true
   switch_development = true
   podhaus_operator = false        # true at cutover; false keeps the docs tunnel off (Q5)
   oom_order = false
   parked = false
   ```
   Why `mdns_host` rather than `lan = true`: with `lan = true` the direct
   route probes `nb-macbook-pro.pod.haus`. That name does not exist until
   Podhaus adds a record (`terraform/unifi.tf`,
   `terraform/dns_unifi_split_horizon.tf`). The `mdns_host` form, which is
   Voltaire's pattern (`private_00-chezmoi.conf.tmpl:70-84`), works today
   with no Terraform. The other form is harmless, but it does not work until
   that record exists.
2. **`.chezmoitemplates/lumen-enabled:1`**: change
   `(eq .chezmoi.hostname "nb-macbook-air")` to
   `(has .chezmoi.hostname (list "nb-macbook-air" "nb-macbook-pro"))`.
   Without this change, the Pro loses Lumen, its skills and the Lumen MCP
   entries, and `.claude-switch/.claude.json` stops being managed.
   (Rendered ignore-list difference: `scratchpad/ignore-pro.txt`.)
3. **`.chezmoitemplates/switch-vault-enabled:2`**: add `"nb-macbook-pro"` to
   the list. Without it, Switch Claude loses `influxdb-haultruck`.
4. **`dot_local/bin/executable_op-vault:54`**: add
   `nb-macbook-pro:dev|nb-macbook-pro:switch` to the file-backend case.
   This is required. Without it every apply aborts.
5. **`dot_local/bin/executable_docs-tunnel-update:28-29`**: no change is
   needed before the first apply, because `podhaus_operator = false` leaves
   the tunnel out on the Pro (`.chezmoiignore:49-54`). At cutover, Nathan
   decides one of two things:
   - keep the certificate fields named `nb-macbook-air_cert_b64` /
     `_key_b64`. The Pro then publishes the docs as "nb-macbook-air", and
     nothing changes in Podhaus; or
   - rename the docs-tunnel client in Podhaus
     (`terraform/tunnel.tf:17`, `tunnel/numbat/restrictions.yaml:10-13`)
     and derive the labels from `uname -n` here.
6. **`dot_claude/commands/ssh.md:73`**: change "Plain `ssh` on nb-macbook-air"
   to "on the MacBook". Wording only.
7. **SSH access between the two Macs. A decision for Nathan; recommended.**
   - The problem: the Pro's `~/.ssh/authorized_keys` currently holds only
     the shared machine key (`SHA256:s5qV…`). That key is how this session
     reaches the Pro. `private_dot_ssh/private_authorized_keys.tmpl:5-11`
     renders only the personal key and the *devbox* machine keys.
   - What happens: the Pro's first apply silently replaces that file. I
     tested that a file chezmoi has never written is overwritten without a
     prompt. **SSH from the Air with the machine key then stops working.**
     Only the 1Password personal key, and agents on the devboxes, can get
     in.
   - sshd on the Pro reads only `.ssh/authorized_keys`
     (`/etc/ssh/sshd_config:50`), so a side file cannot be used.
   - Recommended fix: add `machine_key = "<the shared ed25519 key>"` to
     `[fleet.nb-macbook-air]`. Change the template to grant every fleet
     host's `machine_key` except this host's own. Keep the check that a
     devbox must have one.
   - Result: the Pro grants the Air's key and the Air grants the Pro's.
     Since the key is shared, that means both directions, which is useful
     for copying state. The grant disappears by itself when the Air entry
     is deleted at cutover.
   - Update `tests/test_macbook_access.py:22-26` to match.
   - Alternative: accept losing headless access after step H7, and re-enter
     from the Air through 1Password, or through a devbox's machine key.
8. **Tests.** `tests/op-vault.sh:143-152` could assert that `nb-macbook-pro`
   gets the file backend, which is behaviour this change adds. The other
   `nb-macbook-air` references in the tests use that name only as a sample
   darwin host and need no change. These are `test_pi_mcp.py:10`,
   `test_lumen.py:167`, `test_agent_hooks.py:68` and
   `test_docs_tunnel.py:70-71,130-134`.

**What other hosts see when a second Mac that is not a devbox is added.**
Only two templates loop over the whole fleet and reach non-devbox hosts:

- `~/.ssh/config.d/00-chezmoi.conf` gains direct-route and Pomerium-route
  blocks for `nb-macbook-pro` (`private_00-chezmoi.conf.tmpl:69-115`). This
  happens on every host: the Air and all the Linux hosts.
- `~/.ssh/known_hosts.podhaus` gains a pinned line for
  `nb-macbook-pro.pod.haus` (`private_known_hosts.podhaus.tmpl:19-26`).
  This also happens on every host.

The other fleet-wide outputs are filtered to devboxes, so a non-devbox entry
changes none of them:

- the Mac's `authorized_keys` (`:7`), unless edit 7 above is made;
- the cc-clip tunnel host lists (`private_00-chezmoi.conf.tmpl:154-171`,
  `run_onchange_after_11…:10`, `__ccclip_nudge.fish.tmpl:13`);
- the Herdr machine list (`run_after_16…:9`).

Nothing else from `fleet.toml` reaches Linux hosts. The other lookups read
only the host's own entry. Podhaus Ansible grants the shared key on the
Linux hosts, and that key is unchanged.

## Q5. Conflicts while both Macs run

| Service | What happens if the Pro starts it while the Air runs | Action |
|---|---|---|
| Docs tunnel (`com.podhaus.docs-tunnel` and `-origin`) | Both clients would present the same certificate, whose common name is `nb-macbook-air` (`docs-tunnel-update:28-29`). Both would ask Numbat for a reverse listener on `127.0.0.1:8449`, and Numbat allows that name to (`restrictions.yaml:10-21`). Either the second bind fails and keeps retrying (KeepAlive), or wstunnel hands incoming connections to both clients. Then `mac.docs.pod.haus` would sometimes be served by a half-built Pro. I did not test which of the two happens. | **Defer.** Use `podhaus_operator = false` on the Pro (Q4 edit 1), which keeps the files and scripts 22/23 out. At cutover, on the Air run `launchctl bootout gui/501/com.podhaus.docs-tunnel` and `…docs-origin`. Then set the Pro's flag to true and apply. |
| Docs server (`com.podhaus.docs-server`, `127.0.0.1:8765`) | Loopback only, a separate copy on each machine. | Fine to run. |
| cc-clip | Each Mac's daemon has its own `~/.cache/cc-clip/session.token`. `cc-clip setup <host> --all` copies that token to the devbox; cc-clip has a `connect --token-only` option for exactly that sync. The Pro's first apply would also stop and restart each devbox's clipboard services (`run_onchange_after_11…:17-31`). With different tokens, **the Air's image paste on every devbox fails** until the Air runs setup again. The remote port 18339 goes to whichever SSH session binds first. That is only a warning (`private_00-chezmoi.conf.tmpl:149-153`). | Copy the Air's `session.token` and `cc-clip` binary to the Pro before the apply (step H3). Both Macs then share one token and one version. Expect a short blip while the devbox services restart. |
| Herdr | Not installed by chezmoi. `hc` comes from Herdr.app (`~/.local/bin/hc` → `~/.local/share/herdr-core/…`). Once `hc` exists, `run_after_16…:22-23` runs `hc machine add --install` on every devbox, which installs or replaces `herdr-core` there. A Pro with a different Herdr version would swap the devboxes' `herdr-core` underneath the Air's connections. I did not verify whether two Macs can attach to one devbox `herdr-core`. | **Defer:** do not install Herdr.app on the Pro until cutover. Without it, script 16 only prints which machines are not linked. `herdr-install` (script 24) only clones the Herdr config repository into `~/.config/herdr-app`, which is harmless. |
| Ollama / Lumen | Loopback `127.0.0.1:11434`, with a separate index and model on each machine (`lumen-install-macos:9,32,42`). | Fine to run. The first apply downloads the model. |
| Syncthing | Not managed by chezmoi. The Air runs it through `brew services` (`~/Library/LaunchAgents/homebrew.mxcl.syncthing.plist`). | The Pro gets nothing from the apply. Do not copy the Air's Syncthing keys (`~/Library/Application Support/Syncthing`); two devices with one ID conflict. Give the Pro its own device, or move the keys at cutover with the Air's Syncthing stopped. |
| Git commit signing / Forgejo / GitHub | One shared key that is already registered. Each machine writes its own `~/.ssh/id_<host>.pub` and `allowed_signers` (`run_onchange_05…:130-146`). | No conflict. |

## Q6. op-vault tokens

They can be copied as they are.

- `op-vault` takes the hostname only to choose where the token is stored
  (`:49-66`). The token file holds just the `ops_…` service-account token,
  read from the first line (`:76-88`). Nothing ties it to a machine.
- The checks are that the file exists, that its mode is exactly 600 (`:79`),
  and that the token starts with `ops_`.
- The host appears only in `mint`'s temporary probe-item name (`:153`).
- Running `op-vault mint` again is unnecessary. It also contradicts the
  "keys move, not minted" decision.
- Required first: the `op-vault` edit (Q4 edit 4). The dev token is needed;
  the switch token is needed because `switch_development = true`.
- Side effect: both machines draw on the same service accounts' request
  quotas while both are live.
- Copy method (step H2): piped from the Air, never printed, written under
  `umask 077`.

## Q7. Logins after the apply, and what can be copied from the Air

| Item | Where the Air keeps it | Can it be copied? | How on the Pro |
|---|---|---|---|
| `gh` | macOS Keychain (`gh auth status` says "(keyring)"; `hosts.yml` has no token). | Not as a file. It can be piped without printing: Air `gh auth token` → Pro `gh auth login --with-token`. | The pipe (headless), or `gh auth login --web`, where Nathan enters a device code. |
| Codex | `~/.codex/auth.json` (a file, mode 600). | Copyable, but ChatGPT refresh tokens rotate. If both Macs share one, one of them is likely to be logged out when the other refreshes. | `codex login --device-auth` on the Pro (device code; Nathan approves in a browser). |
| Codex hook trust | `[hooks.state]` `trusted_hash` entries in `~/.codex/config.toml:143-152`, keyed by path and hook content. | Copyable in principle, but trivial to redo. | Start `codex` once and choose "Trust all and continue". |
| Claude Code (personal and Switch accounts) | Keychain: `Claude Code-credentials` and `Claude Code-credentials-<hash>` entries. There is no `.credentials.json` file. | No. | Claude Code itself is **not installed by chezmoi on macOS** (the install is Linux-only, `04-packages:347-357`). Install it with `curl -fsSL https://claude.ai/install.sh \| bash` (headless), then `/login` in each account. |
| Notion MCP OAuth | Each client's own store; Claude keeps it in the Keychain. | No. | `/mcp` in each Claude account, `codex mcp login notion` and `pi mcp login notion` (`README.md:77-79`). Each needs a browser. |
| Forgejo `fj` | — | — | Automatic through `op-vault` (`run_always_06-fj-auth`). |
| Herdr | App home `~/.config/herdr-app` is a git checkout made by `herdr-install`. Machine links come from script 16. | Nothing to copy. | Install Herdr.app at cutover. The next apply links the devboxes. |
| OrbStack first run | — | — | GUI. It asks for an admin password for its helper. |
| Adrafinil helper | — | — | GUI: open the app and approve it under System Settings → Login Items & Extensions. |
| 1Password app, SSH agent | — | — | GUI: install with `brew install --cask 1password` (headless), then sign in and turn on Settings → Developer → SSH agent. Then step H8. |
| Ghostty | Not installed by chezmoi (`macbook-setup.md:23`). | — | `brew install --cask ghostty` (headless). |
| fish as login shell | — | — | `/etc/shells` (sudo) and `chsh` (step N4). |

## Needs Nathan at the keyboard or sudo (on the Pro)

Before step H1:
```sh
sudo scutil --set HostName nb-macbook-pro
# optional, cosmetic:
sudo scutil --set LocalHostName nb-macbook-pro
sudo scutil --set ComputerName nb-macbook-pro

/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"   # also installs the Command Line Tools

printf '%s\n' 'auth       sufficient     pam_tid.so' | sudo tee /etc/pam.d/sudo_local >/dev/null
sudo chown root:wheel /etc/pam.d/sudo_local
sudo chmod 444 /etc/pam.d/sudo_local

sudo tee /etc/ssh/sshd_config.d/000-key-only.conf >/dev/null <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
AllowUsers nathan
EOF
sudo sshd -t
```

A note on the sshd drop-in: today the Pro has no `000-key-only.conf`, so it
accepts the account password over SSH. Remote Login is already on, since SSH
works. Once the drop-in exists, the Pro accepts only the keys in
`authorized_keys`. The Pro's first apply rewrites that file (see Q4 edit 7),
so either make edit 7 first, or keep 1Password on the Air as the way back in.

After step H7:
```sh
echo /opt/homebrew/bin/fish | sudo tee -a /etc/shells
chsh -s /opt/homebrew/bin/fish
```

In the GUI:
- 1Password: install, sign in, turn on the SSH agent.
- OrbStack: open once and approve its helper.
- Adrafinil: open once and approve its helper.
- Start `codex` once and trust its hooks.
- `/login` in Claude, for the personal and Switch accounts.
- Notion OAuth for each client.
- Device codes for `gh` and Codex, if they are not piped.
- At cutover: install Herdr.app.
- Any first-launch prompts from Gatekeeper or the clipboard-privacy setting
  as apps start. I did not see one, but macOS 27 may ask when the cc-clip
  daemon first reads the clipboard.

## Should Nathan add a temporary passwordless sudo entry?

**Recommendation: no.** The root steps are the five command groups above,
and all of them happen before or right after the apply. Nathan is already at
the Pro for the 1Password sign-in and the helper approvals, so one sitting
covers everything.

What a `nathan ALL=(ALL) NOPASSWD: ALL` file in `/etc/sudoers.d/` would
unblock:
- the Homebrew install, including the Command Line Tools, run headlessly
  with `NONINTERACTIVE=1`;
- `scutil`, `sudo_local`, the sshd drop-in and `/etc/shells`;
- `sudo chsh -s … nathan`;
- the `07-sudo-touch-id` script inside the apply.

What it does not unblock:
- any GUI step: the 1Password sign-in and agent toggle, the OrbStack and
  Adrafinil helper approvals, Gatekeeper and privacy prompts;
- the browser or device-code logins: gh, Codex, Claude, Notion;
- the console login that the GUI-session `launchctl` calls need.

The cost: every process running as nathan becomes root for the duration.
That includes any agent session and any `curl | sh` installer.

If Nathan wants the whole thing hands-off anyway:
- install the entry with `visudo -f /etc/sudoers.d/zz-bootstrap`;
- after step H7, remove it with `sudo rm /etc/sudoers.d/zz-bootstrap`;
- check that it is gone with `sudo -k; sudo -n true` failing.

## Appendix: headless commands (run from the Air)

`PRO='nathan@nb-macbook-pro.local'`; `SM=~/.local/bin/ssh-machine`.

```sh
# H1 known_hosts (public keys only)
grep -o 'git.pod.haus ssh-rsa [A-Za-z0-9+/=]*' ~/.local/share/chezmoi/run_onchange_00-ssh-hostkeys.sh.tmpl \
  | $SM $PRO 'umask 077; cat >> ~/.ssh/known_hosts'
grep '^ssh.pod.haus ' ~/.ssh/known_hosts | $SM $PRO 'cat >> ~/.ssh/known_hosts'
$SM $PRO 'ssh-keyscan github.com >> ~/.ssh/known_hosts 2>/dev/null'

# H2 op-vault tokens (never printed)
for id in dev switch; do
  $SM $PRO "umask 077; mkdir -p ~/.local/state/op-vault && cat > ~/.local/state/op-vault/$id.token" \
    < ~/.local/state/op-vault/$id.token
done

# H3 cc-clip binary and shared token
$SM $PRO 'mkdir -p ~/.local/bin && cat > ~/.local/bin/cc-clip && chmod 755 ~/.local/bin/cc-clip' < ~/.local/bin/cc-clip
$SM $PRO 'umask 077; mkdir -p ~/.cache/cc-clip && cat > ~/.cache/cc-clip/session.token' < ~/.cache/cc-clip/session.token

# H4-H7 on the Pro
$SM $PRO 'export PATH="$HOME/.local/bin:$HOME/.local/share/mise/shims:$HOME/.cargo/bin:/opt/homebrew/bin:/opt/homebrew/sbin:$PATH"
  brew install chezmoi node && brew install --cask 1password-cli
  mkdir -p ~/.ssh/config.d && printf "Host *\n    IdentityFile ~/.ssh/id_nb-macbook-pro\n" > ~/.ssh/config.d/90-bootstrap.conf
  GIT_SSH_COMMAND="ssh -i ~/.ssh/id_nb-macbook-pro -o IdentitiesOnly=yes -o IdentityAgent=none" \
    chezmoi init --promptBool headless=false --promptString podhausLan=auto git@git.pod.haus:LogicWolfe/dotfiles.git
  chezmoi apply'
```

Before running H4-H7, check that `uname -n` on the Pro prints
`nb-macbook-pro` and that `op-vault dev -- op whoami` succeeds. The second
check needs `op` and the edited `op-vault`, so run it after `chezmoi init`
through the source copy:
`sh ~/.local/share/chezmoi/dot_local/bin/executable_op-vault dev -- op whoami`.

After H8, verify:
- `ssh-machine -T git@git.pod.haus` authenticates as LogicWolfe;
- `chezmoi status` lists only the scripts that run on every apply;
- `docs-url` prints a working localhost link.
