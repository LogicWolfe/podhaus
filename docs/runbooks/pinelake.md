# Pinelake

> **Offline since 2026-10-14.** The host is powered down for an extended stay.
> [While the host is offline](#while-the-host-is-offline) lists the three
> settings that hold the fleet steady without it and the order to undo them.

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

Three settings, all in this repo, make an offline pinelake cost nothing. Each
carries a comment pointing back here.

1. **The Komodo server is disabled**: `enabled = false` in
   `komodo/sync/servers.toml`. Core stops polling it, marks it `Disabled`,
   closes the open unreachable alert, and reports its stacks as `unknown`, which
   the `Komodo stacks` check does not count as unhealthy.
2. **The never-deployed `pinelake-tunnel` stack is out of the sync**: its
   definition is `tunnel/pinelake/stack.toml.offline`. The sync reads only
   `.toml` files, so the rename hides it, and the stack was deleted from Komodo
   by hand because the podhaus sync never deletes resources on its own. Nothing
   was lost: it had never deployed. The other pinelake stacks stay in the sync;
   they have deployed before and no-op while their files are untouched.
3. **The twelve pinelake Gatus checks are disabled**: each has
   `enabled: false` with the comment `pinelake is offline`.

While these are in place, **do not edit files under a pinelake stack's content
hash** (`pinelake/`, the pinelake overlays, `tunnel/pinelake/`): the push deploy
would try to deploy the changed stack to the disabled host and fail. Make those
edits after the host is back, or accept a red `Komodo procedures` check until
then.

## Bringing the host back

Power the host on and let OrbStack and Periphery start. Then, in one push:

1. Set `enabled = true` on the pinelake server in `komodo/sync/servers.toml`.
2. Rename `tunnel/pinelake/stack.toml.offline` back to `stack.toml`. The push
   deploy's sync stage recreates the `pinelake-tunnel` stack and its deploy
   stage full-deploys it, since it is new to Komodo.
3. Delete the twelve `enabled: false  # pinelake is offline` lines from
   `gatus/conf/config.yaml`; `grep -n 'pinelake is offline'` finds them.
4. Strip the Gatus push plumbing the other hosts lost while pinelake was
   away (docs/plans/gatus-dead-mans-switches.md): the two `wget … GATUS_`
   hooks in `backup/pinelake/config.json.tmpl`, the three `GATUS_*` lines in
   `backup/pinelake/stack.toml`, the `GATUS_RAR_ENDPOINT_ID` line in
   `pinelake/flood/compose.yaml`, and then the three `GATUS_*` placeholder
   references in `backup/compose.shared.yaml`'s `backrest-init` environment,
   which exist only so the env lint tolerates pinelake's declarations. Until
   this is done the hooks push to endpoints that no longer exist and log a
   Backrest error each night, which the *Backrest Pinelake Nightly* check
   reports.
5. Push, then check komodo.pod.haus → Servers shows pinelake `Ok` and the
   `Komodo procedures` check is green.

Expect a burst of Gatus "resolved" alerts from the heartbeat checks as their
first pushes land. Komodo's update history keeps a few `pinelake-tunnel`
deploys stuck at `InProgress` from pushes made while the host was off; they
are inert and need no cleanup.
