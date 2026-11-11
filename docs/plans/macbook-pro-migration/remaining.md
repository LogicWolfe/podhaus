# MacBook Pro migration: what is left

Stage E of the [migration plan](../macbook-pro-migration.md) is complete. On
the evening of 2026-11-09 four read-only audits compared the Air and the Pro
side by side (applications and tooling, macOS settings, home-directory state,
repositories and running agents). Everything mechanical that the audits
turned up has been done; this page is the breakdown of what remains, grouped
by who acts. When an item lands, mark it ✅ and rewrite it as what was done.
When the Pro is Nathan's daily machine, stage F follows, then G, and this page
goes with the plan.

## Done by the agent in the audit pass

- **1Password SSH agent in place.** `chezmoi init` and `chezmoi apply` ran
  once the socket existed; fish exports the agent socket, the fleet SSH
  config names it as `IdentityAgent`, and the bootstrap identity file
  `~/.ssh/config.d/90-bootstrap.conf` is gone. bilby accepts the Personal
  SSH Key over plain `ssh`.
- **Firefox profiles verified.** The staged folder is gone and Firefox is
  the registered http and https handler.
- **Copied from the Air:** the six user fonts in `~/Library/Fonts` (Red Hat
  Mono, Roboto Flex, Source Sans 3), the `~/.local/bin/lunar` wrapper,
  `~/.config/git/ignore`, the three cull bundles in `~/Archive/git-bundles`
  (including the only copy of wattsworth's `docs-timesheets-reorg`), the two
  Orijin-Platform repositories whose remote is dead, and the Air's 368 Claude
  Code transcripts under `~/.claude/projects` (the Pro's own were kept).
- **Repositories:** the `upstream` remote on `terraform-provider-railway`
  and the `github` remote on `Writing` re-added.
- **Claude Code settings:** the nine preference keys the Air carried outside
  the chezmoi template (`model`, `effortLevel`, `tui`, `autoMode`,
  `permissions`, `env`, `modelSettings`, `agentPushNotifEnabled`,
  `skipAutoPermissionPrompt`) merged into the Pro's `~/.claude/settings.json`;
  the template's deep-merge keeps them across applies.
- **Settings:** output volume matched to the Air; three-finger vertical swipe
  on an external trackpad matched.
- **Clipboard bridge on bandicoot fixed.** cc-clip is the bridge that puts a
  devbox's clipboard (and Codex's Ctrl-V images) onto the Mac through a
  reverse SSH tunnel on port 18339. On bandicoot SELinux refused to let sshd
  listen on that port; the podhaus devbox role has a task that labels the
  port for sshd and it had never run there. Ran that one task
  (`ansible-playbook playbooks/bandicoot.yml --tags clipboard-tunnel`, check
  mode first, one change) and `cc-clip setup bandicoot.pod.haus --all` now
  completes. voltaire and fractal get the same label the next time their
  playbooks run.
- **wattsworth's Air-only commit is on the Pro.** The branch
  `docs-timesheets-reorg` (one commit, 2026-04-22, moving the timesheets docs
  from `docs/plans/` into a `docs/timesheets.md` reference page and a
  `timesheets-next.md` plan) was fetched from the cull bundle into
  `~/repos/wattsworth`. It is not pushed; see decisions.
- **Home state:** the two SQLite guidance PDFs sitting loose in the Air's home
  folder copied; the Air's 77 SSH known-hosts entries merged into the Pro's
  file (the previous file is kept as `known_hosts.pre-merge`). The audit
  confirmed Documents, Desktop, Pictures and `~/Archive` match the Air to the
  kilobyte and all 30 items of the small-state copy list are present.

## Nathan at the keyboard, one sitting

Everything here needs a click, a password, a licence or an account. Order
does not matter except where noted.

### Approvals that unblock the agent and the shell

| Item | Why it matters |
|---|---|
| ✅ 1Password SSH key-use approval | Plain `ssh bilby.pod.haus` now signs with the Personal SSH Key and returns |
| System Settings, Login Items: Stay, Lunar, Adrafinil, Magnet (NordVPN, Magnet and Adrafinil are already there) | Registering through System Events raised an Automation prompt nobody could click |
| System Settings, Spotlight: switch off every category except Applications, Folders and System Settings, then run `defaults read com.apple.Spotlight EnabledPreferenceRules` and paste the array into the MacBook setup doc | Fourteen category ids are written; the ids for Mail and Messages, Events, Fonts, Bookmarks, Siri Suggestions, Websites and Conversion only appear once toggled in the GUI |
| Lock screen: require password immediately (`sysadminctl -screenLock immediate -password -`, or System Settings, Lock Screen) | The Pro waits 300 seconds; the Air was immediate |
| System Settings, Keyboard, Dictation: download offline English (US) dictation | The Air had it; the Pro has none |

### Licences, sign-ins and first launches

Nathan does these as each app is first needed; none blocks anything else.
iStat Menus (licence is in the copied plist; align the menu-bar items with
the Air), Lunar, Stay, Magnet, DaisyDisk, NordVPN, Tailscale (`tailscale up`),
Syncthing (pair the Pro and add the "Leftover Words" folder at
`~/Documents/Publii/sites/leftover-words`; never copy the Air's `key.pem`),
OneDrive and iCloud Drive, the chat apps, Plex, Steam, Microsoft 365, Orion,
Brave sync, StreamFab, the Safari extensions, the four iPhone apps from
the App Store, Claude Code `/login` for the Switch account and `/mcp` for
Notion.

### Appearance and small GUI-only settings

Wallpaper ("The Beach" on the Air), Night Shift, True Tone, Finder sidebar,
Siri in the Dock (the Air has it between iPhone Mirroring and System
Settings), and the PA32QCV monitor's colour profile when that display is
next plugged in.

## Decisions for Nathan

| Decision | Options and trade-off |
|---|---|
| iCloud Drive Desktop and Documents sync: **on, like the Air** (decided) | The Air's Desktop and Documents are the iCloud ones, so everything the Pro copied is already in iCloud. When a second Mac turns the sync on with files already in its local Desktop and Documents, macOS does not merge them: it files them under `Desktop - nb-macbook-pro` and `Documents - nb-macbook-pro` inside iCloud, so the Pro would upload 33 GB of duplicates. Sequence: the agent moves the Pro's local `~/Desktop` and `~/Documents` contents aside to `~/Air-copies/`; Nathan turns the switch on (System Settings, Apple Account, iCloud, iCloud Drive, Desktop & Documents Folders); iCloud fills the folders; the agent compares and deletes `~/Air-copies/` |
| The two Orijin-Platform repositories | `Orijin-Platform-Backend` and `-Frontend` are old client work whose GitHub remote, the `orijin-plus` organisation, no longer exists (clones are refused). Their full history is now on the Pro, so nothing is lost. Nothing to do unless the org was renamed and you want to repoint them with `git remote set-url` |
| wattsworth `docs-timesheets-reorg` | The branch is now in the Pro's clone. Push it to origin so it survives the Air (`git -C ~/repos/wattsworth push origin docs-timesheets-reorg`) or drop it if the timesheets docs reorganisation is no longer wanted |
| Graphite (`gt`) and Bun | Both on the Air as tapped formulae with no Keep or Drop row. `brew install withgraphite/tap/graphite`, `brew install oven-sh/bun/bun`, or treat as dropped |
| Bartender 6 | On the Air, not installed on the Pro, no decision recorded. The native menu bar settings already match; install it or drop it |
| `~/.cursor/hooks.json` | Seed it in chezmoi with only Adrafinil's entries, or leave the app to write it; it still carries retired CodeIsland entries |
| Codex sessions | `~/.codex/sessions` (443 MB) exists only on the Air. Codex is skipped on the Pro; copy it only if you want to resume those threads |
| Switch work Claude profile | `~/.claude-switch` is 92 MB on the Air (86 MB of transcripts) and 4 KB on the Pro; the state inventory said memory only, and the copy script carried none of it. Copy `~/.claude-switch/projects` the way the personal transcripts were copied, or start that profile fresh |
| Mail, Messages, Safari | Mail (461 MB) and Messages (227 MB database plus 7 GB of attachments) exist on the Air and are privacy-protected on both machines. iCloud brings Safari bookmarks and Messages back; Mail re-syncs from the accounts. Copying `chat.db` by hand fights iCloud sync, so the recommendation is to rely on the accounts and only export anything not in iCloud |
| Dropped apps' data | CrossOver bottles (4.9 GB), VS Code (2 GB), Conductor (`conductor.db`), Alfred, MailMate, IINA, Goose, iTerm2 remain on the Air only. Nothing to do unless an app comes back; the Air's disk is the archive until stage G |
| Dotfiles review | Package script change `8ffcd6d` (desktop formulae and casks in the non-headless branch) if wanted |
| Komodo variable `LAN_NB_MACBOOK_AIR_IPV4` | Lingers in Komodo because the sync is additive. Delete it in the Komodo UI (Variables); the API's local login refused the agent, so it is a click |
| git's SSH on the Mac and 1Password | The git config's Mac branch (`ssh -i <machine key>`, deliberately without `IdentitiesOnly`, per Nathan's 2026-08 ruling so the personal key is a fallback) consults the 1Password agent first, because OpenSSH offers agent keys before file keys. Once the key-use prompt is approved with "always allow" it is instant; before that every git contact waited a minute. Keep the ruling, or add `-o IdentityAgent=none` and give up the personal-key fallback for git |
| `gh` scope | The Pro's `gh` login lacks `admin:repo_hook`, so a webhook cannot be redelivered from here. `gh auth refresh -h github.com -s admin:repo_hook` if wanted |

## Closed after the cutover

- ✅ Stages F and G completed; the Air was erased. The MacBook Pro,
  bandicoot, bilby, fractal and voltaire all applied dotfiles `26e0fa3` on
  2026-11-11. All 20 directed Herdr connections worked, and the native
  deployment and maintenance jobs passed. Catch-up runs independently of
  interactive login; Quokka remains parked and excluded. See
  [development environment deployment](../../host-provisioning.md#development-environment-deployment).
- `config.fish` tests for Homebrew by path, so a non-interactive fish over
  SSH no longer fails on starship (dotfiles `94d871b`).
- The MacBook setup page carries the lessons: Full Disk Access and Local
  Network before an agent starts, iCloud sync before copying, the Spotlight
  array, the 1Password approval, the Podhaus clone's hook and venv, and the
  Pomerium-separate push for the cutover rule.

## Stages F and G, as they were run

Stage F (cutover) starts when Nathan says the Pro is good for daily work. It
is unchanged in the plan: stop the docs tunnel and origin agents on the Air,
move the Numbat listener 8449 rule to `nb-macbook-pro`, set
`podhaus_operator = true` on the Pro's fleet entry and apply, copy Herdr's
`shared.json` layout from the Air, and check `nb-macbook-pro.pod.haus`
resolves and a devbox can SSH to it. The Air still runs one Claude Code
session, several Herdr terminals with Codex and Claude agents, and the Codex
app-server; they end when the Air shuts down and nothing in them is
uncommitted (every Air repo is clean with zero stashes and zero unpushed
commits). Stage G (retire the Air) follows F.

## Improvements surfaced by the audit

- ✅ The Mac's editable chezmoi checkout now has a repository-local
  `core.sshCommand` pointing to `~/.local/bin/ssh-machine`. Native deployment
  completed through launchd with exit 0. Background dotfiles fetches no longer
  depend on the interactive 1Password agent. The separate decision about
  changing Git authentication for all other Mac repositories remains above.
- rsync 3.5 treats a quoted multi-path remote argument as one path; the copy
  scripts should pass one `host:path` argument per source.
- `mas` was never installed on the Air, so its App Store list had to be
  inferred from `/Applications`; the desktop package list now installs it.
- The settings audit's `plutil` JSON conversion fails on `data` and `date`
  plist values; `plistlib` in Python works for diffing preference domains.
