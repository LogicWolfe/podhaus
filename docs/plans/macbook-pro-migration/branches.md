# Local-only branches and stashes on the MacBook Air

> Investigation report gathered read-only on 2026-11-09 by a subagent; it feeds [the migration plan](../macbook-pro-migration.md). Where a recommendation here differs from the plan, the plan is authoritative.

Surveyed 2026-11-09, read-only (no fetch, checkout, delete or stash pop). Remote refs are as last fetched.

Method: commits counted with `git log <branch> --not --remotes`. "Patches upstream" is non-merge commits whose `git patch-id --stable` equals the patch-id of any commit on any remote ref (same as a `-` line in `git cherry`, but against all remotes rather than one branch, because most of these branches were rebased and squash-merged). Where a patch-id did not match, I looked for the same commit subject on a remote, then compared file contents or code on the remote branch to see whether the work landed in reworked form. "Landed" below means that check passed.

Repos with no local-only work: every other repo under ~/repos (including backend, podhaus). The four extra hybrid-haul-truck worktrees add no branches of their own (agent-dependencies and agent-telemetry have deleted upstreams but no unpushed commits; notion-plan is a detached HEAD with 0 unpushed commits; workbook-fixes tracks origin/dev).

## hybrid-haul-truck (GitHub Switch-Batteries; main checkout on `dev`)

None of these 14 branches is checked out in any worktree. Common cause: squash-merged PRs and rebases left the pre-squash commits behind. Remote default is origin/dev for most.

| Branch | Local-only commits (non-merge) | Dates | Patches upstream | What it holds | Verdict |
|---|---|---|---|---|---|
| catalog-schemas-pre-rebase2 | 25 (25) | 2026-07-14..15 | 24 of 25 | Catalog authoring-schema stack. The 1 unmatched commit ("Gate diesel efficiency...") exists upstream as 19139f341 and in PR #156. | CULL |
| catalog-schemas-pre-rebase | 14 (13) | 2026-07-14..15 | 12 of 13 | Same stack as above, earlier snapshot; same unmatched commit landed in #156. | CULL |
| route-naming-refactor-backup | 20 (20) | 2026-06-29 | 17 of 20 | Segment-to-route rename. The 3 unmatched commits have reconciled twins upstream (2ac29d5ef, f26b60014) and the whole stack landed in PR #108. | CULL |
| agent-telemetry-reviewed-06e38ac90 | 14 (9) | 2026-10-14 | 3 of 9 | Pre-review snapshot of agent telemetry. Others landed reworked: PR #458, 77251d2bc, 9f3fa1c48. The chat-acceptance change (06e38ac90) is present on origin/dev in `chat.py` (`_acceptances`, `_settle_acceptance`); the telemetry test files are identical on origin/dev. | CULL |
| agent-telemetry-restack-182 | 6 (6) | 2026-10-14 | 3 of 6 | Restack of the same work; 3 unmatched landed as f317b5a91, 77251d2bc, 9f3fa1c48. | CULL |
| config-draft-session | 11 (8) | 2026-07-22..23 | 6 of 8 | Config draft-session layer. Unmatched two landed in PR #185 (66fd9076c, 951f5245a, ad09b7bc2). | CULL |
| draft-session-backup | 11 (8) | 2026-07-22..23 | 6 of 8 | Identical tip commit (b2b929068) to config-draft-session; pure duplicate. | CULL |
| preview-terraform-substrate | 8 (7) | 2026-07-22..23 | 0 of 7 | Preview plan/doc and tech-debt notes plus one test tweak; all folded into squash PR #182 (506266ba4 touches the same files). | CULL |
| preview-config-tier | 2 | 2026-07-22 | 0 of 2 | Config tier vs deployment identity; landed as PR #175. | CULL |
| catalog-battery-schema-fixes | 3 | 2026-07-21 | 0 of 3 | Battery chemistry/power-rate moves; landed as PR #167. | CULL |
| preview-database-ownership-guard | 1 | 2026-07-22 | 1 of 1 | Patch already upstream. | CULL |
| preview-environments | 1 | 2026-06-30 | 0 of 1 | Original 385-line preview-builds plan; the file existed upstream and was later deleted (9944d4594), replaced by docs/previews.md. | CULL |
| hitachi-bev-dev-verified | 1 | 2026-10-19 | 0 of 1 | Landed on origin/dev as 8f4b3ddfb (same 6 files; diff of the two patches differs by ~10 lines of context). | CULL |
| slow-tests | 1 | 2026-06-23 | 1 of 1 | Upstream as 23bba7c4c (`git cherry` shows `-`). | CULL |

Recurrence/test-gap note: all fourteen are rebase or squash leftovers; none carries unique content I could find. The one residual risk is the "differs by ~10 lines" hitachi commit; check with `git diff eb53b1bae 8f4b3ddfb` if you want certainty before deleting.

## chat-investor-ui (GitHub Kenzing-Pty-Ltd; main checkout on `feat/cron-only-scheduler`; origin/main last commit 2026-09-24)

| Branch | Commits | Date | Patches upstream | What it holds | Verdict |
|---|---|---|---|---|---|
| twelvedata-triggers | 1 | 2026-03-26 | 0 of 1 | "Preview deployment isolation for scheduled prompts": DATA_TRIGGERS.md (v3 realtime-trigger reference), Vercel deployment-deleted webhook, `lib/deployment.ts`, tests; 9 files, +2026 lines. No same-name remote branch; none of the new files exist on origin/main. Unfinished or unlanded feature. | KEEP |
| feat/monitor-report-split | 2 | 2026-05-28 | 0 of 2 | Two commits on top of the already-pushed origin/feat/monitor-report-split: a `sandbox_state` jsonb column migration (0032) and a 28-row per-user legacy-sandbox rewrite migration (+4042 lines of user-specific mappings). The Monitor/Report split exists on main (run-monitor.ts, run-report.ts), main already has `previous_state` and its own 0032 migration, so these cannot land as written. Cannot tell if the data migration was ever run. | ASK |
| sandbox-code-tool-execution | 1 | 2026-02-05 | 0 of 1 | SANDBOX_DIVERGENCE.md: 239-line analysis of why this branch and main diverged (main rebuilt the sandbox independently). Not on any remote. Reference value only. | ASK |
| scheduled-prompts-refactor | 1 | 2026-05-07 | 0 of 1 | 8-line docs note: preview deploys bake a deploy-specific URL into QStash schedules, so old schedules keep firing at old deploys. Not in main's docs. Small but a real gotcha. | ASK |
| feature/auto-scroll-streaming | 1 | 2025-11-03 | 0 of 1 | Throttled streaming markdown experiment (11 files). Main still has the components this commit deletes; the branch's earlier work is merged. Abandoned experiment. | CULL |
| resume-route-improvements | 1 | 2025-11-12 | 0 of 1 | Resume route logging/reliability; `app/api/chat/resume/` no longer exists on origin/main (resume was removed). | CULL |
| scheduled-prompts-v2 | 3 (2 non-merge) | 2026-03-05..12 | 0 of 2 | SCHEDULED_PROMPTS.md rewrite: identical blob exists on a remote branch. QStash bypass header: superseded by main's lib/qstash/callback-headers.ts. | CULL |
| disable-transport-resume | 1 | 2025-11-12 | 1 of 1 | Upstream. | CULL |
| remove-resume-functionality | 1 | 2025-11-12 | 1 of 1 | Upstream. | CULL |
| feature/reconnect-tool-widgets | 1 | 2025-11-03 | 1 of 1 | Upstream. | CULL |

## Other repos

| Repo | Item | Commits | Date | Patches upstream | What it holds | Verdict |
|---|---|---|---|---|---|---|
| ulysses-link (LogicWolfe) | main-backup | 4 | 2026-02-18..19 | 0 of 4 by patch-id, 4 of 4 by subject | The four early rewrite/rename/TOML/CLI commits; each has a same-subject twin on origin/main (a2d65f6, ef6d2f0, fca8cb2, 138477d). Branch is 22 commits behind main. | CULL |
| SRG (Switch-Batteries) | 2025-11-06-eaip-6c43a | 3 | 2025-11-06 | 3 of 3 | Upstream branch deleted ("gone"); patches already on a remote. | CULL |
| SRG | stash@{0} (WIP on main, 2025-10-31) | n/a | 2025-10-31 | n/a | 11 files, +1118 lines: six TCP-decoding design/validation docs (DIAGNOSTIC_PROPOSALS, PCAP_VALIDATION_*, TCP_DECODING_*, TCP_IP_FILTERING_PLAN), scripts/validate_pcap_protocol.py, plus edits to tcpbus_reader.py. None of the doc/script paths appear in any remote's history; the decoder code has since been refactored upstream. Docs/script are unique; code edits stale. | KEEP |
| wattsworth (Switch-Batteries) | docs-timesheets-reorg | 1 | 2026-04-22 | 0 of 1 | Reorganises timesheets docs (new docs/timesheets.md and plans/timesheets-next.md, removes three plan files; 5 files). Not on dev, which is 20 commits ahead and still has the old plan files. | KEEP |
| wattsworth | log-time-batch-prompts | 1 | 2026-04-22 | 0 of 1 | Batch-entry prompt change; origin/dev has the same behaviour reworded in src/prompt.ts and src/tools/timesheets.ts. | CULL |
| peers (LogicWolfe) | tauri-v2-migration | 1 | 2026-02-13 | 1 of 1 (`git cherry origin/main` shows `-`) | README/CI tweak; already in origin/main. | CULL |
| terraform | stash@{0} (2026-06-29) | n/a | 2026-06-29 | n/a | Only a 21-line `.terraform.lock.hcl`; regenerated by `terraform init`. | CULL |
| terraform-sandbox-runner-auth | stash@{0} (2026-06-29) | n/a | 2026-06-29 | n/a | Same single lock file stash. | CULL |
| veil-voice (worktree of veil, branch `voice`) | uncommitted | 0 unpushed commits | tip c93278b 2026-10-26 | n/a | Confirmed: modified docs/plans/README.md (+5/-1) and docs/plans/data.md (+4), new untracked docs/plans/voice.md (188 lines, "Voice development" design dated 2026-10-26). Tip commit is on origin/main already; `voice` has no upstream. | KEEP (commit and push, as decided) |
| cluster_to_23snaps | main | 1 | 2022-05-18 | n/a (no remote) | Confirmed: clean tree, no remote, single commit "generated with bundle gem" (13 files). lib/ is the empty gem template (`# Your code goes here...`). Author is you. Pushing preserves a blank skeleton only. | KEEP (push, as decided) |

## Summary table

| Repo | Branch / item | Commits | Patches upstream | Verdict |
|---|---|---|---|---|
| hybrid-haul-truck | catalog-schemas-pre-rebase2 | 25 | 24/25 | CULL |
| hybrid-haul-truck | catalog-schemas-pre-rebase | 14 | 12/13 | CULL |
| hybrid-haul-truck | route-naming-refactor-backup | 20 | 17/20 | CULL |
| hybrid-haul-truck | agent-telemetry-reviewed-06e38ac90 | 14 | 3/9 (rest landed reworked) | CULL |
| hybrid-haul-truck | agent-telemetry-restack-182 | 6 | 3/6 (rest landed reworked) | CULL |
| hybrid-haul-truck | config-draft-session | 11 | 6/8 (rest landed) | CULL |
| hybrid-haul-truck | draft-session-backup | 11 | 6/8 (same tip as above) | CULL |
| hybrid-haul-truck | preview-terraform-substrate | 8 | 0/7 (landed in #182) | CULL |
| hybrid-haul-truck | preview-config-tier | 2 | 0/2 (landed #175) | CULL |
| hybrid-haul-truck | catalog-battery-schema-fixes | 3 | 0/3 (landed #167) | CULL |
| hybrid-haul-truck | preview-database-ownership-guard | 1 | 1/1 | CULL |
| hybrid-haul-truck | preview-environments | 1 | 0/1 (superseded) | CULL |
| hybrid-haul-truck | hitachi-bev-dev-verified | 1 | 0/1 (landed 8f4b3ddfb) | CULL |
| hybrid-haul-truck | slow-tests | 1 | 1/1 | CULL |
| chat-investor-ui | twelvedata-triggers | 1 | 0/1 | KEEP |
| chat-investor-ui | feat/monitor-report-split | 2 | 0/2 | ASK |
| chat-investor-ui | sandbox-code-tool-execution | 1 | 0/1 | ASK |
| chat-investor-ui | scheduled-prompts-refactor | 1 | 0/1 | ASK |
| chat-investor-ui | feature/auto-scroll-streaming | 1 | 0/1 | CULL |
| chat-investor-ui | resume-route-improvements | 1 | 0/1 | CULL |
| chat-investor-ui | scheduled-prompts-v2 | 3 | 0/2 (superseded) | CULL |
| chat-investor-ui | disable-transport-resume | 1 | 1/1 | CULL |
| chat-investor-ui | remove-resume-functionality | 1 | 1/1 | CULL |
| chat-investor-ui | feature/reconnect-tool-widgets | 1 | 1/1 | CULL |
| ulysses-link | main-backup | 4 | 0/4 by id, 4/4 by subject | CULL |
| SRG | 2025-11-06-eaip-6c43a | 3 | 3/3 | CULL |
| SRG | stash@{0} | stash | n/a | KEEP |
| wattsworth | docs-timesheets-reorg | 1 | 0/1 | KEEP |
| wattsworth | log-time-batch-prompts | 1 | 0/1 (landed reworded) | CULL |
| peers | tauri-v2-migration | 1 | 1/1 | CULL |
| terraform | stash@{0} | stash | n/a | CULL |
| terraform-sandbox-runner-auth | stash@{0} | stash | n/a | CULL |
| veil-voice | voice (uncommitted files) | 3 files | n/a | KEEP (commit+push) |
| cluster_to_23snaps | main | 1 | n/a (no remote) | KEEP (push) |

Counts: KEEP 5 (twelvedata-triggers, SRG stash, docs-timesheets-reorg, veil-voice, cluster_to_23snaps), ASK 3, CULL 25.

## Commands for approval (not run)

Preservation first. Pushing to the Kenzing and Switch-Batteries orgs adds branch noise, so these use bundles for org repos; the bundles live outside the repos.

```sh
mkdir -p ~/Rescue/bundles

# KEEP: chat-investor-ui twelvedata-triggers (bundle, full history of that branch)
git -C ~/repos/chat-investor-ui bundle create ~/Rescue/bundles/chat-investor-ui-keep.bundle twelvedata-triggers

# KEEP: SRG stash (stash commit bundled as a ref)
git -C ~/repos/SRG bundle create ~/Rescue/bundles/srg-stash-2025-10-31.bundle refs/stash

# KEEP: wattsworth docs reorg (one-commit docs branch; bundle rather than push)
git -C ~/repos/wattsworth bundle create ~/Rescue/bundles/wattsworth-docs-timesheets-reorg.bundle docs-timesheets-reorg

# ASK items, if you decide to keep them (add to the chat-investor-ui bundle or make a second one)
git -C ~/repos/chat-investor-ui bundle create ~/Rescue/bundles/chat-investor-ui-ask.bundle feat/monitor-report-split sandbox-code-tool-execution scheduled-prompts-refactor

# KEEP: veil-voice commit and push (decided)
git -C ~/repos/veil-voice add docs/plans/README.md docs/plans/data.md docs/plans/voice.md
git -C ~/repos/veil-voice commit -m "Add voice development plan and link it from the plan index"
git -C ~/repos/veil-voice push -u origin voice

# KEEP: cluster_to_23snaps push (decided). The git.pod.haus repo must exist first (create it in Forgejo); URL assumes the LogicWolfe owner as veil uses.
git -C ~/repos/cluster_to_23snaps remote add origin git@git.pod.haus:LogicWolfe/cluster_to_23snaps.git
git -C ~/repos/cluster_to_23snaps push -u origin main
```

CULL list (`-D` is required because these are not merged by ancestry). Run after the bundles verify (`git bundle verify <file>`):

```sh
# hybrid-haul-truck (shared by all four worktrees; run once)
git -C ~/repos/hybrid-haul-truck branch -D catalog-schemas-pre-rebase2 catalog-schemas-pre-rebase route-naming-refactor-backup agent-telemetry-reviewed-06e38ac90 agent-telemetry-restack-182 config-draft-session draft-session-backup preview-terraform-substrate preview-config-tier catalog-battery-schema-fixes preview-database-ownership-guard preview-environments hitachi-bev-dev-verified slow-tests

# chat-investor-ui
git -C ~/repos/chat-investor-ui branch -D feature/auto-scroll-streaming resume-route-improvements scheduled-prompts-v2 disable-transport-resume remove-resume-functionality feature/reconnect-tool-widgets

# others
git -C ~/repos/ulysses-link branch -D main-backup
git -C ~/repos/SRG branch -D 2025-11-06-eaip-6c43a
git -C ~/repos/wattsworth branch -D log-time-batch-prompts
git -C ~/repos/peers branch -D tauri-v2-migration
git -C ~/repos/terraform stash drop
git -C ~/repos/terraform-sandbox-runner-auth stash drop
# after the SRG stash bundle is verified:
git -C ~/repos/SRG stash drop
```

Since the repos will be recloned anyway, none of the deletes is actually needed on the Air; the list only matters if you keep using these checkouts.

## Not determined

- chat-investor-ui feat/monitor-report-split: whether the 28-row legacy sandbox migration was ever run against production. Only you or the database can say.
- hybrid-haul-truck hitachi-bev-dev-verified: ~10 lines of difference from the upstream twin were not read line by line.
- Remote refs are as of the last fetch; I did not fetch, so anything pushed since is not reflected.
