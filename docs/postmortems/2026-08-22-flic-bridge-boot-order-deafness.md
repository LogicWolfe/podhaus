# 2026-08-22 — Flic buttons dead for two days after a boot-order race

**Status:** Resolved
**Severity:** Medium
**Trigger:** hard power reset of Bilby

## Summary

The same power reset covered in
[2026-08-22 — Delayed NFS recovery](2026-08-22-delayed-nfs-container-recovery.md)
also killed the Flic buttons, and that half went unnoticed for two days.

Bilby rebooted while the Pi Zero was not yet reachable. Home Assistant came up
at 08:15:11, tried to dial flicd at `10.0.0.77:5551`, got
`[Errno 113] Host is unreachable`, and gave up permanently. The built-in `flic`
platform is set up exactly once: it catches only `ConnectionRefusedError`, never
raises `PlatformNotReady`, and so Home Assistant never scheduled a retry. All
three buttons were dead from that moment.

The Pi was power-cycled by hand at 19:06 that evening. It made no difference
and could not have: flicd was healthy the entire time, and the broken half was
on Bilby. That is the detail that made the fault confusing from the outside —
the device you can see and touch was working, and the fix was on the other host.

The recovery sweep after the outage found nothing wrong. Flic is not a
container and not a Gatus endpoint, so a closeout that reported all containers
healthy, all five Komodo hosts `Ok` and 44 of 45 Gatus endpoints green was
simultaneously true and blind to this. Discovery came from a person pressing a
button two days later.

Restarting Home Assistant restored service immediately. The permanent fix
inverts the direction of the bridge so there is no cross-host connection left
to go stale.

## Timeline

Times AWST. Boot times are derived from `uptime` and journal timestamps.

| Time | Event |
|---|---|
| 2026-08-22 ~08:11 | Bilby reboots after the power reset. |
| 2026-08-22 08:15:11 | Home Assistant starts, dials flicd, logs `Error while setting up flic platform for binary_sensor: [Errno 113] Host is unreachable`. Buttons dead from here. The error proves the Pi was unreachable at this instant. |
| 2026-08-22 19:06 | Pi Zero power-cycled by hand. flicd starts, logs `Successfully bound HCI socket`, and serves normally — with no client connected. No effect on Home Assistant. |
| 2026-08-22 → 08-24 | Buttons dead. No log line, no alert, no failed healthcheck. |
| 2026-08-24 ~08:20 | Reported: buttons still not working after the Pi power cycle. |
| 2026-08-24 08:26 | Pi inspected: flicd `active`, radio bound, but `ss -tn` shows **no connection on 5551**. Fault localised to Bilby. |
| 2026-08-24 08:28 | `docker restart home-assistant`. Connection re-established within 15s; all three buttons re-register. Service restored. |
| 2026-08-24 08:50–09:02 | Push-based bridge built, cut over with no further Home Assistant restart, and tested against flicd restart, flicd crash, unreachable Home Assistant, and two Pi reboots. |

## Root cause

Four defects compounded. The first two are upstream, the third is ours, the
fourth is why it lasted two days.

**1 — No setup retry.** `homeassistant/components/flic/binary_sensor.py`
constructs `pyflic.FlicClient(host, port)` inside a `try` that catches only
`ConnectionRefusedError`. A host that is down raises `OSError` (errno 113)
instead, which is not caught. Nothing raises `PlatformNotReady`, which is the
only mechanism that makes Home Assistant retry a platform. Note the caught
branch is no better: it logs and `return`s, equally permanently.

**2 — No reconnect.** The client's event loop runs as
`threading.Thread(target=client.handle_events).start()` — a bare thread. In
`pyflic`, `handle_events` is `while not self._closed: if not
self._handle_one_event(): break` followed by `self._sock.close()`. When the
socket drops it simply returns and the thread exits, with no log line at all,
and the docstring records that "any use of this FlicClient is illegal"
afterwards. The integration has no reload service and its manifest carries
`"codeowners": []` and `"quality_scale": "legacy"`.

Together these mean **a full Home Assistant restart was the only recovery**, and
only one boot ordering ever survived:

| Event | Self-heals? |
|---|---|
| Bilby reboots, Pi already up and flicd listening | yes |
| Bilby reboots, Pi down or still booting | no — errno 113, setup aborts |
| Bilby reboots, Pi up but flicd not yet listening | no — connection refused, quiet return |
| Pi reboots while Home Assistant is up | no — thread exits silently |
| `systemctl restart flicd` | no — same |
| Wifi or LAN blip long enough to drop the TCP session | no — same |

**3 — No signal.** The bridge was observable only by pressing a button. It has
no container, no healthcheck and no Gatus endpoint, so it was absent from the
post-outage audit rather than failing it. Five of the six rows above produce no
log line whatsoever.

**4 — A deferral recorded as a completion.** `docs/plans/grasshopper-buttons.md`
carried this under a heading reading *"Settled constraints — do not
relitigate"*:

> **Flic reliability is already handled.** The integration's missing reconnect
> path has a plan of its own and is not part of this work.

The gap was correctly identified. The plan it promises was never written — no
such file exists in `docs/plans/` and none appears anywhere in the history. So
the one durable note about this defect asserted it was handled and instructed
readers not to revisit it.

## Impact

- All three Flic buttons (blue, green, black) and the six automations bound to
  them were dead for approximately 48 hours.
- No data loss. flicd, the BLE links and `/var/lib/flicd/flicd.db` were healthy
  throughout; no button needed re-pairing.
- One ineffective manual recovery (the Pi power cycle), which pointed away from
  the real fault rather than toward it.

## Resolution

**In-repo**

- [x] **2026-08-24**: Added `iot/pizero/flic-pusher` — a stdlib-only daemon that
      holds the flicd connection on **localhost** and POSTs each press to a Home
      Assistant webhook. It carries no retry logic: losing flicd means exiting
      non-zero so systemd starts a fresh process against a fresh flicd.
- [x] **2026-08-24**: Added `iot/pizero/flic-pusher.service` with
      `StartLimitIntervalSec=0`, so a burst of exits during a flicd restart
      cannot park the unit in permanently-failed — the trap that kept
      `mnt-jump.automount` down for fourteen hours on 2026-05-30.
- [x] **2026-08-24**: `iot/pizero/flicd-install` now installs, enables and
      asserts the pusher, refusing to proceed when `/etc/flic-pusher.env` is
      absent rather than inventing a webhook id.
- [x] **2026-08-24**: `home-assistant/config/packages/flic.yaml` replaced: the
      `binary_sensor: platform: flic` block is gone, and a webhook-triggered
      automation re-fires `flic_click` with byte-identical event data, so the
      six button automations are unchanged.

**Host**

- [x] **2026-08-24**: `/etc/flic-pusher.env` written on pizero (mode 0600);
      `flic_webhook_id` added to `/var/lib/home-assistant/secrets.yaml` on
      Bilby. Neither is in the checkout.
- [x] **2026-08-24**: Legacy cross-host connection retired and the three
      orphaned `binary_sensor.flic_*` entity-registry entries removed. Only a
      loopback connection to 5551 remains.

**Docs**

- [x] **2026-08-24**: `docs/runbooks/pizero.md` rewritten around the push
      bridge.
- [x] **2026-08-24**: The false "already handled" claim in
      `docs/plans/grasshopper-buttons.md` corrected to point here.
- [x] **2026-08-24**: `home-assistant/config/http.yaml` rewritten. Its comment
      described `trusted_proxies` as trusting "the cloudflared/dockernet
      gateway … behind the Cloudflare Tunnel", which has not been true since
      the Tunnel was removed. The **value is correct and unchanged** — Caddy
      reaches host-network Home Assistant across the dockernet gateway
      (`reverse_proxy @home 172.18.0.1:8123`) from a dynamic address inside
      172.18.0.0/16, so the subnet is the only expressible form. The comment now
      records what consumes the client IP, which newly includes this
      postmortem's own webhook (`local_only`), and names the spoofing trade-off.

**Cleanup**

- [x] **2026-08-24**: Webhook id stored in the 1Password Homelab vault as
      **Home Assistant flic webhook** (first attempt was refused; the `op-vault
      dev` grant gained item-create access later the same day).
- [x] **2026-08-24**: Deleted `/var/lib/private/flicd` on pizero — a **0-row**
      bond database orphaned by the abandoned `DynamicUser` unit on 2026-08-14.
      `flicd-install` removes the `/var/lib/flicd` symlink that unit left but
      never removed what it pointed at. The live database (3 buttons) was
      untouched and verified afterwards.
- [x] **2026-08-24**: Removed the stock `some_password: welcome` placeholder
      from Bilby's `/var/lib/home-assistant/secrets.yaml`. Unreferenced
      anywhere in the config; it shipped with Home Assistant's default install
      and had sat there since 2024-10-31.

**Open**

- [ ] Commit the repo changes and reconcile Bilby's working checkout, which is
      diverged from `origin/main` with 61 modified files (see *Out of scope*).

## What we learned

- **A long-lived TCP session between two hosts needs supervised reconnect, or
  it needs to not exist.** The fix was not to add retry logic to the session
  but to delete the session: the daemon now talks to flicd over loopback where
  systemd can supervise it, and each press is an independent stateless POST.
  There is no ordering of reboots that can leave that half-connected, so the
  failure class is gone rather than handled.
- **"Recovery is: restart the whole hub" is a design smell, not a runbook
  step.** It was tolerable only because nobody had counted how many ordinary
  events triggered it. Six did.
- **A health sweep scoped to containers and endpoints will report green over a
  dead non-container integration.** The 2026-08-22 closeout was accurate and
  still missed this. Same shape as the
  [Turn Touch BLE wedge](2026-08-09-turn-touch-ble-link-wedge.md), where the
  metrics existed and nothing consumed them.
- **A deferral written as a completion is worse than no note.** "Already
  handled … has a plan of its own", filed under "do not relitigate", is the
  single reason this defect survived being noticed. Defer by recording what is
  still broken, not by asserting it is covered.
- **Test the failure mode you claim to fix.** Rebooting the Pi to verify the
  new bridge immediately exposed a real bug: the unit had been started but never
  enabled, so it would not have come back on boot — reintroducing the exact
  fault under repair. Inspection would not have caught it; the reboot did.

## Out of scope

- **Monitoring and alerting.** Deliberately declined for now. The bridge no
  longer has a state that can go stale, so the remaining risk is a Pi that is
  simply off — which the buttons themselves make obvious. If an alert is wanted
  later, a heartbeat POST carrying flicd's per-button connection status would
  cover both this and the Turn Touch gap.
- **Bilby's working checkout.** It is diverged from `origin/main` (13 commits
  behind, plus local commits) with 61 modified files. This matters here because
  `home-assistant/config` is bind-mounted into the container from that checkout
  via `PODHAUS_CHECKOUT`, so it is the live source of Home Assistant's config.
  The `home-assistant/` subtree itself is clean and its `flic.yaml` was
  byte-identical to the committed version before this change, so the edit was
  safe — but the wider divergence is untouched and needs a deliberate
  reconciliation.
- **Narrowing `trusted_proxies` below the whole dockernet subnet.** Home
  Assistant takes CIDRs, not container names, so trusting only Caddy would mean
  pinning it to a static dockernet address — against the "reach containers by
  name" rule in `AGENTS.md`, and a symptom of the flat dockernet trust domain
  in [`../plans/tech-debt.md`](../plans/tech-debt.md) rather than anything
  specific to Home Assistant. Left as is; the comment now explains why.

## Related

- [2026-08-22 — Delayed NFS recovery left containers and jobs stopped](2026-08-22-delayed-nfs-container-recovery.md)
  — same power reset, different latent defect.
- [2026-08-09 — Turn Touch BLE link wedge](2026-08-09-turn-touch-ble-link-wedge.md)
  — the same "no signal for a device-side bridge" gap.
- [2026-05-30 — Power outage NFS recovery](2026-05-30-power-outage-nfs-recovery.md)
  — source of the `StartLimitIntervalSec=0` lesson applied above.
- [`docs/runbooks/pizero.md`](../runbooks/pizero.md)
- Upstream: `homeassistant/components/flic/binary_sensor.py` (`quality_scale:
  legacy`, no codeowner) and `pyflic==2.0.4`.
