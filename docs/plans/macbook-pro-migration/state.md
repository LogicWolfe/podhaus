# Unmanaged state on the MacBook Air (nb-macbook-air), classified for the move to the MacBook Pro

> Investigation report gathered read-only on 2026-11-09 by a subagent; it feeds [the migration plan](../macbook-pro-migration.md). Where a recommendation here differs from the plan, the plan is authoritative.

Read-only survey, 2026-11-09. Nothing was read from any secret file; only existence, size and purpose.
"Chezmoi?" = should chezmoi start managing it. "Copy" = rsync from Air to Pro. "Re-login" = authenticate fresh on the Pro.

Background: the Air already has a chezmoi-managed identity model (machine key `~/.ssh/id_<hostname>`, 1Password service-account tokens at `~/.local/state/op-vault/*.token`, docs-tunnel certs fetched from 1Password on apply). Items below are only what chezmoi does NOT own.

Drift check: `chezmoi status` shows `.claude/settings.json` as modified. Semantic comparison (`jq -S` on the template output vs the live file) is **identical**: the app rewrote the file with different JSON spacing (`"key" : v` vs `"key": v`). Not real drift; `chezmoi apply` would only reformat it. The `R` lines for run_* scripts are the known permanent noise noted in ~/WIP.md.

## 1. Credentials (auth tokens)

| Path | Size | Owner / what it is | Recommendation | Chezmoi? |
|---|---|---|---|---|
| macOS Keychain "Claude Code-credentials" | n/a | Claude Code OAuth | Re-login (`claude` then `/login`); keychain items are not file-copyable | no |
| `~/.local/state/op-vault/{dev,switch}.token` | 818 B, 839 B | 1Password service-account tokens read by `op-vault` | Provide on the Pro through the existing documented identity procedure (README "Development identities"); a Pro-specific token is better than a copy | no (secret; the wrapper script is already managed) |
| `~/.ssh/id_nb-macbook-air` (+ `.pub`) | 419 B | Air's machine key | Do NOT copy: the Pro has its own `id_<hostname>`. Task states the Pro key was already placed; confirm it is the Pro's own | no |
| `~/.ssh/id_personal.pub` | 101 B | public half of personal key (private lives in 1Password agent) | copy (public) | maybe yes (public, non-secret) |
| `~/.ssh/authorized_keys` | 926 B | inbound keys | Pro's sshd differs; `/etc/ssh/authorized_keys/nathan` (root-owned) is the real source. Skip | no |
| `~/.codex/auth.json` | 4.0 KB | Codex CLI login (ChatGPT/API) | Re-login (`codex login`) | no |
| `~/.pi/agent/auth.json` | 998 B | pi agent provider logins | Re-login | no |
| `~/.config/gh/hosts.yml` | in 8 KB dir | GitHub CLI token | Re-login (`gh auth login`) | no |
| `~/.config/neonctl/credentials.json` | 4 KB | Neon CLI token | Re-login (`neonctl auth`) | no |
| `~/.config/graphite/user_config` | in 8 KB dir | Graphite CLI token | Re-login (`gt auth`) | no |
| `~/.config/rclone/rclone.conf` | 4 KB | rclone remotes with secrets | Copy only if still used; else skip. Contains secrets | no (secret) |
| `~/.config/stormy/stormy.toml`, `~/Library/Application Support/rustormy/config.toml` | 4 KB each | weather CLI config (may hold API key) | Copy (tiny); likely safe but may hold an API key | no unless key-free |
| `~/.config/op/config` | 144 B | 1Password CLI account list | Re-create (`op account add` / sign in via app integration) | no |
| `~/.local/state/llm-token/token.json` | 952 B | LLM token cache | Re-create | no |
| `~/.cli-m365-*.json` (3 files) | 4-8 KB | CLI for Microsoft 365 MSAL tokens | Re-login (`m365 login`) | no |
| `~/.azure/` | 116 KB | Azure CLI profile + MSAL token cache | Re-login (`az login`) | no |
| `~/.aws/sso/cache`, `~/.aws/cli` | 36 KB total | AWS SSO tokens (short-lived) | Re-login (`aws sso login`); `.aws/config` already managed | no |
| `~/.railway/` | 28 KB | Railway CLI token + state | Re-login (`railway login`) | no |
| `~/.sentryclirc` | 4 KB | Sentry CLI auth token | Re-create (`sentry-cli login`) or copy by hand | no (secret) |
| `~/.cloudflared/` (3 token files) | 12 KB | Cloudflare Access org tokens | Re-login on first use | no |
| `~/.mine-api-client/token-*.json` | 16 KB | cached API client tokens | Re-login | no |
| `~/.copilot/config.json` | 16 KB | GitHub Copilot CLI login | Re-login | no |
| `~/.ansible/galaxy_token` | in 33 MB dir | Ansible Galaxy token | Re-create if needed | no |
| `~/.docker/config.json`, `.token_seed` | 2.9 MB dir | Docker CLI; `auths` is empty, context = orbstack | Skip; OrbStack re-creates | no |
| `~/.gnupg/` | 68 KB | GPG; no private keys (0), only keyboxd/pubring | Skip | no |
| `~/.claude/.claude.json`, `~/.claude.json` | 164 KB | Claude Code account state, MCP servers, per-project trust | Re-login then re-add MCP; copy only for project trust settings | no (contains account identifiers) |
| `~/.claude/plugins/` (installed_plugins, marketplaces) | 21 MB | Claude plugin installs | Re-install plugins (`codex@openai-codex`, etc.; `always_09-codex-plugin.sh` handles codex) | no |
| `~/Library/Application Support/1Password`, Keychains | 6 MB | 1Password app / login keychain | Sign in again; never copy keychains | no |
| `~/Library/Application Support/Syncthing/{key,https-key}.pem` | 4 KB each | Syncthing device identity (also in section 5) | Do NOT copy | no |

## 2. Configuration

| Path | Size | Owner / what it is | Recommendation | Chezmoi? |
|---|---|---|---|---|
| `~/.zshrc`, `.profile`, `.bashrc`, `.tcshrc` | 4 KB each | shell rc files (login shell is fish; zshenv/zprofile already managed) | Skip; likely stubs. Review `.zshrc` once | no, unless they hold something live |
| `~/.mcp.json` | 4 KB | user MCP server list for Claude | Copy | yes if it holds no tokens (inspect first) |
| `~/.config/direnv/` | 0 | empty | skip | no |
| `~/.config/chezmoi/` | 260 KB | chezmoi's own config + key state | Pro already has chezmoi configured by bootstrap. Skip | no |
| `~/.config/iterm2/`, `~/Library/Preferences/com.googlecode.iterm2.plist`, `Application Support/iTerm2` | 3.3 MB | iTerm2 prefs | Copy plist if still used (Ghostty is managed) | yes optional (plist export) |
| `~/Library/Preferences/com.mitchellh.ghostty.plist` | small | Ghostty app state (config is managed) | skip | no |
| `~/Library/Preferences/dev.zed.Zed.plist`, `com.microsoft.VSCode.plist` | small | app state | skip (Zed settings managed) | no |
| `~/.vscode/argv.json`, `~/.vscode-shared` | 24 KB | VS Code runtime args | skip; use VS Code Settings Sync | no |
| `~/Library/Application Support/Code/User` (settings, keybindings, snippets) | few KB (within 569 MB dir) | VS Code user config | Copy `User/` only, or use Settings Sync | yes if Nathan still uses VS Code |
| `~/.cursor/hooks.json` (rules already managed) | 4 KB | Cursor hooks | copy | yes (non-secret) |
| `~/.codex/hooks.json`, `rules/`, `skills/` (non-managed ones) | small | Codex hooks and rules (config.toml, AGENTS.md managed) | copy `hooks.json`, `rules/` | yes (non-secret) |
| `~/.claude/settings.local.json` | small | local Claude permission overrides | Copy | no (machine-local by design) |
| `~/.claude/profiles/`, `~/.claude/commands/` (extras beyond ssh.md) | small | Claude profiles/commands | Copy | maybe yes for commands |
| `~/.claude-switch/` (settings, CLAUDE.md, skills, commands managed) | 90 MB | work Claude profile (Switch) | Config managed; re-login. Its `.claude.json` and `projects/` are state | already managed |
| `~/.pi/agent/{settings.json,mcp.json,models-store.json,extensions,bin}` | 7 MB | pi coding agent config | Copy settings/mcp/extensions; `bin` skip | yes for settings.json/mcp.json if token-free |
| `~/.config/goose/` (config.yaml, recipes, .goosehints managed) | 298 MB | Goose; 298 MB is `mcp-hermit` download cache | Skip `mcp-hermit`, `tls`; rest managed | already managed |
| `~/.config/herdr-app/` | 103 MB | Herdr app config, mods, docs, tools: **is a git repo** (origin git@git.pod.haus:LogicWolfe/herdr.git, branch main) with **32 uncommitted changed files** | Commit/push from the Air, then clone on the Pro; or rsync the whole directory | no (own repo; commit it) |
| `~/Library/Application Support/Goose` | 2.2 MB | Goose desktop Electron state | skip | no |
| `~/Library/Application Support/Claude/claude_desktop_config.json`, `Claude-3p/claude_desktop_config.json` | small | Claude Desktop MCP config | Copy those JSONs only | maybe (check for tokens) |
| `~/Library/Application Support/Zed` (db, extensions) | 928 MB | Zed caches/extensions | skip; Zed re-downloads | no |
| `~/Library/Application Support/Alfred` / `Alfred.alfredpreferences` | 2.4 MB | Alfred workflows/prefs | Copy (or Alfred sync) | no |
| `~/Library/Application Support/Adrafinil` | 280 KB | keep-awake tool; `config.json`, `state.json`, `events.log` | copy `config.json` only; hooks installed by managed script | yes (config.json if non-secret) |
| `~/Library/Application Support/Mouser/config.json`, `MailMate`, `Stay`, `Lunar`, `iStat Menus 7`, `Orion`, `Fastmail`, `Publii`, `balenaEtcher` | 0.4 KB - 260 MB | GUI apps | Re-install apps; use each app's own sync/export. Lunar `.padl` is a license: copy (`650170.*`) | no |
| `~/Library/Application Support/Caddy/autosave.json` | 4 KB | Caddy runtime autosave (docs-tunnel is managed separately) | skip | no |
| `~/.terraform.d`, `~/.matplotlib`, `~/.cups/lpoptions`, `~/.dsh`, `~/.happy`, `~/.herdr`, `~/.homebrew`, `~/.kube` | 0-412 KB | tool scratch (checkpoint, font cache, printer opts, empty dirs) | skip | no |
| `~/.bashrc.d`, `~/.claude-worktrees/{bookshelf,fenwick}`, `~/.claude.notes` | 0 | empty | skip | no |

## 3. State and history

| Path | Size | Owner / what it is | Recommendation | Chezmoi? |
|---|---|---|---|---|
| `~/.claude/projects/` | 1.8 GB | Claude Code session transcripts, memory (`projects/*/memory`) | Copy only `projects/*/memory/` (auto-memory). Whole tree only if resuming old sessions (paths embed `/Users/nathan`, same on Pro) | no |
| `~/.claude/history.jsonl`, `file-history`, `plans`, `sessions`, `paste-cache`, `shell-snapshots`, `teams`, `jobs` | ~14 MB | prompt history and session scratch | Optional copy of `history.jsonl` and `plans`; rest skip | no |
| `~/.claude/notes/` (WIP session notes) | small | working notes (`.keep` managed) | Copy | no |
| `~/.claude-switch/projects` and `history.jsonl` | 84 MB | work-profile transcripts | Optional; copy memory dirs only | no |
| `~/.codex/sessions`, `thread_history_1.sqlite`, `state_5.sqlite`, `memories_1.sqlite`, `history.jsonl`, `session_index.jsonl` | ~600 MB | Codex conversation history, memories | Copy `memories_1.sqlite`, `history.jsonl`; sessions only if wanted | no |
| `~/.pi/agent/sessions` | in 7 MB | pi transcripts | optional | no |
| `~/.zsh_history`, `.viminfo`, `~/.local/state/lesshst` | 4-8 KB | shell/editor history | skip (fish history is under `.local/share/fish`, 88 KB: copy `fish_history`) | no |
| `~/.local/share/fish/fish_history` | 88 KB dir | fish command history | Copy | no (private) |
| `~/.local/share/direnv/allow` | 52 KB | direnv trusted-dir hashes | skip; hashes are path+content, re-run `direnv allow` | no |
| `~/.local/share/signal-cli/data` | 2.1 MB | signal-cli linked-device registration (also identity) | Do NOT copy; re-link a new device | no |
| `~/.local/share/goose`, `~/.local/state/goose` | 4.6 MB + 156 KB | Goose sessions | optional | no |
| `~/.local/share/graphite`, `~/.local/state/gh`, `~/.local/state/herdr-core`, `~/.local/share/herdr-core/state` | small | tool state | skip | no |
| `~/.local/share/lumen` | 9.4 MB | Lumen semantic index | skip; rebuilds via lumen-reindex | no |
| `~/Library/Application Support/Syncthing/index-v2` | 23 MB | sync index | skip (identity section) | no |
| `~/Library/Application Support/Signal` | 4.6 GB | Signal Desktop DB/attachments | Re-link Signal Desktop; archive transfer is via Signal's own mechanism | no |
| `~/Library/Application Support/com.conductor.app/conductor.db` | 832 KB | Conductor app database | copy `conductor.db` if used (bin is 390 MB, skip) | no |
| `~/Library/Application Support/Claude/{claude-code-vm,vm_bundles}` | 11.3 GB | Claude Desktop VM images | Skip; re-downloaded | no |
| `~/Documents` 11 GB, `~/Desktop` 684 MB, `~/Pictures` 21 GB, `~/Downloads` 42 GB, `~/Music` 9.5 MB | | user files | Nathan's call; Documents/Desktop/Pictures are likely copy (or iCloud), Downloads is review-then-copy | no |
| `~/Rescue/` | 105 GB (`ecroeser` 104 GB, `repaired` 445 MB, `_recovery` 5.5 MB, report PDF) | data-recovery project output | Nathan's call; likely archive to external disk, not the laptop | no |
| `~/WIP.md`, `~/README.md`, `~/SQLite Guidance.pdf`, `~/What each column...pdf` | 2 KB each | loose notes | Copy | no |
| `~/scratch/` (2 review briefs), `~/tmp/prototypes`, `~/go` (231 MB module cache) | 2 MB | scratch | copy `scratch`, `tmp`; skip `go` | no |
| `~/repos` non-git folders: `battery-calibration` 8K, `budget` 12M, `median_window_analysis_results` 2.8M, `proposal` 340K, `todoms` 8K (and empty `fenwick-wt`, `podhaus-wt`, `results`, `tmp`) | 16 MB | non-versioned working data | **Copy**; not clones | no |

## 4. Caches and reinstallable artefacts (skip)

| Path | Size | What it is | Recommendation |
|---|---|---|---|
| `~/.npm` | 7.4 GB | npm cache | skip |
| `~/.cache` | 7.1 GB | uv/pip/misc caches | skip |
| `~/.local/share/virtualenvs` | 8.1 GB | pipenv virtualenvs (81) | skip; re-create per project |
| `~/.local/share/mise` | 2.9 GB | mise-installed tools (`config.toml` managed) | skip; `mise install` |
| `~/.local/share/aube` | 1.4 GB | package store | skip |
| `~/.local/share/claude` | 1.2 GB | Claude Code binaries (`versions/`) | skip; reinstall via installer |
| `~/.local/share/claude-agent-acp` | 437 MB | ACP adapter (managed script fetches) | skip |
| `~/.local/share/docs-server` | 362 MB | docs server build (managed scripts rebuild) | skip |
| `~/.local/share/uv` | 16 MB | uv tools (`it2`) | skip |
| `~/.rustup` 1.3 GB, `~/.cargo` 533 MB | | Rust toolchain/registry (managed script 03-rustup) | skip; `~/.cargo/bin` reinstall |
| `~/.bun` | 268 KB | bun | skip |
| `~/.codex/packages` 2.8 GB, `plugins` 413 MB, `.tmp`, `cache`, `logs_2.sqlite`, `vendor_imports` | ~3.6 GB | Codex runtime and plugin cache | skip |
| `~/.vscode/extensions`, `cli` | 1.5 GB | VS Code extensions | skip; Settings Sync reinstalls |
| `~/Library/Application Support/Code/*Cache*`, `CachedExtensionVSIXs` | ~540 MB | VS Code caches | skip |
| `~/Library/Application Support/{Claude/Cache,Claude/Code Cache,CEF,Google,Codex,com.apple.*}` | ~3 GB | Electron caches (Codex app 467 MB, Chrome 787 MB) | skip |
| `~/Library/Application Support/{Steam,CrossOver,SlayTheSpire2,CavesOfQud,Plex,Transmission,StreamFab}` | 11.6 GB | games and media apps | Re-install; saves via Steam Cloud. CrossOver bottles are Nathan's call |
| `~/.config/herdr-app/tools` etc. | in 103 MB | covered under configuration (repo) | |
| `~/.config/goose/mcp-hermit` | 298 MB | Goose MCP download cache | skip |
| `~/.config/configstore` | 4 KB | npm update-notifier | skip |
| `~/.local/state/{chezmoi-last-update,claude-agent-acp-last-fetch,pnpm,mise}` | tiny | timestamps/state | skip |
| `~/.ollama` | 309 MB | Ollama models (`models/blobs`) | skip; `ollama pull` (service is a brew launchd item) |
| `~/Library/Application Support/Zed/{languages,external_agents,extensions}` | 905 MB | Zed downloads | skip |
| `~/.ansible` | 33 MB | collections, galaxy cache | skip; reinstall collections |
| `~/.claude/{cache,downloads,backups,ide,chrome,session-env,daemon*,feedback}` | small | Claude runtime | skip |
| `~/.claude.json.backup`, `~/.claude.json.tmp.*` | 84 KB / 0 | Claude temp/backup | skip |
| `~/.DS_Store`, `~/.CFUserTextEncoding`, `~/.Trash` | | macOS | skip |
| `~/Applications` | 1.5 MB | app shortcut stubs | skip |

## 5. Machine-specific identity (must NOT be copied)

| Path | Size | What it is | Recommendation |
|---|---|---|---|
| `~/Library/Application Support/Syncthing/` (`key.pem`, `https-key.pem`, `config.xml`, `index-v2`) | 23 MB | Syncthing device ID and config; copying makes two devices claim one ID | Do not copy. Install on Pro (`brew services start syncthing`), then add as a new device and share folders |
| `~/.orbstack/` and `~/OrbStack/` | 4.6 MB | OrbStack VM identity, ssh config, vmstate; containers/images live elsewhere | Do not copy. Reinstall OrbStack, rebuild containers |
| `~/.local/share/herdr-core/` (`Herdr Core.app`, `active`) and `~/.local/state/herdr-core` | 12 MB | Herdr core daemon install and per-host state | Do not copy; `herdr-install` / managed script `24-herdr-macos.sh` recreates |
| `~/.local/share/signal-cli/data` | 2.1 MB | signal-cli linked-device identity | Do not copy |
| `~/Library/Application Support/Caddy/instance.uuid` | 4 KB | Caddy instance id | Do not copy |
| `~/.codex/installation_id`, `~/.homebrew/trust.json.lock`, `~/.orbstack/.installid` | tiny | install identifiers | Do not copy |
| `~/.ssh/known_hosts`, `known_hosts.old`, `known_hosts.podhaus` | 15 KB each | host keys; `00-ssh-hostkeys` is managed | Optional copy of `known_hosts` to avoid TOFU prompts; `.old` skip. Tailscale node state is not present in the home dir (system extension) |
| `~/.ssh/agent`, `config.cc-clip-backup`, `pod.d`, `config.d` | small | agent socket dir, backup, managed split config | skip (`config`/`config.d` managed by script) |
| `~/Library/LaunchAgents/{homebrew.mxcl.syncthing,sh.brew.ollama,com.valvesoftware.steamclean,com.google.*,com.bjango.*}.plist` | small | brew/app-created agents; the four `com.podhaus.*` and `com.cc-clip.daemon` are managed | Do not copy; reinstall the apps |
| `~/Library/Application Support/Adrafinil/state.json`, `events.log` | 264 KB | per-host runtime state | skip |
| `~/Library/Application Support/com.openai.chat`, `com.openai.codex`, `OpenAI` | few MB | ChatGPT/Codex desktop app state | Re-login |

## 6. Repositories with uncommitted or unpushed work (~/repos, 64 entries)

| Repo | Finding |
|---|---|
| veil-voice | 3 uncommitted files; branch `voice` has no upstream (not pushed) |
| SRG | 1 stash on `dev` |
| terraform | 1 stash on `dev` |
| terraform-sandbox-runner-auth | 1 stash on `sandbox-runner-authorization` |
| bookshelf-audible-purchase | branch `audible-purchase` has no upstream; no commits that are absent from every remote ref |
| podhaus-visual-test | branch `visual-test` has no upstream; no local-only commits |
| cluster_to_23snaps | no remote at all; 1 commit exists only here ("generated with bundle gem") |
| hybrid-haul-truck (all worktrees: `-agent-dependencies`, `-agent-telemetry`, `-notion-plan`, `-workbook-fixes`) | the five are worktrees of one repository; 79 local branches have no remote or a gone remote, 107 commits across them exist on no remote branch (e.g. `hitachi-bev-dev-verified`, `agent-telemetry-restack-182`, `agent-telemetry-reviewed-06e38ac90`; `agent-dependencies` and `agent-telemetry` upstreams are "gone"). Worktrees cannot be recloned; push or archive branches you want first. Working trees themselves are clean |
| `~/.config/herdr-app` (not under ~/repos) | 32 uncommitted modified files, git repo with remote `LogicWolfe/herdr` |

All other repos are clean with no local-only state. Non-git folders under ~/repos are listed in section 3.

## 7. Proposed chezmoi additions

| Item | Why it is safe |
|---|---|
| `~/.mcp.json` | MCP server list; verify no inline tokens first (use `op://` or env references) |
| `~/.codex/hooks.json`, `~/.codex/rules/`, `~/.cursor/hooks.json` | tool hooks/rules, no secrets |
| `~/.pi/agent/settings.json`, `mcp.json` | agent settings; not `auth.json`/`models-store.json` |
| `~/.ssh/id_personal.pub`, `known_hosts` (optional) | public data |
| `~/Library/Application Support/Adrafinil/config.json` | tiny config, no secret |
| `~/.claude/settings.json` | already managed; fix the apparent drift by rewriting the template as formatted JSON (or accept benign reformatting), content is identical |
| herdr config repo | not chezmoi; commit and push the existing repo instead |

Never manage: all credential rows, machine-identity rows, history.

## 8. Proposed rsync include list (copy items)

```
# run from the Air; adjust the destination host
rsync -aR --relative \
  ~/./.mcp.json \
  ~/./.claude/settings.local.json ~/./.claude/profiles ~/./.claude/commands ~/./.claude/notes ~/./.claude/plans ~/./.claude/history.jsonl \
  ~/./.claude/projects/*/memory \
  ~/./.codex/hooks.json ~/./.codex/rules ~/./.codex/memories_1.sqlite ~/./.codex/history.jsonl \
  ~/./.cursor/hooks.json \
  ~/./.pi/agent/settings.json ~/./.pi/agent/mcp.json ~/./.pi/agent/extensions \
  ~/./.config/herdr-app \
  ~/./.config/stormy ~/./.config/rclone \
  ~/./.local/share/fish/fish_history \
  ~/./.ssh/id_personal.pub ~/./.ssh/known_hosts \
  ~/./Library/Application\ Support/Code/User \
  ~/./Library/Application\ Support/Claude/claude_desktop_config.json \
  ~/./Library/Application\ Support/Claude-3p/claude_desktop_config.json \
  ~/./Library/Application\ Support/Adrafinil/config.json \
  ~/./Library/Application\ Support/Alfred \
  ~/./Library/Application\ Support/Lunar/650170.padl ~/./Library/Application\ Support/Lunar/650170.spadl \
  ~/./Library/Application\ Support/Mouser/config.json \
  ~/./Library/Application\ Support/rustormy/config.toml \
  ~/./Library/Application\ Support/com.conductor.app/conductor.db \
  ~/./Library/Preferences/com.googlecode.iterm2.plist \
  ~/./WIP.md ~/./README.md ~/./scratch ~/./tmp \
  ~/./Documents ~/./Desktop ~/./Pictures \
  ~/./repos/battery-calibration ~/./repos/budget ~/./repos/median_window_analysis_results \
  ~/./repos/proposal ~/./repos/todoms \
  nathan@<pro>:~/
```

Before running: (1) commit/push `~/.config/herdr-app` and the repos in section 6, or add `~/repos/veil-voice` and `~/repos/cluster_to_23snaps` and the hybrid-haul-truck repo (with branches) to the list; (2) the rclone stormy entries contain secrets, so use an encrypted transport (rsync over SSH is fine); (3) Downloads (42 GB) and Rescue (105 GB) are left out pending Nathan's decision.
