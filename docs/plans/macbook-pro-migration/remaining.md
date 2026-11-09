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
| 1Password: approve the SSH key-use prompts for `ssh` (tick "remember"/always allow) | Until then every plain `ssh`, and git's first contact through the 1Password agent, waits on the dialog; a `git pull` waited a minute before falling back to the machine key |
| System Settings, Login Items: Stay, Lunar, Adrafinil, Magnet (NordVPN, Magnet and Adrafinil are already there) | Registering through System Events raised an Automation prompt nobody could click |
| System Settings, Spotlight: switch off every category except Applications, Folders and System Settings, then run `defaults read com.apple.Spotlight EnabledPreferenceRules` and paste the array into the MacBook setup doc | Fourteen category ids are written; the ids for Mail and Messages, Events, Fonts, Bookmarks, Siri Suggestions, Websites and Conversion only appear once toggled in the GUI |
| Lock screen: require password immediately (`sysadminctl -screenLock immediate -password -`, or System Settings, Lock Screen) | The Pro waits 300 seconds; the Air was immediate |
| System Settings, Keyboard, Dictation: download offline English (US) dictation | The Air had it; the Pro has none |

### Licences, sign-ins and first launches

| App | What to do |
|---|---|
| iStat Menus | Launch, approve the helper, check the licence (the four plists are in place), then align the menu-bar item visibility with the Air: Battery, CPU, Memory, Network differ in the stored state |
| Lunar | Licence (Paddle), Screen Recording and Accessibility; display settings are machine-specific so set them fresh |
| Stay | Accessibility and Screen Recording; the Air's saved window layouts live in its plist and were not copied (they are display-specific) |
| Magnet | Accessibility |
| DaisyDisk | Full Disk Access |
| NordVPN | Network extension approval |
| Tailscale | `tailscale up` and the browser sign-in; the Pro reports `NeedsLogin` under node name `nb-macbook-pro` |
| Syncthing | Pair the Pro with the Air (or the other devices) in the Syncthing UI and add the "Leftover Words" folder at `~/Documents/Publii/sites/leftover-words`, which the Documents copy already placed; the Pro's Syncthing has no folders and no peers. Do not copy the Air's `key.pem`: two devices would share one ID |
| OneDrive, iCloud Drive | Sign in; OneDrive-Personal (1.5 GB) and the Switch Technologies libraries live in `~/Library/CloudStorage` on the Air and repopulate on sign-in, as do iCloud Drive (603 MB), Books, Pixelmator, Playgrounds and Ulysses's library |
| Claude desktop, ChatGPT, Slack, Signal, WhatsApp | Sign in; Signal and WhatsApp are device links from the phone |
| Plex, Steam | Sign in; Steam games (Caves of Qud, Pathogenic, Slay the Spire 2 were in the Air's `~/Applications`) redownload |
| Microsoft 365 (Word, Excel, PowerPoint, Outlook, OneDrive, To Do, Teams) | Sign in |
| Orion (Kagi), Brave sync | Sign in |
| StreamFab | Direct download from streamfab.com and licence entry (activation count is limited) |
| Zed | First launch; see the Zed decision below for the settings |
| Safari | Enable the 1Password, Kagi, Consent-O-Matic and Hush extensions |
| App Store | Install the iPhone apps Audible, Big Ass Fans, Sensibo, MacroFactor (`mas` cannot) |
| Claude Code | `claude-switch` then `/login` if the Switch account is missing; `/mcp` Notion OAuth in each account |

### Appearance and small GUI-only settings

Wallpaper ("The Beach" on the Air), Night Shift, True Tone, Finder sidebar,
Siri in the Dock (the Air has it between iPhone Mirroring and System
Settings), and the PA32QCV monitor's colour profile when that display is
next plugged in.

## Decisions for Nathan

| Decision | Options and trade-off |
|---|---|
| iCloud Drive Desktop and Documents sync | The Air has it on; the Pro is off and `~/Desktop` and `~/Documents` are the local copies from the Air. Turning it on merges those into iCloud Drive. Turn it on in System Settings, Apple Account, iCloud, iCloud Drive, after checking the Pro's folders are what you expect; or leave it off and treat the Pro's copies as the truth |
| The two Orijin-Platform repositories | Working copies are now on the Pro with history, but `github.com/orijin-plus` is dead. Point them at the renamed org (`git remote set-url`), or leave them as local archives |
| wattsworth `docs-timesheets-reorg` | One commit (`48f8b03`) exists only on the Air and in the copied bundle. Push the branch (`git push origin docs-timesheets-reorg`, publishes it) or rely on the bundle |
| Air worktrees not recreated | Eight clean extra checkouts on the Air with nothing unpushed: `bookshelf-audible-purchase` (`audible-purchase`, no upstream), `hybrid-haul-truck-agent-dependencies` and `-agent-telemetry` (remote branches gone), `hybrid-haul-truck-notion-plan` (detached), `hybrid-haul-truck-workbook-fixes` (`plan-workbook-smoke-follow-ups`), `indy-board-button-order`, `podhaus-visual-test` (`visual-test`, no upstream), `terraform-sandbox-runner-auth`. Recreate any you still want with `git -C ~/repos/<repo> worktree add ~/repos/<dir> <branch>`; the two with no upstream exist only on the Air |
| Graphite (`gt`) and Bun | Both on the Air as tapped formulae with no Keep or Drop row. `brew install withgraphite/tap/graphite`, `brew install oven-sh/bun/bun`, or treat as dropped |
| Bartender 6 | On the Air, not installed on the Pro, no decision recorded. The native menu bar settings already match; install it or drop it |
| Zed settings | The Air's `~/.config/zed/settings.json` carries theme, font sizes, unified diff view, new-window CLI behaviour, agent model and permissions and the `codex-acp` registry entry that the chezmoi-managed file lacks, plus a `keymap.json`. Fold them into the dotfiles source (a plain copy is overwritten on the next apply) or start fresh |
| `~/.cursor/hooks.json` | Seed it in chezmoi with only Adrafinil's entries, or leave the app to write it; it still carries retired CodeIsland entries |
| Codex sessions | `~/.codex/sessions` (443 MB) exists only on the Air. Codex is skipped on the Pro; copy it only if you want to resume those threads |
| Switch work Claude profile | `~/.claude-switch` is 92 MB on the Air (86 MB of transcripts) and 4 KB on the Pro; the state inventory said memory only, and the copy script carried none of it. Copy `~/.claude-switch/projects` the way the personal transcripts were copied, or start that profile fresh |
| pi agent extras | The Air's `~/.pi/agent` has `auth.json` (a login), `models-store.json` and 7 MB of sessions that the Pro lacks; settings, MCP and extensions were copied. Sign in again, or copy `models-store.json` and the sessions |
| OrbStack dev containers | The Air has four stopped containers (postgres 17 and mongo 7 for hybrid-sim, a chat-investor sandbox, redis), unused for months. The plan says rebuild; the two databases may hold data worth a `pg_dump`/`mongodump` before the Air is wiped |
| Mail, Messages, Safari | Mail (461 MB) and Messages (227 MB database plus 7 GB of attachments) exist on the Air and are privacy-protected on both machines. iCloud brings Safari bookmarks and Messages back; Mail re-syncs from the accounts. Copying `chat.db` by hand fights iCloud sync, so the recommendation is to rely on the accounts and only export anything not in iCloud |
| Dropped apps' data | CrossOver bottles (4.9 GB), VS Code (2 GB), Conductor (`conductor.db`), Alfred, MailMate, IINA, Goose, iTerm2 remain on the Air only. Nothing to do unless an app comes back; the Air's disk is the archive until stage G |
| `clipboard-tunnel` Ansible tag | The cc-clip failure on bandicoot is an SELinux port label the devbox role applies; voltaire and fractal are unlabelled too but work. Run the tag on bandicoot alone, or on all three |
| Dotfiles review | Package script change `8ffcd6d` (desktop formulae and casks in the non-headless branch) if wanted |

## Gates to stages F and G

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

- The Mac branch of `core.sshCommand` in the dotfiles git config should set
  `-o IdentityAgent=none -o IdentitiesOnly=yes` like `ssh-machine` does, so
  git never waits on 1Password.
- rsync 3.5 treats a quoted multi-path remote argument as one path; the copy
  scripts should pass one `host:path` argument per source.
- `mas` was never installed on the Air, so its App Store list had to be
  inferred from `/Applications`; the desktop package list now installs it.
- The settings audit's `plutil` JSON conversion fails on `data` and `date`
  plist values; `plistlib` in Python works for diffing preference domains.
