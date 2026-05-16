# Cutover

Decision recorded in the [index](index.md): **hard swap, no dual-ship.**
Alloy is repointed in one change; VictoriaLogs is left
*stopped-but-intact* as the rollback until ClickStack is trusted, then
decommissioned. This page is the ordered sequence and the rollback.

Every mutating step (`komodo-sync`, deploy, `git push`, `tf apply`)
**requires explicit authorization** — this page is the plan, not a
licence to execute. `tf plan` is fine unprompted.

## Why the order matters

Two hard constraints force the sequence:

1. **The ingestion key doesn't exist until HyperDX has booted**
   ([Stack & storage](clickstack-stack.md)). Alloy can't be repointed
   before ClickStack is up and the key is in 1Password.
2. **The default 3-day TTL is silently wrong**
   ([Retention & storage](retention-and-storage.md)). The TTL must be
   corrected *before* it's the only log store, or there's a window
   where logs are being retained for 3 days and we think it's 90/180.

So ClickStack must be fully stood up, keyed, and TTL-corrected
*while VL is still the live store*, and only then does the swap happen.

## Sequence

**Phase A — stand up ClickStack alongside live VL (non-disruptive)**

1. 1Password: create `ClickStack session secret`,
   `ClickStack ClickHouse password` (and `ClickStack Mongo` if auth
   chosen). `komodo-op` syncs them.
2. Land `clickstack/compose.yaml` + `clickstack/stack.toml` (dockernet,
   local-NVMe data dirs, resource caps, healthchecks, autoheal —
   [Stack & storage](clickstack-stack.md)). `komodo-sync` + deploy.
   VL is untouched and still serving; nothing ingests into ClickStack
   yet.
3. arm64 pre-flight already passed (blocking gate from
   [Stack & storage](clickstack-stack.md)) — if it didn't, stop here.
4. HyperDX first-run: create the `nathan` admin account (decision 5),
   confirm it reaches ClickHouse and Mongo.
5. **Correct the TTL now** — set the collector exporter `ttl` and/or
   `ALTER TABLE … MODIFY TTL` on the auto-created
   `otel_logs`/`otel_traces`/`otel_metrics_*`
   ([Retention & storage](retention-and-storage.md)). Verify with
   `SHOW CREATE TABLE`.
6. Capture the HyperDX-generated ingestion key into the 1Password
   `ClickStack ingestion key` item. `komodo-op` syncs it to the
   `OP__KOMODO__*` variable.

**Phase B — the hard swap**

7. The new Alloy configs are **already authored and validated**, staged
   as `logging/bilby/alloy-conf/config.alloy.clickstack` and
   `logging/kangaroo/alloy-conf/config.alloy.clickstack` (NOT named
   `config.alloy` — that would hot-reload the live Alloy and cut over
   prematurely, since the dir is bind-mounted and Alloy watches it).
   `gatus/conf/config.yaml` already has `metrics: true`; the
   `CLICKSTACK_INGESTION_KEY` env passthrough is already in
   `logging/compose.shared.yaml`. The cutover action is therefore
   purely mechanical: on each host
   `mv config.alloy config.alloy.victorialogs.bak && mv
   config.alloy.clickstack config.alloy`, and add the ingestion-key
   `[[VAR]]` (`CLICKSTACK_INGESTION_KEY=[[OP__KOMODO__CLICKSTACK_INGESTION_KEY__CREDENTIAL]]`)
   to both `logging` overlays' `stack.toml` `environment` blocks.
8. (Gatus `metrics: true` already landed — no action.)
9. `komodo-sync` + redeploy `logging` (both hosts) and `gatus`. The
   redeploy (not just the file rename) is required so Alloy restarts
   with `CLICKSTACK_INGESTION_KEY` in its environment. **This is the
   cutover instant** — from here Alloy ships only to ClickStack; VL
   stops receiving but is still running and queryable. Rollback =
   reverse the two `mv`s + redeploy.
10. Validate against the checklists in
    [Ingestion pipeline](ingestion-pipeline.md) and
    [Gatus metrics](gatus-metrics.md): live `flood`/`op-connect-api`
    lines with JSON extracted, ANSI stripped, `rtorrent-cleanup`
    distinct, kangaroo logs present, Gatus series queryable, Postmark
    alert chain still firing.

**Phase C — Cloudflare / UI swap**

11. `cloudflare/` Terraform: add a **new** `watch.pod.haus` ingress →
    HyperDX `http://hyperdx:8080`; set HyperDX
    `FRONTEND_URL`/`HYPERDX_APP_URL` to `https://watch.pod.haus`. The
    `*.pod.haus` Family Access app already covers it — no new Access
    app. **`logs.pod.haus` is left pointing at VL untouched** — VL
    stays queryable at its existing URL through the entire soak, which
    makes the A–C rollback even cleaner (no ingress revert needed).
    `tf plan` first (unprompted OK); `tf apply` needs authorization.
12. Confirm `watch.pod.haus` serves HyperDX through the tunnel + Access
    + HyperDX's own login.

**Phase D — soak, then decommission (only after trust)**

VL stays stopped-but-intact through the soak. Rollback during A–C is
trivial (below). Once ClickStack is trusted (a representative soak —
includes at least one nightly Backrest run capturing the new Mongo
dump, [Backup & DR](backup-and-dr.md)):

13. Stop and remove `victoria-logs` from `logging/bilby/compose.yaml`.
14. Retire Grafana entirely ([Gatus metrics](gatus-metrics.md)):
    remove the `grafana` service + `grafana-data` volume +
    `grafana-provisioning` bind from `logging/bilby/compose.yaml`;
    delete the dead `logging/bilby/grafana-provisioning` dashboards.
15. `cloudflare/` Terraform: remove the `logs.pod.haus` (VL vmui) and
    `grafana.pod.haus` ingress + DNS + Access policy entries (both
    retire together now that VL and Grafana are gone; `watch.pod.haus`
    is the only observability hostname). `tf plan` → authorized
    `tf apply`.
16. Backrest (`backup/bilby/compose.yaml` + `config.json.tmpl`): remove
    the `/mnt/jump/victoria-logs` bind and the `logging_grafana-data`
    external volume + bind and their plan entries; **add** the
    `clickstack` Mongo-dump plan ([Backup & DR](backup-and-dr.md)).
17. Reclaim `/mnt/jump/victoria-logs` on Jump (~0.4 GB actual today,
    not the 50 GB cap — negligible, and irrelevant to the NVMe budget).
18. Docs: rewrite `docs/monitoring.html` (Grafana gone, HyperDX +
    Gatus-metrics in); add `docs/runbooks/clickstack.html` (DR runbook
    skeleton in [Backup & DR](backup-and-dr.md)); update
    `docs/backup-and-recovery.html`, `docs/storage.html`
    (clickstack on local NVMe + Jump reclamation),
    `docs/stack-conventions.html` key-files table, and the
    `AGENTS.md` / docs index. Mark this plan's status accordingly.

## Rollback

- **During A–C, before step 13:** VL is still running with all its
  data. Revert the two `alloy-conf` files + `gatus/conf/config.yaml` to
  the `loki.write`/no-metrics state, `komodo-sync` + redeploy
  `logging`/`gatus`. **No TF revert needed** — `logs.pod.haus` was
  never touched, so VL is back in service at its existing URL the
  moment Alloy points at it again. The only loss is the gap of lines
  that went to ClickStack during the swap (acceptable per the
  hard-swap decision — the risk explicitly accepted over dual-ship).
- **After step 13 (VL removed):** no longer a config revert — VL would
  have to be redeployed and would come back empty (its data dir may
  have been reclaimed in step 17). This is why steps 13–17 are gated on
  *trust*, not a fixed clock. Do not run Phase D until the soak +
  one good Mongo backup are in hand.

## Pitfalls specific to this cutover

- **Forgetting step 5 (TTL).** The single highest-consequence quiet
  failure in the whole plan. Logs silently 3-day-retained while
  everyone assumes 90/180. It is in Phase A *before* the swap on
  purpose.
- **Header format for the ingestion key.** Wrong `authorization` form →
  silent 401 → empty HyperDX with no obvious error. Verify against
  HyperDX's API-keys help text at step 6
  ([Ingestion pipeline](ingestion-pipeline.md)).
- **`FRONTEND_URL` mismatch.** HyperDX behind the tunnel with the wrong
  app URL breaks login/cookies. Set it in step 11, test in 12.
- **Mongo lost before first backup.** Steps 13–17 gated on at least one
  validated Mongo dump in restic *and* OneDrive
  ([Backup & DR](backup-and-dr.md)) — otherwise a DR event between
  cutover and first backup loses every dashboard/alert and forces the
  ingestion-key regeneration dance.
- **Resource regression.** If ClickHouse destabilises bilby under real
  load ([Stack & storage](clickstack-stack.md)), that surfaces during
  the Phase D soak — which is exactly why VL stays intact until then.
  A resource finding is grounds to halt and consult, not to push
  through.
