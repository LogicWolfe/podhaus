# Grasshopper button design

Four Flic buttons in grasshopper, a 4-year-old's room. This file exists to
stop the design drifting. **It is Nathan's spec, not a proposal.** Do not
substitute alternatives, do not add gestures, do not propose hardware.

## The design

**Three** Flic buttons, covering four jobs.

| Button | Light | Short press | Long press |
|---|---|---|---|
| Blue | Nanoleaf grasshopper lamp | Toggle on/off | Change colour |
| Green | Hue bookshelf lamp | Toggle on/off | Change colour |
| Black | ESP32 LED strip / all three | Toggle the strip | Start **crazy mode** |

Crazy mode's core: **a series of changing lights over a period of time, with
some randomization.** It has **no cancel** — it runs its 30 seconds and ends
itself, so the hold only ever means "start".

**Rearranged 2026-08-15**, when the room went from four buttons to three. The
strip moved onto black's short press and crazy mode onto black's hold. One
consequence, accepted rather than overlooked: **toggling the strip mid-show
does not stick**, because the show captures the strip's state at the start and
restores it at the end. The press still does something visible at the time,
which is the rule that actually matters here.

The rearrangement cost **nothing on Apple's side**: the Shortcuts are
triggered by the request booleans, not by buttons, so which Flic raises a
boolean is invisible to them.

## Settled constraints — do not relitigate

- **The LED strip is an on/off pink strip and nothing else.** It has no
  colour and no brightness. What the ESP32 is *capable* of is irrelevant;
  the strip is not a fancy device. It needs exactly one gesture, which is why
  it fits alongside crazy mode on black. This has been raised and rejected
  twice.
- **Use what is already in the house.** The goal is not to buy hardware to
  make a specific thing work. No purchases.
- **Determinism is not a goal.** Rapid pressing leading to unclear outcomes
  is fine. Rapid pressing leading to *nothing happening* is the failure.
  The 4-year-old's mission is to make stuff happen.
- **The Nanoleaf stays owned by Apple Home**, driven through the relay in
  `home-assistant/config/packages/grasshopper_lamp.yaml`. Adopting it into
  HA would cost Apple Home, the Nanoleaf app and its on-bulb effects; that
  trade has been considered and is not being taken.
- **Flic reliability is already handled.** The integration's missing
  reconnect path has a plan of its own and is not part of this work.
  Battery wear from heavy pressing is a battery swap, not a design input.

## State

**Everything is built** — the Home Assistant side in this repo, and all three
Apple Shortcuts in the Home app.

- **Green** — the bookshelf lamp, entirely HA-driven. **Confirmed working in
  the real world** (as blue, before the swap). Short press toggles, hold
  cycles blue → red → blue+red.
- **Blue** — the Nanoleaf, both request booleans bridged, both Shortcuts
  authored. The palette cycle is **confirmed working in the real world** (as
  green, before the swap): reading → pink → blue → green.
- **Black** — short press toggles the strip. Hold raises the crazy flag; the
  flag, both scripts and every automation are live, and the Nanoleaf's
  Shortcut is authored, so all three lights should join in.

Deployed 2026-08-14 (`5ad84bd`); rearranged 2026-08-15.

**Not yet exercised end to end:** crazy mode has never actually been run —
that flickers a child's room for 30 seconds, so it wants a deliberate moment
rather than a deploy-time smoke test. The Nanoleaf's beat interval is
untested, and it is the piece most likely to disappoint: every step is a hub
round trip and the bulb fades rather than snaps.

### The Shortcuts, all of them in the Home app

| Shortcut | Trigger | Does |
|---|---|---|
| Lamp colour | `Grasshopper lamp next colour` turns on | Read hue/sat, set the next palette entry |
| Lamp toggle | `Grasshopper lamp toggle` turns on | Read power, set the opposite |
| Crazy Nanoleaf | `Grasshopper crazy mode` turns on | Loop colours while the flag stays on |

**Trap, paid for once.** The palette cycle is a chain of nested
`If`/`Otherwise` branches, and the **innermost `Otherwise` is the wrap-around**
— the branch that takes the last palette entry back to the first. Leaving it
empty does not fail loudly: the cycle works until it reaches that colour and
then stops dead there permanently, because every subsequent press lands in the
same empty branch. Symptom is "it changed colour once and now the button does
nothing". Check the terminal `Otherwise` has an action before debugging
anything else.

The palettes and the loop live inside these Shortcuts, in Apple's closed
database, and are **not** recoverable from git. Rebuilding this house means
re-authoring all three by hand.

## The Nanoleaf relay: move the loop to Apple's side

Researched 2026-08-14. The relay is slow **per round trip** — HA boolean →
HomeKit bridge → HomePod automation engine → HAP over Thread → bulb, where
Apple's automation engine is the dominant, undocumented, untunable term.

The fix is not a faster round trip. It is **fewer of them.** A Home automation
converted to a Shortcut runs *on the hub*, and the hub-executable action set
includes `If`, `Wait`, `Repeat`, `Random Number`, `Control Home`, and
`Get the status of Home` (which reads Brightness, **Hue**, **Saturation** and
Power State). Only third-party apps, user input and displaying results are
excluded.

So HA fires **one** boolean meaning "do the thing", and the HomePod runs the
loop locally against the bulb. Latency is paid once, at the trigger.

Consequences:

- **Toggle needs no HA state.** `Get the status of Home` → `If` on → turn off,
  else on. HA never guesses at power, so **the one-way drift problem
  disappears** — the earlier stateful-boolean design existed only because HA
  could not observe the bulb, and Apple's side can.
- **Colour needs no palette in HA.** The shortcut reads hue/saturation and
  steps or randomises on Apple's side. No scene count to settle, no
  one-boolean-per-colour.
- **Crazy mode runs on the hub**: `Repeat` + `Random Number` + `Wait`, with no
  bridge in the path after the trigger.

That reduces the whole Nanoleaf surface to **three momentary booleans** —
toggle, colour, crazy — with no HA-side state.

Precedent: HomeKit users cycle colours from Onvis Thread buttons using `If` on
saturation and hue thresholds. Same shape as this.

### Colour selection: fixed palette cycle — decided

The shortcut reads the bulb's hue and saturation, works out which palette
entry it is on, and sets the next. **Chosen over random**, which needs no
state but re-rolls the current colour roughly one press in N — and a press
that changes nothing is the one outcome this design must not produce.

Authoring notes, each of which has a documented failure behind it:

- **Test saturation before hue.** A bulb in colour-temperature (white) mode
  has meaningless hue. This is how the Onvis-button users handle it.
- **Convert with `Get Numbers from Input` before comparing.** An iOS 15 bug
  made if-statements always evaluate false when triggered automatically
  rather than run by hand; fixed in 15.1, but the conversion remains the
  reliable shape.
- **Every branch sets hue, saturation AND brightness**, so a change is always
  visibly a change rather than a washed-out or dim version of one.
- **Every branch also turns the light on**, so a long press on an off lamp
  comes on in the next colour instead of silently recolouring a dark bulb.
- **Include a default branch** for a bulb reporting outside every band. It
  jumps to palette entry 1 — still a visible change, never a no-op.

`Control Home` taking a *computed* hue is unconfirmed (the one Apple thread
asking went unanswered), but the palette approach never needs it: colours are
picked in the UI per branch.

**Palette size costs nothing in HA** — it is purely how much tapping the
Shortcuts editor takes. HA is one boolean whether it is three colours or ten.

Cost: the shortcuts are hand-authored in Apple's closed database, more
intricate than plain automations, and not in git. The DR story gets worse.

### Crazy mode: hub-side loop, cancelled by an out-of-band flag

Same shape as toggle and colour — HA fires one trigger, the HomePod runs the
loop. HA stays ignorant of the bulb.

**Cancel via a dedicated stateful `input_boolean` (`grasshopper_crazy_active`),
bridged to Apple Home**, which the shortcut reads at the top of each iteration.
Checking whether the *light* is off does **not** work: crazy mode wants periods
with the light off, so "off" cannot also mean "stop".

Why this shape earns its keep:

- HA regains the one piece of state it legitimately owns — whether the show is
  running — without knowing anything about the bulb.
- Cancellation is symmetric: the same flag stops HA's Hue and strip loops, so
  the room stops together rather than half-stopping.
- Overlapping runs become impossible. The trigger is an off→on edge on a
  stateful boolean, so there is no edge to fire while the show runs, which
  sidesteps the undocumented question of how Apple treats a re-trigger during
  a `Repeat`.
- The Nanoleaf's Shortcut needs to *read* the flag once per iteration, which a
  momentary boolean could not survive long enough to allow. This is the reason
  it is stateful; the rest is consequence.

**Hub shortcuts are killed at 10 minutes** (Apple TV 4K / HomePod; reportedly
unreliable past ~7; the limit is a deliberate anti-infinite-loop measure). Keep
the show to 2-3 minutes — a light show that stops on its own is the better toy
anyway — and the timeout becomes a safety net rather than a constraint.

**HA must clear the flag on its own timer.** A hub-side kill cannot clear
anything, so trusting the shortcut to finish would leave the flag stuck on and
crazy mode permanently untriggerable.

Black's long press **raises** the flag and nothing else — there is no cancel
gesture. The gesture therefore stays absolute: pressing it repeatedly can only
ever mean "start", which is what keeps the button safe to hammer.

That makes the timer the flag's only owner, and so a single point of failure:
an HA restart during its delay would drop it and strand the flag on forever.
`initial: off` on the boolean is what closes that, and it is the only reason
that key exists.

Unknown, and a test rather than a search: the floor on the beat interval. Each
pass is `Get status` → `If` chain → `Control Home` through the hub, so the real
period is `Wait` plus execution. The bulb also fades rather than snaps, so a
fast beat may read as a wash rather than distinct steps.

## Colours

**Saturation is the whiteness axis.** A Hue bulb looks washed out because
something sent low saturation or a colour temperature, not because the hue was
wrong. Every colour below is full saturation; nothing in this room should ever
set a partial one.

Hue bulbs have a narrower gamut than sRGB, so "100% blue" renders as the most
saturated blue the bulb can physically produce. Expected, not a fault.

### Blue button (Hue bookshelf lamp) — normal cycle

Three entries, sent as `rgb_color` rather than converted through HS:

| Entry | RGB |
|---|---|
| Full blue | `[0, 0, 255]` |
| Full red | `[255, 0, 0]` |
| Blue + red | `[255, 0, 255]` |

Long press advances and **turns the light on**, so a press from off comes on in
the next colour rather than recolouring a dark bulb.

### Crazy mode palette (Hue)

Eight entries, evenly spread, saturation 100 throughout — no white is
reachable:

| Colour | Hue | | Colour | Hue |
|---|---|---|---|---|
| Red | 0 | | Cyan | 180 |
| Orange | 25 | | Blue | 240 |
| Yellow | 50 | | Purple | 280 |
| Green | 110 | | Magenta | 320 |

## Crazy mode: the animation

**30 seconds**, all three lights running **independent** random intervals — the
architecture forces this (HA cannot drive the Nanoleaf), and the resulting
drift between the three is the more interesting result anyway.

- **Strip** — binary, HA-driven, crisp, and **twice everyone else's rate**: on
  for a random **0.25–1.5s**, off for a random **0.25–0.5s**, roughly 24
  flashes in 30s. Speed is the only variable it has, so it gets all of it. It
  can afford the command rate because it is an ESPHome light on the native
  API — a local socket write, not a bridge round trip. Captures its prior
  state in a script variable and restores it at the end. **Not**
  `scene.create`.
- **Hue** — on for a random **0.5–3s**, off for a random **0.5–1s**, about
  twelve flashes, a new palette colour each on-phase.
- **Nanoleaf** — same intent, but see the caveats below.

The per-light iteration caps in `scripts.yaml` are backstops against a failed
timer, and are sized against the **fastest** possible run rather than the
average — otherwise the cap quietly becomes the duration control and one light
stops early while the rest of the room carries on.

30s is nowhere near the 10-minute hub ceiling, so that constraint drops out.

### Nanoleaf caveats for the animation

- **It will not flicker crisply.** Every on/off is a hub round trip and the
  bulb fades rather than snaps, so at 0.5s on-times it reads as pulsing or
  breathing. It will not match the other two.
- **Random wait durations may not be expressible.** Whether `Wait` accepts a
  variable is unresolved, same open question as computed colour. Fallback:
  `Random Number` → branch → one of several fixed `Wait` lengths. Works with
  confirmed capabilities, bloats the shortcut.
- Its colours must come from hand-authored `If` branches. Worth testing
  whether `Run Shortcut` is hub-executable — a single shared "set palette
  entry N" shortcut, called by both the blue-button cycle and the crazy
  animation, would mean authoring the palette once instead of twice.

## Open

- **Crazy mode has never been run.** Everything else here is confirmed
  against the real room; this is not.
- The Nanoleaf's beat interval — `Wait` plus hub execution time, floor
  unknown. If it reads as a wash rather than distinct steps, slow it down
  rather than trying to make the hub faster.
- Real round-trip latency of `Get status` → `If` → `Control Home` on the hub.
