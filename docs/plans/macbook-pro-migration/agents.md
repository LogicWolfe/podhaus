# Coding agents on nb-macbook-air, for the move to the MacBook Pro

> Investigation report gathered read-only on 2026-11-09 by a subagent; it feeds [the migration plan](../macbook-pro-migration.md). Where a recommendation here differs from the plan, the plan is authoritative.

Snapshot taken 2026-11-09 10:40 local time (UTC+8), read-only. Nothing was
signalled, killed or messaged.

Background in one paragraph: every agent terminal on this Mac lives inside
Herdr. The Herdr app (`/Applications/Herdr.app`) talks to a local server,
herdr-core (`hc`), which keeps terminals alive in "holder" processes and also
holds one SSH connection to the herdr-core on each development machine
(voltaire, bandicoot, bilby, fractal). A Herdr "space" is a named group of tabs;
each tab shows one terminal, addressed like `t1d` locally or `voltaire/t27`
remotely. Agents on the remote machines keep running whatever happens to this
Mac, so only the terminals whose address has no machine prefix are local.

## Summary table (live agent processes on this Mac)

| # | Tool | Account | Repo (cwd) | Branch@sha | Dirty files | Worktree? | Herdr / tmux | Resumable on Pro? |
|---|------|---------|------------|------------|-------------|-----------|--------------|-------------------|
| 1 | Claude Code (PID 97642) | personal (`~/.claude`, no `CLAUDE_CONFIG_DIR`) | none: `/Users/nathan` is not a git repo | n/a | n/a | n/a | Herdr local terminal `t1r`, space "herdr-app", unnamed tab "2"; no tmux | Not to be moved: **this is the migration session itself** |
| 2 | Codex CLI `codex resume` (PID 98958) | personal ChatGPT login (`~/.codex`) | `~/.config/herdr-app` (herdr repo, `git.pod.haus:LogicWolfe/herdr`) | main@1fd9b7e, level with origin/main | 32 (23 modified, 9 untracked), **none of them this session's** | no, main checkout | Herdr local terminal `t1d`, space "herdr-app", tab "vaporwave"; no tmux | Yes in principle (copy rollouts, same path), but its work is shipped; recommend not resuming |

Counts: 1 Claude Code, 1 Codex CLI, 0 pi. No agent runs in tmux, in a bare
Ghostty window (Ghostty `ttys002` holds only an idle fish shell) or in an IDE.
Herdr's third local terminal, `t1s` (space "herdr-app", tab "3"), is an idle
fish shell in `/Users/nathan`.

Other agent-looking processes, none of them a session to move:

- **Codex desktop app** (`/Applications/ChatGPT.app`, PID 67797, running since
  Nov 2) with its app-server and a `codex exec-server --remote` to Codex cloud
  environments started today 08:34. Its local thread store has no threads from
  the desktop app; cloud tasks live in OpenAI's cloud and follow the login.
- **Six orphaned `codex app-server` brokers** (PIDs 14683, 47430, 56734, 62038,
  74803, 88802, started Oct 15 to Oct 21) from Claude Code's Codex plugin
  (Codex Companion). They outlived the Claude sessions that started them and
  hold no live thread. They are harmless leftovers on the Air.
- **Claude desktop app** (`/Applications/Claude.app`), no Claude Code children.
- Codex app-server daemon 0.167.0 (PID 29153) serving the `codex resume` TUI.

## Session 1: the migration session (Claude Code, personal)

- PID 97642, started Mon 9 Nov 10:02:29, `claude --enable-auto-mode --allow-dangerously-skip-permissions`, cwd `/Users/nathan`.
- Session id `94c571e6-4cda-4128-96dd-f1f08d02008f`; transcript
  `~/.claude/projects/-Users-nathan/94c571e6-4cda-4128-96dd-f1f08d02008f.jsonl`
  (1.2 MB). Working notes `~/.claude/notes/94c571e6-4cda-4128-96dd-f1f08d02008f-main.md` exists (updated 10:37).
- Inside Herdr terminal `t1r` (environment carries `HC_TERMINAL_ID=t1r`); Herdr's own record shows its starting folder as `~/.config/herdr-app`, the process's cwd is `/Users/nathan`.
- Context: Nathan asked for the new MacBook Pro (`nb-macbook-pro.local`) to be set up with chezmoi (not Ansible), with settings outside chezmoi copied by hand and assessed. Decided: the Pro gets a new name while the Air stays fully working until the Pro is; the Air's passphrase-less machine key was copied to the Pro under the Pro's name, so no key registration changes and the rename is a hostname thread through the dotfiles (fleet table, hostname-gated templates, secret runner, docs tunnel, tests) and Podhaus (UniFi, DNS, Ansible inventory, Pomerium, Forgejo key file and so on). SSH to the Pro works and the Pro is held awake. Investigation subagents are fanned out (this inventory is one of them); the plan is being assembled from their reports.
- **Not to be moved.** It is the session running the migration.

## Session 2: Codex "vaporwave" thread in the herdr repo (Codex CLI, personal)

- PID 98958 `codex resume`, started Mon 2 Nov 13:22 in Herdr terminal `t1d`; Herdr reports it live and idle at turn 55. cwd `/Users/nathan/.config/herdr-app`.
- Thread `01a19a95-cf86-78c1-8d1d-a31976ac016c`, model gpt-6.1-sol (high effort), 172.8M tokens used, context compacted 4 times. Created 2 Nov 12:47, **last activity 3 Nov 16:08** (six days idle).
- Repo: `~/.config/herdr-app`, branch main at `1fd9b7e` "Build Vaporwave scenery from live agents", level with origin/main (0 ahead, 0 behind). Not a worktree.
- Context summary: it began with "my cuts and resizes are all based on an assumed window size rather than a measured one, is that true?" and grew into designing a vaporwave scene for Herdr's Vaporwave layout: an illustration whose objects (sun, sphere, dolphin fountain, pyramid, arcade cabinet, satellite dish and others) appear one by one as agents start, coloured by each agent's state. Nathan directed many art edits (removed rails and floor inlays, moved objects, fixed an appearance order "1 2 3 12 15 7 13 9 10 8 11 5 16 4 6 14" while keeping element numbers), then frame mockups placing the scene under the agent panels without covering terminal text, in dark and light, documented in the plan at `https://mac.docs.pod.haus/herdr/plans/vaporwave-agent-scene.html`. On "ship it" it split the artwork into transparent objects, dropped the ground layers, wired objects to live agent states, passed an independent review (after fixing clipping in short windows), 155 tests and 12 native mod checks, and pushed `1fd9b7e` with CI green. Its last message: "Shipped as 1fd9b7e; tests and CI pass ... Switch to Vaporwave to check it". Nothing is in progress and no next step or blocker was stated; the next move is Nathan's feedback on the live scene.
- Working notes: Codex sessions have none.
- The 32 uncommitted files in this checkout belong to two **Claude** sessions, not this one (see "Repos with unfinished work" below).
- Resuming on the Pro: possible with `codex resume 01a19a95-cf86-78c1-8d1d-a31976ac016c` after copying the main rollout `~/.codex/sessions/2026/11/02/rollout-2026-11-02T12-47-51-01a19a95-cf86-78c1-8d1d-a31976ac016c.jsonl` (177 MB) and, for its spawned helper threads, the 15 subagent rollouts under `~/.codex/sessions/2026/11/02/` (5) and `~/.codex/sessions/2026/11/03/` (10), 80 MB together, to the same paths; the cwd `~/.config/herdr-app` exists at the same path on the Pro once chezmoi runs `herdr-install`. Recommendation: do not resume. The work is shipped and the thread is enormous; start a fresh Codex session in `~/.config/herdr-app` with the summary above if more vaporwave work is wanted.

## Recently finished sessions (last 48 hours), no live process

Claude transcripts modified in the last 48 hours, besides session 1. No Codex
rollout and no pi session was modified in that window (newest Codex activity
is 3 Nov; `~/.pi` holds only an `agent` folder with no sessions).

### A. Switch account, herdr repo: new-menu fixes (uncommitted work)

- Transcript `~/.claude-switch/projects/-Users-nathan--config-herdr-app/12e8a8c6-9891-4c23-85e7-f53872e18092.jsonl` (2.2 MB). File time is 9 Nov 09:00, but the last message is 4 Nov 08:47 local; the file was touched later without new turns. Ran under the Switch account although the repo is personal.
- Working notes `~/.claude/notes/12e8a8c6-9891-4c23-85e7-f53872e18092-main.md` exists.
- Context: Nathan reported that "local" in the new-space menu opened a space on voltaire. Cause: the menu called Herdr's new-space action without a machine, and Herdr fills that from the focused space's machine. Fix in `mods/new-menu-machines/main.js`: both local rows pass an empty machine (meaning this computer). It also added a machine tag (server or monitor icon plus machine name, or "local") to the repo "+" menu header. Both are **uncommitted, waiting for Nathan to try them and accept**, then commit. Herdr's shipped `mods/new-menu/main.js` has the same omission but is read-only, so left alone. It also fixed voltaire's Herdr connection (Pomerium had parked this Mac's machine key; a one-off non-batch `ssh-machine` run plus Nathan's Signal approval bound it for 30 days) and diagnosed that the "Fenwick PWA updates" tab on bandicoot shows no status because that Claude started on build 2.1.274, before status reporting existed; the fix is restarting it with `claude --continue`, Nathan's call.
- Resumable: the work is a small uncommitted diff, so on the Pro it is simpler to commit or carry the diff than to resume. Resuming would need the transcript copied to `~/.claude-switch/projects/-Users-nathan--config-herdr-app/` on the Pro.

### B. Switch account, hybrid-haul-truck workbook fixes (finished, handed off)

- Transcript `~/.claude-switch/projects/-Users-nathan-repos-hybrid-haul-truck-workbook-fixes/f2ffd7c8-cbd8-4f60-9450-7d925a3b2512.jsonl` (21 MB). Last turn 6 Nov 08:37 local; file touched 9 Nov 10:06. It ran in the Herdr space "Workbook fixes" (terminal `t1h`, now finished).
- Working notes `~/.claude/notes/f2ffd7c8-cbd8-4f60-9450-7d925a3b2512-main.md` exists.
- Repo `~/repos/hybrid-haul-truck-workbook-fixes`, a worktree of `~/repos/hybrid-haul-truck` (Switch-Batteries/hybrid-haul-truck on GitHub), branch `plan-workbook-smoke-follow-ups` at `c15357ce3`, tracking origin/dev and level with it; clean.
- Context: fixed every finding from a parallel smoke test of the conversation workbook feature on dev (PRs #495, #496, #497 and Terraform #112 merged; fix log at `https://mac.docs.pod.haus/hybrid-haul-truck-workbook-fixes/guides/workbook-smoke-fix-log.md`). Nathan then had it hand the whole effort to a Claude agent on voltaire, Herdr terminal `voltaire/t27` named "workbook-follow-ups", checkout `~/repos/hybrid-haul-truck-workbook-smoke-follow-ups` on voltaire, which is holding with full context and waiting for Nathan. That agent will raise two MacBook-only clean-ups: retire the local PR #495 guide files once Nathan confirms he read the guide, and remove this worktree plus five merged local branches. One open decision recorded in the repo's `docs/tech_debt.md`: bare `ValueError` counts as an expected refusal, so some invariant failures are logged at info and never reported; the fix (a dedicated refusal type, about 22 sites) was held.
- Nothing to move. Do not resume; the voltaire agent owns the follow-ups.

### C. Personal, chezmoi reconcile run (interrupted)

- Transcript `~/.claude/projects/-Users-nathan--local-share-chezmoi/3dbabc14-470e-4cb7-a301-874a75b23c8b.jsonl`, 9 Nov 10:01 to 10:02, an automated "reconcile chezmoi state" prompt that Nathan interrupted after it found `.claude/settings.json` is a `modify_` template.
- The drift is still there: `chezmoi status` shows `MM .claude/settings.json` (local and source differ). The chezmoi source repo is clean and level with origin (main@b7e4793). Resolve it on the Air before the Pro's first `chezmoi apply`, or the Pro will get the source version and the Air's local change is lost.

## Herdr

### What runs on this Mac

- **Herdr.app** 0.1.14, re-installed by its own updater today at 09:12. Not installed by chezmoi or Homebrew; it was installed by hand.
- **herdr-core / `hc`** 0.1.19. The app installs it itself under `~/.local/share/herdr-core/` (versioned, `current` symlink) and links `~/.local/bin/hc` and `~/.local/bin/herdr-core` to it. The app starts it as `hc --hc-launchd`; local terminals live in holder processes with sockets in `~/.local/state/herdr-core/default/`. One holder from 2 Nov (PID 97712) still holds the Codex terminal `t1d`; the holder from 10:01 today (PID 96097) holds `t1r` and `t1s`.
- **Core identity**: `~/.local/state/herdr-core/default/core.json` names this core `nb-macbook-air` with its own id. The Pro's core will get a fresh id under the Pro's hostname.
- **App home `~/.config/herdr-app`** is a git checkout of `git.pod.haus:LogicWolfe/herdr`. Tracked: mods, layouts, shared, tools, docs, `keys.json`, `settings.json` (zoom 1, sounds on, minimum contrast 1), `programs.json` (Claude launches as `claude-auto --enable-auto-mode --allow-dangerously-skip-permissions`; Codex and pi with their icons). Untracked app state that matters: `shared.json` (active layout is **cyberpunk**, the hidden-machines list is empty, Vaporwave scene assignments, space colours, per-layout panel choices), `view.json`, `window.json` (fullscreen on the Air's display), `windows.json`, `seen.json`, `installed.json`. `telemetry/`, `herdr.d.ts` and `gpui-kit.d.ts` are written by the app.
- **Spaces** (from `docs.json` and `hc ls`): local space "herdr-app" (folder `/Users/nathan`) with tabs "vaporwave" (`t1d`, Codex), "2" (`t1r`, this Claude), "3" (`t1s`, fish), and finished tabs "Workbook fixes" (`t1h`) and an older "2" (`t1k`).

### Machines it connects to

All four `devbox` hosts in the dotfiles fleet table that are not parked, each on Herdr protocol 0.1.15 and connected at snapshot time:

| Machine | Target |
|---|---|
| voltaire | `~/.local/bin/ssh-machine -T -o BatchMode=yes -o ClearAllForwardings=yes voltaire.pod.haus` |
| bandicoot | same pattern, `bandicoot.pod.haus` |
| bilby | same pattern, `bilby.pod.haus` |
| fractal | same pattern, `fractal.pod.haus` |

Remote terminals visible right now (these stay where they are; the Pro sees them once its Herdr links the same machines):

- voltaire: `t1p` Codex "engine-assist-build" (hybrid-haul-truck-engine-assist-drive-mode, idle), `t1q` Codex "gear-ceiling-build" (hybrid-haul-truck-gear-ceiling-road-rules, idle), `t25` Codex (hybrid-haul-truck-transmission-stored-component, idle), `t27` Claude "workbook-follow-ups" (done, holding for Nathan), plus two finished shells.
- bandicoot: `t2` Claude "Fenwick PWA updates" (done; on the old build that never reports status).
- bilby: `t2` Claude "Brinno backfill" in `~/repos/fenwick` (done, turn 81), plus two finished shells.
- fractal: nothing listed.

### How `hc` is authenticated

- Locally: no token or sign-in. `hc` talks to herdr-core over the Unix socket `~/.local/state/herdr-core/default/default.sock`, guarded by file ownership. No Herdr keychain item and no Herdr account exist on this Mac.
- To each machine: plain SSH through `~/.local/bin/ssh-machine`, which on macOS uses the passphrase-less machine key `~/.ssh/id_<short hostname>` (here `id_nb-macbook-air`) with the SSH agent disabled, so no 1Password unlock is needed. Each devbox grants that key in its `authorized_keys` (driven by the fleet table's machine keys). At home the `*.pod.haus` name resolves on the LAN; away it goes through the Pomerium SSH relay, which parks a key's first connection until a browser sign-in is approved by Signal push, and that approval lasts 30 days. Because Herdr's connections use `BatchMode`, they cannot show that sign-in: when it lapses they sit in "needs login", and the fix is running `ssh-machine voltaire.pod.haus true` once interactively and tapping the link (`hc machine login` does not help).
- Pairing: `hc machine add --install` installs herdr-core on the remote if missing and records the remote core's id. A remote that was rebuilt needs "Connect" in the sidebar to forget and re-pair.

### What chezmoi sets up versus what was manual

Chezmoi does:

- `run_after_16-herdr-machines-macos.sh.tmpl` (every apply, macOS): for every non-parked `devbox` in `.chezmoidata/fleet.toml` missing from `hc machine ls`, runs `hc machine add --name <host> --install --via "~/.local/bin/ssh-machine -T -o BatchMode=yes -o ClearAllForwardings=yes <host>.pod.haus"`. A failed add only prints "Herdr is not linked to: ..."; the next apply retries.
- `run_after_24-herdr-macos.sh.tmpl` (every apply, macOS hosts with `development = true` in the fleet table): runs `~/.local/bin/herdr-install`, which, if `~/.config/herdr-app` is not yet a git checkout, inits it, fetches the herdr repo and force-checks-out `main` over the app's own `keys.json`, `settings.json` and `programs.json`. An existing checkout is left alone.
- `~/.local/bin/ssh-machine`, `~/.local/bin/herdr-agent` (launches an agent in a new `wt` worktree as a labelled Herdr space), the shared `herdr-agents` skill for Claude and Codex, fish `conf.d/herdr.fish` (sets `HERDR_ENV=1` inside Herdr terminals so Codex forwards copies), the docs server's `herdr` source pointing at `~/.config/herdr-app`, and herdr-core on Linux devboxes (`run_onchange_04-packages.sh.tmpl`, Linux only). `.chezmoiignore` keeps `.config/herdr-app` out of chezmoi.

Done by hand on the Air:

- Downloading and installing Herdr.app and launching it once (which installs herdr-core and the `hc` links).
- The Pomerium sign-in approval for the machine key on each relay connection.
- Choices stored only in untracked app state: active layout (cyberpunk), window placement, space colours, Vaporwave scene assignments, panel choices.

### What the Pro needs

1. Install Herdr.app by hand and launch it once, **before** the first `chezmoi apply` that renders the Herdr scripts. Finding: `run_after_16-herdr-machines-macos.sh.tmpl` runs under `set -eu` and starts with `added=$(hc machine ls --json | jq ...)`; with no `hc` on the PATH that line fails and the apply fails, rather than printing "not linked". Either install Herdr first, or (Nathan's decision) make the script skip when `hc` is absent.
2. The fleet table needs a `nb-macbook-pro` entry with `development = true`, or `run_after_24` never runs `herdr-install` and `~/.config/herdr-app` is never made a checkout. The migration session's rename thread covers this.
3. The machine key must exist as `~/.ssh/id_nb-macbook-pro`, since `ssh-machine` derives the file name from `uname -n`. The migration session reports it already copied the Air's key there, so the devboxes' `authorized_keys` and Pomerium need no change. If the Pro is away from home on first apply and Pomerium has not seen the key from the Pro, run `ssh-machine voltaire.pod.haus true` once and approve.
4. After apply, `hc machine ls` on the Pro should list voltaire, bandicoot, bilby and fractal as connected; the remote terminals listed above then appear in the Pro's Herdr without moving anything.
5. Optional: copy `~/.config/herdr-app/shared.json` (layout choice, colours, scene assignments) from the Air to keep the look; skip `window.json`, which is tied to the Air's display.
6. Before step 1 on the Pro, decide what to do with the 32 uncommitted files in the Air's `~/.config/herdr-app` (next section); `herdr-install` on the Pro clones origin/main, so they do not travel.

## Repos with unfinished work not attached to any live session

Scanned all 63 checkouts under `~/repos`, `~/.claude-worktrees/*`, `~/.config/herdr-app` and the chezmoi source for uncommitted files, missing or gone upstreams, commits on no remote, and stashes. Everything not listed is clean and pushed.

**Uncommitted work**

- `~/.config/herdr-app` (herdr repo, main@1fd9b7e): 23 modified, 9 untracked. Two Claude sessions made them. (1) Personal session `c55d6bc0-41c3-4829-a4cd-c7e7d515e9e7` (4 Nov 08:13 to 08:19, transcript `~/.claude/projects/-Users-nathan--config-herdr-app/c55d6bc0-41c3-4829-a4cd-c7e7d515e9e7.jsonl`) added a menu, opened from the "+N remotes" readout, that shows or hides individual remote machines in the sidebar: new `mods/machine-menu/`, new `shared/fleet.js` synced into each layout as `mods/*/fleet.js`, readout-as-button edits in the Glass, Sunrise, Darkmode and Vaporwave mods, `tools/tests/hidden-machines.test.mjs`, README and docs index. Tests passed; it never committed. (2) Switch session A above: the new-menu "local" fix and machine tag in `mods/new-menu-machines/main.js`. Recommended: Nathan tries both in the running app and has them committed and pushed from the Air before setting up the Pro (decision: commit as is, or discard).
- `~/repos/veil-voice` (worktree of `~/repos/veil`, branch `voice`, no upstream, last commit 26 Oct): 2 modified plan files (`docs/plans/README.md`, `docs/plans/data.md`) and 1 untracked `docs/plans/voice.md`. Not touched in the last 48 hours. The branch is not on the remote either. Needs pushing or copying if the voice plan matters.

**Commits that exist only on this Mac** (lost if the Pro clones fresh instead of copying `~/repos`)

- `~/repos/hybrid-haul-truck`: 107 commits on 14 local-only branches, mostly backups and pre-rebase snapshots (`catalog-schemas-pre-rebase2` 25, `route-naming-refactor-backup` 20, `agent-telemetry-reviewed-06e38ac90` 14, `catalog-schemas-pre-rebase` 14, `config-draft-session` 11, `draft-session-backup` 11, `preview-terraform-substrate` 8, `agent-telemetry-restack-182` 6, and six with 1 to 3 each).
- `~/repos/chat-investor-ui`: 13 commits on 10 local-only branches (for example `scheduled-prompts-v2` 3, `feat/monitor-report-split` 2).
- `~/repos/ulysses-link`: `main-backup`, 4 commits.
- `~/repos/SRG`: branch `2025-11-06-eaip-6c43a`, 3 commits, and 1 stash.
- `~/repos/wattsworth`: `docs-timesheets-reorg` and `log-time-batch-prompts`, 1 commit each.
- `~/repos/peers`: `tauri-v2-migration`, 1 commit.
- `~/repos/cluster_to_23snaps`: no remote at all; 1 commit on main (last commit 2022).
- `~/repos/terraform`: 1 stash, no unpushed commits.

**Stale worktrees, clean, nothing to carry** (upstream gone or none, no local-only commits): `~/repos/bookshelf-audible-purchase`, `~/repos/hybrid-haul-truck-agent-dependencies` and `~/repos/hybrid-haul-truck-agent-telemetry` (remote branches deleted), `~/repos/hybrid-haul-truck-notion-plan` (detached HEAD), `~/repos/podhaus-visual-test`. `~/repos/hybrid-haul-truck-workbook-fixes` is clean and slated for removal by the voltaire agent.

## What could not be determined

- Which exact session made the `agent-state.js` and `navigation.js` edits across the layout mods in `~/.config/herdr-app`; they fit the hidden-machines session's description ("hiding takes effect in the shared code") but no diff was read.
- Codex desktop cloud tasks: they live in OpenAI's cloud, not on disk here.
- Why two Switch transcripts were modified today without new turns (likely Claude Code rewriting metadata at startup); it does not change the picture.
