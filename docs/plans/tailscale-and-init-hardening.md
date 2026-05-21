# Tailscale + init-container hardening

Bundle of small, related cleanups around the tailnet management plane
and the init-container convention. Each item is independently shippable
— no ordering dependency.

## Status

**NOT STARTED.** All items below are deferred follow-ups surfaced
during the kookaburra cattle-rebuild work (2026-05-21). Current state
(daemon.json + MagicDNS FQDN, tailscale-cleanup init, OAuth client
scope) is captured in `/docs/networking.html`, `/docs/hosts.html`,
`/docs/secrets.html`, and `/docs/komodo.html` — read those first.

## Items

### 1. Tailscale auth-key 90-day rotation loop

**Problem.** `op://Homelab/Tailscale Auth Key` is used by every
tailscale stack (`tailscale/bilby/`, `tailscale/kookaburra/`) and by
`kookaburra_bootstrap`. The key has a 90-day expiry; the current key
expires `2026-11-17`. Already-enrolled nodes keep working
(`keyExpiryDisabled: true` on each device), so the system shows no
warning until a *new or rebuilt* node tries to register past the
expiry — at which point a rebuild silently can't enrol.

**Fix.** Build a rotation loop using the existing `Tailscale OAuth
Client` (already scoped `auth_keys:write`):

- A scheduled job mints a fresh reusable, tag-bound (`tag:podnet`),
  key-expiry-disabled auth key via the OAuth client.
- Writes the new key back to the `Tailscale Auth Key` 1P item via the
  1Password CLI (using the service-account token already on bilby).
- Trigger cadence: monthly. Ofelia label on a small init container
  feels right (same pattern as the existing scheduled jobs in
  `ofelia/conf/`).

**Verification.** After cycle, rebuild kookaburra → `terraform apply
-replace` + `kookaburra_bootstrap` should enrol successfully end-to-end
using the freshly-minted key.

**Reference scope:** `auth_keys:write` on the OAuth client (already
granted; verify before relying on it).

### 2. Init-tools shared image: add curl + jq

**Problem.** `tailscale/compose.shared.yaml`'s `tailscale-cleanup`
service uses `alpine:3.20` directly and `apk add curl jq` at runtime,
because `init-tools/Dockerfile` (the convention-mandated shared init
image) only ships `gettext` + `python3`. This is the only exception
to the "all init containers use `init-tools:local`" rule documented in
`/docs/stack-conventions.html`.

**Fix.** Extend `init-tools/Dockerfile`:

```dockerfile
FROM alpine:latest
RUN apk add --no-cache gettext python3 curl jq
```

Then convert `tailscale-cleanup` in `tailscale/compose.shared.yaml`:

- Replace `image: alpine:3.20` with `image: init-tools:local` +
  inline `build:` (same pattern as plex's init).
- Drop the `apk add --no-cache --quiet curl jq` line from the
  entrypoint script — tools are baked in.
- Add `run_build = true` to `tailscale/{bilby,kookaburra}/stack.toml`
  (matches plex/backup pattern).

**Verification.** First post-change deploy: confirm `init-tools:local`
gets rebuilt with the new tools on each Periphery, `tailscale-cleanup`
runs in <5s without apk overhead, and the tailnet API call still
succeeds.

**Side effect.** Existing init containers (plex preferences merge,
flood directory init, backup init) inherit curl + jq in their
`init-tools:local` image — small image size bump (~5 MB), unused
until something needs them. Acceptable.

### 3. bilby tailscale stack name

**Problem.** Asymmetric naming:

- bilby's stack: `tailscale` (bare)
- kookaburra's stack: `kookaburra-tailscale`

The kookaburra-* pattern is meaningful (push-deploy Stage 2 force-deploy
target). bilby's stack rides Stage 1's `BatchDeployStackIfChanged "*"`,
so it doesn't need the `bilby-` prefix to function — but the asymmetry
is mildly confusing to a reader scanning the fleet.

**Fix options.**

- **(a) Rename to `bilby-tailscale`.** Touches `tailscale/bilby/stack.toml`
  (`name = "bilby-tailscale"`), nothing else. Cosmetic-only. Komodo
  would deploy a new stack-record under the new name; the old `tailscale`
  record would need a manual delete via the UI/API after the rename to
  avoid leaving a phantom.
- **(b) Leave as-is.** `tailscale` (bare) is fine because bilby is
  the implicit primary; the `<host>-` prefix only matters where there's
  a host disambiguation need. Document the convention in
  `/docs/komodo.html` and move on.

**Pick.** Probably (b) — the asymmetry isn't load-bearing, and (a)
risks a Komodo state-tracker hiccup during the rename. Worth ~30
seconds in `/docs/komodo.html` to call out "bare stack name = bilby
(primary host); `<host>-` prefix only on linked-repo hosts."

### 4. Verify bilby tailscale-cleanup on a real ghost

**Problem.** The cleanup init was proven on the kookaburra side
(it deleted `kookaburra-podnet-1`). The bilby side runs the exact same
code path with `TS_HOSTNAME=bilby-podnet`, but no `bilby-podnet` ghost
ever existed to test against. Same code, same OAuth creds, very low
risk it doesn't work — but unverified.

**Fix.** Manufacture and resolve a test ghost:

1. In Tailscale admin, find a recently-removed-and-recreated node
   that could trigger a ghost (or temporarily create one by `docker
   volume rm tailscale_tailscale-state` after stopping bilby's
   tailscale — destroys the machine identity).
2. Bring tailscale back up — new `bilby-podnet-1` appears, old
   `bilby-podnet` goes offline.
3. Wait >60s, redeploy `tailscale` stack on bilby (`komodo-sync` or
   manual DeployStack).
4. Confirm the init container's logs show "deleting stale device
   bilby-podnet …" + the ghost is gone in the admin.

**Risk.** This intentionally takes down the bilby tailnet node
briefly. During that window: Komodo Core can't reach kookaburra
Periphery, alloy log shipper paused, etc. Do during the 04:00 AWST
maintenance window per `feedback_dead_time_window.md`.

### 5. Cleanup-init resilience to API outage

**Problem (latent).** The init is best-effort — any OAuth/API error
becomes a warning and `exit 0`, never blocking the tailscale service.
This is correct behaviour but not tested. A genuine Tailscale API
outage would let a stale-ghost rebuild silently produce a `-N` suffix,
and the next successful deploy would self-heal — but only if the
operator knows to redeploy.

**Fix.** Add a one-line log signal at the END of `tailscale-cleanup`
that reports the count of devices considered vs deleted:

```
echo "[tailscale-cleanup] done — considered=$considered deleted=$deleted"
```

So a log search of `tailscale-cleanup` always shows the latest run's
state, and a count of `considered=0` + a known ghost in the admin is
the silent-failure signal.

**Optional.** Add a Gatus heartbeat fed by the cleanup container —
init containers don't normally have outbound HTTP, but a simple
`curl -sS https://gatus.../api/v1/endpoints/...` at the end would
flip a Gatus check red on persistent silence.

## Out of scope

- The TF foundation consolidation (`docs/plans/terraform-foundation.md`).
  Separate plan; not blocking any of the above.
- `pinelake-migration/`. Future host; will inherit whatever shape
  these items leave behind.

## Verification (whole plan)

End state to confirm:

- A droplet rebuild past day 90 of the auth key enrols successfully
  with no manual key intervention (item 1).
- `tailscale/compose.shared.yaml`'s `tailscale-cleanup` uses
  `init-tools:local` and the entrypoint has no `apk add` line
  (item 2).
- `/docs/komodo.html` documents the `tailscale` (bare) vs
  `<host>-tailscale` naming convention (item 3, if pick is (b)).
- `bilby-podnet` ghost cleanup verified once on bilby (item 4).
- A grep for `tailscale-cleanup` in logging always shows a run with
  `considered=` + `deleted=` counts (item 5).
