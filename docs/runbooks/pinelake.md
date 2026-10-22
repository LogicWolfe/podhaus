# Pinelake

Pinelake is the Apple M1 Mac mini media appliance in the second household:
Plex, Flood, Syncthing, Backrest, ingress, logging, scheduling and Autoheal, all
as Komodo stacks on OrbStack. Its Periphery agent, wstunnel client and Alloy
dial out to Numbat; nothing reaches it inbound. The host page in
[Hosts](../hosts.html#pinelake) covers the machine; this page covers how Komodo
and Gatus treat it.

## Where things are defined

| Thing | Where |
|---|---|
| The Komodo server | `komodo/sync/servers.toml`, `[[server]] name = "pinelake"` |
| Its clone of this repo | `komodo/sync/repos.toml`, `podhaus-pinelake` |
| Its stacks | `pinelake/*/stack.toml` (plex, flood, syncthing, ofelia, periphery), the pinelake overlays under `autoheal/`, `backup/`, `caddy/`, `logging/`, and `tunnel/pinelake/` |
| Its Gatus checks | `gatus/conf/config.yaml`, every endpoint named `Pinelake …` or `… (pinelake, via Komodo)` |

## How the fleet sees an unreachable host

Komodo polls every enabled server. An unreachable one raises a CRITICAL
`ServerUnreachable` alert that stays open until the host answers, and the
`Komodo Alerts` Gatus check is red for as long as any CRITICAL alert is open, so
one dead host hides every other CRITICAL.

The podhaus push deploy's last stage runs `BatchDeployStackIfChanged` over every
stack. A stack that has deployed before is compared by content and left alone
when nothing under it changed, so an unreachable host costs nothing on pushes
that do not touch its files. A stack that has never deployed has no content to
compare, so Komodo full-deploys it on every push; with the host unreachable that
deploy fails, and the procedure, and the `Komodo procedures` check, fail with it.
The batch pattern cannot leave a stack out (wildcards and regexes only, no
negation), so a never-deployed stack on an offline host has to leave the sync.

The Gatus checks that read pinelake through Komodo get a 500 on every poll while
the host is away, and the heartbeat checks expire. They stay red, and each one
sends a "resolved" alert when the host returns.

## While the host is offline

Two settings, both in this repo, make an offline pinelake cost nothing. Give
each a comment pointing back here.

1. **Disable the Komodo server**: `enabled = false` on the pinelake server in
   `komodo/sync/servers.toml`. Core stops polling it, marks it `Disabled`,
   closes the open unreachable alert, and reports its stacks as `unknown`, which
   the `Komodo stacks` check does not count as unhealthy.
2. **Disable the twelve pinelake Gatus checks**: give each `enabled: false`
   with the comment `pinelake is offline`.

Every pinelake stack has deployed before, so each no-ops while its files are
untouched. A pinelake stack that has never deployed would full-deploy on every
push and fail; hold its `stack.toml` out of the sync by renaming it (the sync
reads only `.toml` files) and delete the stack from Komodo by hand, since the
podhaus sync never deletes resources on its own.

While the host is offline, **do not edit files under a pinelake stack's content
hash or compose text**: `pinelake/`, the pinelake overlays, `tunnel/pinelake/`,
the shared `compose.shared.yaml` files those overlays combine with, and the
extra paths in each stack's `x-podhaus-content-paths` (`flood/`,
`logging/alloy-modules/`, `tunnel/launcher/`). The push deploy would try to
deploy the changed stack to the disabled host and fail. Make those edits after
the host is back, or accept a red `Komodo procedures` check until then.

## Bringing the host back

Power the host on and let OrbStack and Periphery start. Then, in one push:

1. Set `enabled = true` on the pinelake server in `komodo/sync/servers.toml`.
2. Delete the `enabled: false  # pinelake is offline` lines from
   `gatus/conf/config.yaml`; `grep -n 'pinelake is offline'` finds them.
3. Rename any held-out `stack.toml` back. The push deploy's sync stage
   recreates the stack and its deploy stage full-deploys it, since it is new
   to Komodo.
4. Push, then check komodo.pod.haus → Servers shows pinelake `Ok` and the
   `Komodo procedures` check is green.

The push deploy redeploys every pinelake stack whose files changed while the
host was away. Expect a burst of Gatus "resolved" alerts as the heartbeat
checks see their first pushes.
