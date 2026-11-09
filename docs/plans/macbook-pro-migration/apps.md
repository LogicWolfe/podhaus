# App and tool inventory: MacBook Air (nb-macbook-air) to MacBook Pro

> Investigation report gathered read-only on 2026-11-09 by a subagent; it feeds [the migration plan](../macbook-pro-migration.md). Where a recommendation here differs from the plan, the plan is authoritative.

Gathered read-only on the Air, 2026-11-09. "Covered" means chezmoi already installs it.

## Findings that change the plan

1. `run_onchange_04-packages.sh.tmpl` is not gated on hostname. Its only gate is the `headless` prompt answer, which is false on a Mac. The Pro gets these automatically on first `chezmoi apply`: formulae fish, git-delta, starship, git-lfs, cloudflared, gh, awscli, micro, tmux, zellij, mise, uutils-coreutils, uutils-findutils, fortune, jq, direnv, azure-cli, wstunnel, caddy; casks 1password-cli, codex, zed, orbstack, adrafinil; rustormy via cargo binstall; the fj CLI. Homebrew itself comes from `run_onchange_02-homebrew`. The mise tool set (node, python, go, terraform, uv and others) comes from `dot_config/mise/config.toml.tmpl`. The only `nb-macbook-air` strings in chezmoi are in `op-vault` (1Password vault selection), `docs-tunnel-update` (per-machine certificate fields) and tests; these need a Pro entry but install nothing.
2. Not installed by chezmoi but installed on the Air: ghostty, block-goose and ngrok (all casks), and 25 Homebrew formulae (listed below). ghostty is the terminal in daily use, so it is the most notable gap.
3. Bartender is a login item but is NOT installed. Only `~/Downloads/Bartender 6.dmg` exists, so the login item is stale. Do not carry it over unless Nathan wants it. The cask `bartender` installs Bartender 7, a paid upgrade from 6.
4. Audible, Big Ass Fans, Sensibo, Spriggy and Runner (bundle `com.sbs.diet`) are iPhone apps running on Apple silicon (bundle holds `Wrapper/` and `WrappedBundle/`). They are App Store only and cannot be installed by cask. `Brave.app` (no bundle id) is a local AppleScript launcher applet, not Brave itself; recreate by hand if wanted. No Setapp apps exist.
5. `mas` is not installed on the Air; it is a Homebrew formula (`mas`) and would have to be added.
6. Hush (a Safari content blocker), Stay and the Microsoft apps have both an App Store build on the Air and a cask. Cask builds can have different licence handling; the App Store builds are tied to the Apple ID.

## Developer tools

| App | Install route | Licence | Settings | Login/permissions | Chezmoi? |
|---|---|---|---|---|---|
| 1Password CLI | cask `1password-cli` | account | none | needs 1Password app integration | Covered |
| Codex CLI | cask `codex` | OpenAI sign-in | `~/.codex` is chezmoi-managed | none | Covered |
| Zed | cask `zed` | free | `dev.zed.Zed` plist; `~/.config/zed` | none | Covered |
| OrbStack | cask `orbstack` | free personal | `dev.kdrag0n.MacVirt` plist; containers/volumes are NOT in the plist | privileged helper (asks for admin in GUI on first run) | Covered |
| Adrafinil | cask `adrafinil` | free | `~/Library/Application Support/Adrafinil/config.json`; plist `glass.kagerou.adrafinil` | login item, helper daemon (needs approval in Login Items & Extensions) | Covered |
| Ghostty | cask `ghostty` | free | config at `~/.config/ghostty` (check chezmoi, else copy); plist `com.mitchellh.ghostty` | none | Add to chezmoi (core terminal) |
| iTerm | cask `iterm2` | free | plist `com.googlecode.iterm2`; `~/Library/Application Support/iTerm2`; plist copy works | none | Personal (probably legacy; confirm still used) |
| Visual Studio Code | cask `visual-studio-code` | free | `~/Library/Application Support/Code` (User/settings.json, keybindings, snippets); extensions in `~/.vscode/extensions`; built-in Settings Sync via GitHub/Microsoft sign-in is the clean route | none | Personal (add to chezmoi if still used) |
| Conductor | cask `conductor` (version differs from Air) | account sign-in | `~/Library/Application Support/com.conductor.app`; plist `com.conductor.app` | none | Add (daily agent tool) |
| Herdr | direct download only (`~/Downloads/Herdr.dmg`; releases at releases.herdr.dev; no cask) | unknown, account | plists `dev.herdr.app`, `herdr-app`; chezmoi already has `run_after_24-herdr-macos` and `run_after_16-herdr-machines-macos` | none known | Handled by chezmoi scripts; app install itself is a gap |
| Goose desktop | cask `block-goose` (Air is 1.38.0, cask 1.57.0) | model provider keys | `~/Library/Application Support/Goose`; plist `com.electron.goose` | none | Personal |
| ngrok | cask `ngrok` | account authtoken in `~/Library/Application Support/ngrok` (copy or re-run `ngrok config add-authtoken`) | same | none | Personal |
| CrossOver | cask `crossover` | licence key / account (not found as a file; re-enter or sign in) | bottles in `~/Library/Application Support/CrossOver/Bottles` (large, copy folder); plist `com.codeweavers.CrossOver`; Steam bottle in `~/Applications/CrossOver/Steam` | none | Personal |
| balenaEtcher | cask `balenaetcher` | free | negligible | needs removable-volume access prompt | Personal |
| Mist | cask `mist` plus formula `mist-cli` | free | plist `com.ninxsoft.mist` | privileged helper `com.ninxsoft.mist.helper` approval | Personal |

### Homebrew formulae on the Air not installed by chezmoi (25)

block-goose-cli, cloc, ddrescue, e2fsprogs, ffmpeg, git-filter-repo, git-machete, libpq, mist-cli, mkvtoolnix, ollama, pandoc, pigz, pngpaste, poppler, rclone, rsync, sapling, sentry-cli, signal-cli, smartmontools, syncthing, tailscale, tesseract, typst.

Recommendation: move into chezmoi's package script: git-filter-repo, git-machete, sapling, libpq, rsync, rclone, sentry-cli, tailscale, pandoc, typst, poppler, tesseract, pngpaste, ffmpeg, cloc, pigz (everyday developer tools). Personal or machine-specific: ollama and syncthing (both run as `brew services`; start with `brew services start`; syncthing config in `~/Library/Application Support/Syncthing` carries the device identity, so copying it makes the Pro look like the Air to peers, prefer a fresh identity and re-pair), mkvtoolnix, ddrescue, smartmontools, e2fsprogs, signal-cli (its account data would need re-linking), block-goose-cli. tailscale runs as a root daemon (`homebrew.mxcl.tailscale`) and needs `sudo brew services start tailscale` plus login in a browser; this cannot be fully headless.

## Menu bar and utilities

| App | Install route | Licence | Settings | Login/permissions | Chezmoi? |
|---|---|---|---|---|---|
| Alfred 5 | cask `alfred` | Powerpack licence file `~/Library/Application Support/Alfred/powerpack.CL9PL254C7.dat` (268 bytes); copy it or re-enter the key from the Alfred account | preferences live in `~/Library/Application Support/Alfred/Alfred.alfredpreferences` (local, no sync folder set; `prefs.json` points at it). Copy that folder, or set Preferences > Advanced > Syncing to a folder both Macs see. Plist `com.runningwithcrayons.Alfred-Preferences` | login item; Accessibility, Full Disk Access if file search is used; Contacts/Calendar if used | Personal |
| iStat Menus 7 | cask `istat-menus` | licence stored in plist `com.bjango.istatmenus.menubar.7` (key `License`) and tied to the account; re-enter the key in the app if the plist is not copied | app has Settings > General > Export Settings (preferred) | login item via helper daemon `com.bjango.istatmenus.daemon` (privileged helper approval); the app also runs launch agents `com.bjango.istatmenus.agent` and `.status` | Personal |
| Lunar | cask `lunar` (Air is 6.x in a Pro build; cask 6.11.3) | Paddle licence files `~/Library/Application Support/Lunar/650170.padl` and `.spadl` plus a Paddle key in plist `fyi.lunar.Lunar`. Paddle licences are bound to activation count, so re-activate in app with the key rather than relying on file copy | plist `fyi.lunar.Lunar` holds per-display settings keyed by display serial, which differ on the Pro's built-in display; copy gives monitor schedules for the external PA32QCV and Studio Display XDR, which is probably what is wanted | login item; Screen Recording and Accessibility prompts; DDC needs no permission | Personal |
| Magnet | App Store only (`com.crowdcafe.windowmagnet`; no cask) | tied to Apple ID purchase | plist `com.crowdcafe.windowmagnet` (copy works) | login item; Accessibility | Personal |
| Stay | cask `stay` (Air has the MAS build) | MAS purchase tied to Apple ID; cask build uses its own licence | `~/Library/Application Support/Stay/Stay.sqlite` (window layouts, per-display so partly stale on a new display); plist `com.cordlessdog.Stay` | login item; Accessibility, Screen Recording | Personal |
| DaisyDisk | cask `daisydisk` | licence FILE `~/Library/Application Support/DaisyDisk/License.DaisyDisk` (352 bytes); copy it | plist `com.daisydiskapp.DaisyDiskStandAlone` | Full Disk Access (GUI grant) | Personal |
| Bartender | NOT installed on the Air (stale login item). cask `bartender` is v7 | Bartender 7 needs a paid upgrade licence from 6 | n/a | Accessibility, Screen Recording | Skip unless wanted |
| Hush | App Store (`se.oblador.Hush`) or cask `hush` | free/App Store | Safari extension; enabled in Safari settings (GUI) | Safari extension toggle | Personal |
| Mouser | direct download (github tombadash/mouser; no cask) | unknown | `~/Library/Application Support/Mouser/config.json` (1 KB; copy works) | likely Accessibility and Input Monitoring | Personal |
| Speedtest | App Store only (`com.ookla.speedtest-macos`) | free | none | none | Personal, skip |
| Transmission | cask `transmission` | free | plist `org.m0k.transmission`; `~/Library/Application Support/Transmission` (torrent list) | none | Personal |
| Parcel | App Store only (`com.mr-brightside.myParcel`) | App Store subscription/purchase | iCloud/account sync | notifications | Personal |
| Moonlight | cask `moonlight` | free | plist `com.moonlight-stream.Moonlight` (paired hosts; copy works, or re-pair) | none | Personal |
| NordVPN | cask `nordvpn` (Air has the MAS build) | account sign-in | account | network extension approval (GUI) | Personal |
| iOS-on-Mac apps: Audible, Big Ass Fans, Sensibo, Spriggy, Runner | App Store only | account sign-ins | none | none | Personal |

## Browsers

| App | Install route | Licence | Settings | Login/permissions | Chezmoi? |
|---|---|---|---|---|---|
| Google Chrome | cask `google-chrome` | free | sign in to Google to sync; `~/Library/Application Support/Google` | none | Personal |
| Brave Browser | cask `brave-browser` | free | `~/Library/Application Support/BraveSoftware`; sync chain code is the clean route; also a Brave PWA plist exists | none | Personal |
| Firefox | cask `firefox` | free | `~/Library/Application Support/Firefox`; Firefox Account sync | none | Personal |
| Orion | cask `orion` | free/Kagi sign-in | `~/Library/Application Support/Orion`; plist `com.kagi.kagimacOS` | none | Personal |
| Safari extensions: 1Password for Safari, Kagi for Safari, Consent-O-Matic, Hush | App Store only (Hush also cask) | Apple ID; Kagi needs a Kagi account | enable each in Safari settings (GUI) | GUI toggle | Personal |
| 1Password (app) | cask `1password` | account and Secret Key (do not copy files; sign in) | vault syncs; chezmoi detects `Group Containers/2BUA8C4S2C.com.1password/t/agent.sock` for the SSH agent, so enable the SSH agent and CLI integration in the app before `chezmoi init` | Accessibility, Full Disk Access optional | Add to chezmoi (every Mac needs it) |

## Communication

| App | Install route | Licence | Settings | Login/permissions | Chezmoi? |
|---|---|---|---|---|---|
| Slack | cask `slack` (Air has MAS build) | workspace sign-in | none to copy | notifications | Personal |
| Signal | cask `signal` | phone link; fresh link, cannot copy account | none | notifications | Personal |
| WhatsApp | cask `whatsapp` (Air has MAS build) | phone link | none | notifications | Personal |
| Fastmail | cask `fastmail` | account | plist `com.fastmail.mac.Fastmail` | notifications | Personal |
| MailMate | cask `mailmate` | licence is not found on disk (not in Application Support or the plist); it comes as a licence file/key by email, so retrieve from the purchase email | `~/Library/Application Support/MailMate` (Identities, Mailboxes, Sources, Submission plists; Database is rebuilt from IMAP); plist `com.freron.MailMate` | Accessibility if used with scripts | Personal |
| ChatGPT / ChatGPT Classic | cask `chatgpt` installs one `ChatGPT.app`; the Air has two (bundles `com.openai.codex` and `com.openai.chat`). Determine which one Nathan still uses; the other is a direct download (`~/Downloads/ChatGPT.dmg`) | OpenAI sign-in | plists `com.openai.chat`, `com.openai.codex` | Screen Recording, Accessibility | Personal |
| Claude | cask `claude` | Anthropic sign-in | `~/Library/Application Support/Claude`; MCP config is chezmoi-managed (`modify_private_dot_claude.json.tmpl`) | Accessibility, Screen Recording (GUI) | Add (every Mac) |

## Media and personal

| App | Install route | Licence | Settings | Login/permissions | Chezmoi? |
|---|---|---|---|---|---|
| IINA | cask `iina` | free | plist `com.colliderli.iina` | none | Personal |
| Plex | cask `plex` | account | sign-in | none | Personal |
| Steam | cask `steam` | account | games in `~/Library/Application Support/Steam` (large; redownload) | none | Personal |
| StreamFab | direct download only (`~/Downloads/StreamFab_7048.dmg`, streamfab.com; no cask) | paid licence tied to account/machine; not found as a file (`Application Support/StreamFab` holds an id folder); likely needs re-activation | plist `com.goland.streamfab.macos` | none | Personal, optional |
| Pixelmator Pro | App Store only | Apple ID purchase | `~/Library/Containers/com.pixelmatorteam.pixelmator.x` and Group Container `4R6749AYRE.com.pixelmator`; custom presets there | none | Personal |
| UlyssesMac | App Store only (no cask) | Ulysses subscription via Apple ID | iCloud library syncs; container `com.ulyssesapp.mac` | iCloud on | Personal |
| Kindle | App Store only | Amazon sign-in | none | none | Personal |
| Publii | cask `publii` | free | `~/Library/Application Support/Publii` (sites; copy folder) | none | Personal |
| Apple apps (GarageBand, iMovie, Keynote, Numbers, Pages) | App Store (free, preinstalled on a new Mac or `mas`) | free | iCloud | none | Skip unless wanted |

## Microsoft and work

| App | Install route | Licence | Settings | Login/permissions | Chezmoi? |
|---|---|---|---|---|---|
| Microsoft Word / Excel / PowerPoint / Outlook | cask `microsoft-word`, `microsoft-excel`, `microsoft-powerpoint`, `microsoft-outlook` (Air has MAS builds; the cask builds are the same apps from Microsoft's installer) | Microsoft 365 account sign-in; no file | account | sign-in via Entra broker (GUI) | Personal / work |
| Microsoft Teams | cask `microsoft-teams` | work account sign-in | account | Screen Recording, Microphone, Camera (GUI) | Work |
| OneDrive | cask `onedrive` (Air has MAS build) | account sign-in | sync root `~/Library/CloudStorage/OneDrive-*`; files-on-demand re-syncs | File Provider approval (GUI) | Work |
| Microsoft To Do | App Store only (no cask) | Microsoft account | account | none | Work |

## Proposed installs

### Cask one-liner (40 casks, not already covered by chezmoi)

```
brew install --cask 1password alfred balenaetcher block-goose brave-browser chatgpt claude conductor crossover daisydisk fastmail firefox ghostty google-chrome hush iina istat-menus iterm2 lunar mailmate microsoft-excel microsoft-outlook microsoft-powerpoint microsoft-teams microsoft-word mist moonlight ngrok nordvpn onedrive orion plex publii signal slack stay steam transmission visual-studio-code whatsapp
```

Adding Bartender 7 is optional: `brew install --cask bartender`.
The 25 formulae above install with one `brew install` line of the same names.

### Cannot be installed headlessly with brew

- App Store only, would need `brew install mas` plus a GUI Apple ID sign-in first, and App Store installs of purchased apps (10): 1Password for Safari, Consent-O-Matic, Kagi for Safari, Kindle, Magnet, Microsoft To Do, Parcel, Pixelmator Pro, Speedtest, UlyssesMac.
- App Store iPhone apps running on the Mac (5): Audible, Big Ass Fans, Sensibo, Spriggy, Runner. `mas` generally cannot install these; do it from the App Store GUI.
- Apple's own App Store apps (5, optional): GarageBand, iMovie, Keynote, Numbers, Pages.
- Direct download (3): Herdr (Herdr.dmg, releases.herdr.dev), Mouser (GitHub tombadash/mouser release), StreamFab (streamfab.com). Possibly a fourth: the second ChatGPT app if the cask supplies only one.
- Local only: the Brave launcher applet (`/Applications/Brave.app`).
- Steps that need the GUI regardless of install route: Accessibility, Screen Recording, Full Disk Access and Input Monitoring grants (Alfred, Lunar, Magnet, Stay, DaisyDisk, iStat Menus, Mouser, Claude, ChatGPT, Teams); privileged helper and network extension approvals (OrbStack, iStat Menus, Adrafinil, Mist, NordVPN, tailscale); Safari extension toggles; login item registration (the Pro must add Stay, Lunar, Adrafinil, Magnet and Alfred 5 itself, since login items are stored in macOS background items, not in the app plists); Apple ID, Microsoft, OpenAI and similar sign-ins.

### Licences and settings that file copy cannot move

- Move by file copy (works): Alfred Powerpack (`powerpack.CL9PL254C7.dat` and the `.alfredpreferences` folder), DaisyDisk (`License.DaisyDisk`), Mouser (`config.json`), plists for IINA, Moonlight, Transmission, Magnet, iTerm.
- Licence must be re-entered or re-activated: iStat Menus (key sits in plist, use the in-app export/import instead), Lunar (Paddle activation), CrossOver, MailMate (licence not on disk), StreamFab, Bartender 7 (upgrade).
- Tied to Apple ID, no file to move: Magnet, Stay (MAS build), Pixelmator Pro, Ulysses, Parcel, Kindle, Speedtest, Microsoft To Do, Safari extensions, iOS-on-Mac apps.
- Account or device link, cannot be copied: 1Password, Signal, WhatsApp, Slack, Microsoft 365, OneDrive, Teams, ChatGPT, Claude, NordVPN, Plex, Steam, Syncthing identity (should differ), Tailscale.
- Settings not safe by plist copy: Lunar (display-serial keyed), Stay (display-keyed layouts), OrbStack (containers not in plist), Syncthing.
