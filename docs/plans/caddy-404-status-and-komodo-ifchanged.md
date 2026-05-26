# Two related defects from the Caddy 404 fix attempt

Surfaced 2026-05-26 trying to make `nathanbaxter.com/<missing-path>`
return HTTP 404 instead of HTTP 200. Both issues are open.

## 1. Caddy 404-status preservation for proxied-from-bucket misses

### Goal

When a request to `nathanbaxter.com/some-missing-page` hits Caddy, we
want:

- **Body:** the styled `404.html` page from the `nathanbaxter-com`
  MinIO bucket.
- **Status:** `HTTP 404`.

The styled body lands fine. The status is `HTTP 200` because the
inner `reverse_proxy minio:9000` call that fetches `404.html` from
MinIO writes its successful 200 over whatever the outer handler set.

### What we tried

| Attempt | Caddyfile structure | Result |
|---|---|---|
| Original (pre-fix) | `handle_response @missing { rewrite; reverse_proxy }` inside outer reverse_proxy | 200 with body — current production state |
| `replace_status` inside `handle_response` | Added `replace_status 404` after the inner proxy | Caddyfile parse error: `unrecognized directive: replace_status` inside `reverse_proxy` block |
| `handle_errors 404 { … }` + `error 404` raised from `handle_response @missing` | New top-level handler | Body lands, status still 200 |
| `replace_status` inside `handle_errors` | Added inside `handle_errors` block | Caddyfile parse error: `unrecognized directive: replace_status` inside `handle_errors` |

Confirmed Caddy 2.11.3 has `http.handlers.intercept` compiled in
(`caddy list-modules | grep intercept`), so the `replace_status`
directive exists at the JSON level — it just isn't accepted in the
Caddyfile subhandler contexts we tried.

### Current production state

The Caddyfile uses the `handle_errors 404 + error 404` structure
without `replace_status`. Status is still 200 for missing paths.
Functionally equivalent to the original handler — the rewrite has
moved into the error path, no other change. Crawlers and uptime
monitors will continue to see 200s for genuine misses until this is
solved.

### Things still to try

1. **`replace_status` at the route/site level with a vars matcher
   that targets the `{http.error.status_code}` variable.** This pulls
   `replace_status` out of any subhandler context, which is where it
   keeps getting rejected. Likely shape:

   ```
   @from_404_error vars {http.error.status_code} 404
   replace_status @from_404_error 404
   ```

   placed at site level. Need to validate the var is in scope when
   `replace_status` runs.

2. **JSON config instead of Caddyfile.** Switch the caddy stack from
   Caddyfile to a `caddy.json` mount. The `intercept` handler exposes
   richer replacement semantics in JSON than the Caddyfile adapter
   currently surfaces, including conditional `replace_status` ops.

3. **Switch to file_server + try_files.** Pre-sync `404.html` into a
   local volume on the Caddy host (or build it into the caddy image)
   so we can do `try_files {path} =404` style logic without the
   reverse_proxy stomping on the status. Loses the
   bucket-is-source-of-truth property — every site deploy would need
   to also push the 404 to the host filesystem.

4. **Accept the 200.** The page is correctly styled, crawlers that
   read `<meta name="robots" content="noindex">` on the 404 page
   handle it fine, and uptime monitors usually probe specific known
   paths. Cost is some SEO signal hygiene. Worth it vs. ongoing
   investigation time? Maybe.

The branch order above is roughly the order of effort. (1) is the
lightest experiment.

## 2. Komodo `DeployStackIfChanged` no-op'd on `caddy` despite content change

### Symptom

Pushed `caddy/Caddyfile` change at `04f26eb`. `podhaus-push-deploy`
procedure fired and completed successfully:

- Stage 0 RunSync — ok
- Stage 1 `RunAction podhaus-inject-content-hashes` — ok
- Stage 2 `BatchDeployStackIfChanged "*"` — `DeployStackIfChanged
  caddy` queued and reported success
- Stage 3 RestartStack ofelia — ok

`caddy` container did not recreate. `docker ps` still showed
`Up 28 hours`. The same was true for an earlier in-session push
(`b37792d`, the Publii→nathanbaxter rename) which also touched
`caddy/Caddyfile` (comment only). Two pushes in a row, both with
Caddyfile changes, neither produced a caddy recreate.

Workaround used: direct `DeployStack` API call against `caddy`
forced the recreate. Container restart timestamp confirmed.

### What we know

- The action `podhaus-inject-content-hashes` enumerates stack dirs
  from Komodo Core's view of `/syncs/podhaus`. The hash is supposed
  to cover every file in the stack dir.
- Other stacks recreate correctly via the same mechanism on the same
  procedure runs (`nathanbaxter-deploy` notably did, and earlier
  `vpn-diagnostics` did).
- The Stage 2 log shows `DeployStackIfChanged caddy` was *executed*,
  not skipped. It returned success without redeploying — meaning the
  IfChanged check returned "unchanged".

### Hypotheses

- The hash injected by the Action and the hash already present in
  caddy's stored env happen to match because of how the diff is
  computed against a stale baseline.
- The Caddyfile-only change generates a hash that collides with the
  previously stored one (extremely unlikely with sha256-truncated
  hashes).
- The Action's directory walk for `caddy/` is excluding the
  Caddyfile for some reason (e.g., path filtering, mode check). The
  lint script in `tools/lint-stack-content-hash.py` checks the
  *consumer* side; the *producer* (the Action that actually hashes)
  is implicit.

### Investigation steps

1. **Diff the env that the Action writes for `caddy` between two
   runs.** Add a `RunCommand` action that dumps caddy's stored env
   after Stage 1 and before Stage 2. Compare the
   `STACK_CONTENT_HASH` value across runs that touched the
   Caddyfile.
2. **Read the Action source.** It's in `komodo/sync/actions.toml`.
   Confirm it actually walks the entire stack dir (including
   `Caddyfile` which has no extension and no `compose` in the path).
3. **Test on another stack.** Push a comment-only change to a
   different non-build stack (e.g. `docs-server`) and see if its
   IfChanged also no-ops or correctly recreates.
4. **Check `DeployStackIfChanged` semantics in Komodo source.** Per
   `AGENTS.md`, the check compares rendered env to deployed env;
   confirm what "deployed env" actually points at in Komodo's
   storage when a stack was last DeployStack'd vs. last
   DeployStackIfChanged'd.

### Workaround until fixed

Force-deploy caddy directly when Caddyfile changes are pushed:

```
curl -X POST http://localhost:9120/execute \
  -H "X-Api-Key: $K" -H "X-Api-Secret: $S" \
  -d '{"type":"DeployStack","params":{"stack":"caddy"}}'
```

Or temporarily add caddy to a force-deploy list in
`podhaus-push-deploy` until root cause is known.

### Severity

The Caddyfile change at `04f26eb` lost ~1.5 minutes between push and
the manual force-deploy. The earlier comment-only change at
`b37792d` was cosmetic and the silent no-op went unnoticed at the
time. This becomes serious if a future Caddyfile change is
behavior-affecting AND not caught by visual smoke-tests after push.
