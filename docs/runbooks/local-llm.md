# Local model service

A language model that runs on fractal's graphics card (GPU) and answers
coding clients such as Claude Code and pi at `llm.pod.haus`. The GPU belongs to
Nathan's Windows desktop, so the service's main job is to get out of the way: a
watcher unloads the model the moment a Windows game starts using the GPU and
loads it again once the GPU has been quiet for a while.

It is the Komodo stack `fractal-llm` (`llm/`), deployed to fractal through the
linked repo `podhaus-fractal`. fractal is a Fedora guest under WSL2; Docker
there reaches the GPU through NVIDIA's container toolkit, which Ansible installs
(see [Host provisioning](../host-provisioning.md) and [Hosts](../hosts.html#fractal)).

Terms used below:

- **Router**: the llama.cpp server in router mode. It starts with no model and
  supervises a separate *model process* that it starts and stops on request.
- **Slot**: one of four independent conversation lanes in the model process, so a
  main conversation and three subagents never wait for one another.
- **Pool**: the one token budget the four slots share (`ctx-size`).
- **Yield**: unload the model so a game can have the whole GPU. **Resume**:
  load it again.
- **Hold**: a stretch after the Yield button during which the model stays away.

## Where things are defined

| What | Where |
|---|---|
| The three containers, their memory limits, the watcher's settings | `llm/compose.yaml` |
| Komodo stack | `llm/stack.toml` (`fractal-llm`, on server `fractal`) |
| Model server settings and the chat templates | `llm/server/models.ini`, `llm/server/*.jinja` |
| Watcher | `llm/watcher/` (standard-library Python; start with `state.py`) |
| Setup page, `llm-token` sign-in command, install scripts, `claude-podhaus` launcher, pi extension | `caddy/fractal/llm-setup/` (served at `/setup/`; part of the `fractal-caddy` stack) |
| Tests | `llm/tests/` for the service; `caddy/fractal/tests/test_caddyfile.py` for the loopback and LAN listeners, running the real Caddyfile with stand-in upstreams; `caddy/fractal/tests/` for the setup page: `test_client_setup.py` (the install scripts and `claude-podhaus` against a stand-in `llm.pod.haus`, the page's contents, the public Pomerium route), `setup-page.test.ts` (the page's sign-in script under Node, with stand-in browser objects) and `podhaus.test.ts` (the pi extension's sign-in under Node). All run by `tools/pre-commit`. |
| Listeners, exposed paths, the `/setup/` files, request log | `caddy/fractal/Caddyfile`, `caddy/fractal/compose.yaml` |
| The three `llm.pod.haus` routes (setup, control, model) | `pomerium/config.yaml` |
| DNS record and Pocket ID client | `terraform/services_pod_haus.tf`, `terraform/pocket_id.tf` (`pocketid_client.llm_token`, whose one callback is the setup page) |
| Log parsers | `logging/alloy-modules/llm-server.alloy`, `llm-watcher.alloy`, `caddy.alloy` |
| Metric scrapes | `logging/fractal/alloy-conf/config.alloy` |
| Alerts | `gatus/conf/config.yaml`, group `Local model` |

## The three containers

| Container | What it does | Limits |
|---|---|---|
| `llm-model` | One-shot job. Makes sure the model file is in the `llm-models` volume and matches its checksum, then exits. Runs on the shared `init-tools` image. | `mem_limit` 1g, `restart: "no"` |
| `llm-server` | llama.cpp in router mode (`ghcr.io/ggml-org/llama.cpp:server-cuda13`, not pinned). Serves the model on dockernet port 8080 and publishes no port. Gets the GPU. | `mem_limit` 17g, `memswap_limit` 18g, `oom_score_adj` 1000 |
| `llm-watcher` | Owns who holds the GPU: samples GPU use once a second, tells the router to unload or load the model, serves the control page, metrics and health check on dockernet port 8081. Gets the GPU so that `nvidia-smi` works in it. | `mem_limit` 256m |

`llm-server` and `llm-watcher` start only after `llm-model` has exited
successfully, so a deploy that cannot produce a verified model file stops there.
The watcher also waits for the server's health check to pass.
`ignore_services = ["llm-model"]` in `stack.toml` keeps Komodo from counting
the exited job as an unhealthy stack.

## How a request reaches the model

```text
client ─ https://llm.pod.haus ─▶ Numbat Pomerium ─ rathole fractal_http ─▶ fractal-caddy :4443 ─▶ llm-server :8080
client on fractal ─ http://127.0.0.1:8085 ───────────────────────────────▶ fractal-caddy :8085 ─▶ llm-server :8080
Fenwick on bandicoot ─ http://fractal.pod.haus:8086 ─────────────────────▶ fractal-caddy :8086 ─▶ llm-server :8080
```

- **Remote path.** `llm.pod.haus` is a DNS-only A record to Numbat's application
  address. Pomerium has two routes for the name (below), forwards to
  `127.0.0.1:8444` on Numbat, and the `fractal_http` rathole service carries it
  over mutual TLS to fractal's Caddy. The model route allows 10 minutes without
  traffic and 30 minutes in total, because a long prompt is read in silence for
  minutes before the first byte and an answer can stream for many minutes.
- **Local path.** On fractal itself Caddy also listens on port 8085, published on
  fractal's loopback only. It has no sign-in: anything running on fractal can
  use it, including the control page's buttons.
- **LAN path.** Fenwick on bandicoot reaches Caddy's port 8086 across the home
  LAN, with no sign-in. It serves the model paths alone, never the control or
  setup pages. Caddy answers 403 to every address but bandicoot's
  (`BANDICOOT_LAN_IPV4`, from `config/lan-addresses.json`), and Windows' Hyper-V
  firewall admits the port from the home network. The port is published on every
  interface because fractal's LAN address exists in the guest only under WSL's
  mirrored networking, and a bind to an absent address would stop the whole
  `fractal-caddy` container. See [fractal's Windows-side
  settings](../hosts.html#fractal-windows).
- **Routes.** Pomerium sends the five installer files under `/setup/` (the two
  install scripts, the token command, the Claude Code launcher and the pi
  extension) to a public route with no sign-in, so `curl | sh` works from a
  bare terminal; the rest of `/setup` and below, the page itself, to a route
  that admits members of Pocket ID's `family` and `friends` groups by browser
  sign-in; and `/control` and below to a route that admits only Nathan's email.
  Everything else goes to a route that admits the same two groups on the
  bearer token described in the next section. Group membership is Pocket ID's
  to say.

The signed-in and loopback listeners serve only these paths, and the LAN
listener only the first row. Everything else is 404.

| Paths | Go to |
|---|---|
| `/v1/chat/completions`, `/v1/completions`, `/v1/messages`, `/v1/messages/count_tokens`, `/v1/models` | `llm-server:8080` (OpenAI and Anthropic formats) |
| `/control` and `/control/*` | `llm-watcher:8081`. On the remote listener Caddy also requires the caller's email, passed by Pomerium as `X-Pomerium-Claim-Email`, to be Nathan's. |
| `/setup` | A redirect to `/setup/` |
| `/setup/` and `/setup/*` | Files in `caddy/fractal/llm-setup/`, mounted with the rest of `caddy/fractal/` at `/etc/caddy` |

The server's management paths (load, unload, slots, metrics, health) and the
watcher's own `/metrics` and `/healthz` are not exposed. Only the watcher may
load or unload the model, so on the model paths Caddy also drops the query
string, sends every body as JSON, and removes `X-Conversation-Id`: the router
would otherwise let a request load the model through an `autoload` parameter,
and a second request naming the same conversation cancels the first one's
answer.

The model's id on the API is `qwen3.8-27b`.

## Setting up a client

Command-line clients have no browser session, so they send a Pocket ID access
token as their API key. The setup page, `https://llm.pod.haus/setup/`, hands
out such a token and sets up Claude Code and pi to fetch their own. It shows:

- **The key**: a Pocket ID access token, masked, with a copy button. It works
  as the API key in either request format. It is valid for a year (see "What
  Pomerium does with a token" below).
- **Claude Code**: `curl -fsSL https://llm.pod.haus/setup/claude.sh | sh`, after
  which `claude-podhaus` starts Claude Code on the local model.
- **pi**: `curl -fsSL https://llm.pod.haus/setup/pi.sh | sh`, then `/login
  podhaus` and `/model` inside pi.
- **Manual setup**: download links for the token command, `claude-podhaus` and the
  pi extension; Claude Code's environment, whose copy button fills in the key;
  the base addresses of the two request formats (`https://llm.pod.haus` for
  Anthropic's, `https://llm.pod.haus/v1` for OpenAI's); the model name; and the
  no-key address on fractal itself, `http://127.0.0.1:8085`.

Pomerium serves the page behind the friends policy, so opening it means the
usual Pocket ID sign-in first; only the installer files it links are public,
and none of them holds a secret. The page then signs in by itself, in the
browser, through Pocket ID's authorization-code grant with PKCE on the token
command's client `llm-token`, which admits only the `family` and `friends`
groups, because Pomerium cannot hand its own Pocket ID token to a browser. The
sign-in's state and PKCE verifier stay in the tab's session storage for the
round trip to Pocket ID and are removed on return, the code is cleared from the
address before it is exchanged, and the token is kept only in the page's
memory, so a reload signs in again and shows a new key. The page leaves for
Pocket ID by replacing itself, so Back does not return to it. Nothing in the
returned address is used until its state matches the one the tab sent, and an
error code is then shown in fixed words ("Access denied", "Pocket ID
unavailable", otherwise "Sign-in failed"), never as the address's own text,
because anyone can write an error into a link. The client's callback is
`https://llm.pod.haus/setup/`, so the page signs in only there: opened on
fractal's loopback listener it returns to `llm.pod.haus` and reports "Sign-in
expired", and Retry then works. It suits Linux, macOS and WSL; the token command
needs `fcntl`, which native Windows lacks.

The page also gives Cursor's settings: the key as the OpenAI API key, the base
URL override `https://llm.pod.haus/v1`, and `qwen3.8-27b` as a custom model.
Cursor's own servers make the requests, not the laptop, which is why the key
has to be pasted rather than fetched by a command. Only Cursor's chat panel
uses a custom endpoint; Tab and
inline edits stay on Cursor's models, the override applies to every key Cursor
holds, and custom keys need Cursor Pro.

### What `/setup/` serves

The files are in `caddy/fractal/llm-setup/`.

| Path | File | What it does |
|---|---|---|
| `/setup/` | `index.html` | The page. Static, and loads nothing from elsewhere. |
| `/setup/claude.sh` | `claude.sh` | Needs `curl` and nothing else, and stops before writing anything otherwise. Installs the token command as `~/.local/bin/llm-token` and the launcher as `~/.local/bin/claude-podhaus`, mode 755, each replacing any older copy once it has downloaded whole. Warns if `~/.local/bin` is not on `PATH` or `claude` is not installed. Then runs `llm-token` once with the token discarded, so the first sign-in link appears in the terminal during the install and is approved in the browser already open; a refused sign-in fails the install. Ends by printing how to start: `claude-podhaus`, or its full path when `~/.local/bin` is not on `PATH`. |
| `/setup/claude-podhaus` | `claude-podhaus` | Runs `llm-token` with the token discarded, so a sign-in that has run out shows its link before Claude Code takes the screen, then starts `claude` with `--settings '{"apiKeyHelper":"~/.local/bin/llm-token"}'`, the environment below, and every argument passed through. Claude Code runs `apiKeyHelper` through `sh`, whose tilde expansion yields the home directory whole, so a home directory holding spaces, quotes or backslashes needs no quoting. |
| `/setup/pi.sh` | `pi.sh` | Needs `curl`. Installs the pi extension as `podhaus.ts` in pi's extensions directory, `$PI_CODING_AGENT_DIR/extensions/` (pi's own setting; `~/.pi/agent/extensions/` when unset), mode 644, and touches nothing else of pi's. Warns if `pi` is not installed. |
| `/setup/podhaus.ts` | `podhaus.ts` | The pi provider extension `podhaus`, which signs in through pi's `/login`. When `LLM_POD_HAUS_URL` is fractal's loopback listener it registers the fixed key `local` instead and needs no sign-in. |
| `/setup/llm-token` | `llm-token` | The token command, below. |

Both install scripts are written to be piped into `sh`. The shell then reads the
script from standard input, so they never read it themselves, and everything
runs from a function called on the last line, so a download cut short runs
nothing. `LLM_POD_HAUS_URL` replaces `https://llm.pod.haus` in all three
scripts, as it does in the pi extension: the installers download from
`$LLM_POD_HAUS_URL/setup/`, and `claude-podhaus` sends Claude Code there. The name
is this service's alone, because a generic one could already be set for another
tool, whose server would then be sent a fresh key.

Claude Code's environment, as `claude-podhaus` sets it and the page lists it:

| Variable | Value |
|---|---|
| `ANTHROPIC_BASE_URL` | `https://llm.pod.haus`, or `LLM_POD_HAUS_URL` |
| `ANTHROPIC_API_KEY` | Empty |
| `ANTHROPIC_AUTH_TOKEN` | The key, in the page's manual setup. `claude-podhaus` unsets it and gives the token command as `apiKeyHelper` instead, which Claude Code runs again when a request is refused. Claude Code prefers `ANTHROPIC_AUTH_TOKEN`, then `ANTHROPIC_API_KEY`, then `apiKeyHelper`, which is why the first is unset and the second empty. |
| `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL`, `ANTHROPIC_DEFAULT_HAIKU_MODEL`, `ANTHROPIC_DEFAULT_FABLE_MODEL` | `qwen3.8-27b` |
| `CLAUDE_CODE_MAX_CONTEXT_TOKENS` | `150000`, the window the service is sized for |
| `CLAUDE_CODE_EXTRA_BODY` | `{"chat_template_kwargs":{"reasoning_effort":"medium"}}`. The server otherwise runs every request at the model's highest effort, whatever Claude Code's own thinking settings say: 74 s against 50 s on a small measured task. |
| `CLAUDE_CODE_DISABLE_TERMINAL_TITLE` | `1` |
| `CLAUDE_CODE_ENABLE_PROMPT_SUGGESTION` | `false` |
| `CLAUDE_CODE_TOTAL_TOKENS_REMINDER` | `off`. With the two above, no side requests for the terminal title, prompt suggestions or token reminders, each of which would take a slot. |

When `LLM_POD_HAUS_URL` starts with `http://127.0.0.1` (fractal's loopback listener,
which has no sign-in), `claude-podhaus` skips the token command and sets
`ANTHROPIC_AUTH_TOKEN=local`, because Claude Code must send some key.
`CLAUDE_PODHAUS_COMMAND` names the command `claude-podhaus` starts in place of
`claude`, for a wrapper that selects an account or adds flags; Nathan's
chezmoi `claude-qwen` runs `claude-auto` this way.

### The token command

`caddy/fractal/llm-setup/llm-token` produces a token from a command line. It is
POSIX sh over `curl` and `sed`, so it runs as it is on any Linux or macOS
machine; `claude.sh` installs it as `~/.local/bin/llm-token`. Its tests,
`caddy/fractal/tests/test_token_command.py`, run it whole against a stand-in
`curl`.

- It prints the token on standard output and nothing else. The sign-in link and
  any failure go to standard error, and a failure exits non-zero. Claude Code
  runs it as its key helper; pi signs in through its own extension instead.
- First run: Pocket ID's device sign-in. It prints one link with the code already
  in it, opens it when the machine has a browser on its own screen (never over
  SSH), and waits while the link is approved on any device.
- Later runs return the cached token, renew it silently with the refresh token
  (ten minutes before the token runs out), or print a fresh link when
  Pocket ID no longer accepts the refresh token. A Pocket ID server error is
  reported as a failure rather than turned into a new sign-in.
- The token and refresh token are cached in `$XDG_STATE_HOME/llm-token/token.json`
  (default `~/.local/state/llm-token/`), mode 0600, replaced in one step.
  Pocket ID issues a new refresh token on every renewal and refuses the old
  one, so of two runs renewing at the same moment the second is refused; it
  then reads the file the first one wrote, and signs in afresh only if that
  is stale too.
- The Pocket ID client is `llm-token`: public, with PKCE, limited to the `family`
  and `friends` groups, so Pocket ID itself refuses anyone else at approval and at
  every renewal. Its one callback address is `https://llm.pod.haus/setup/`,
  where the setup page's sign-in returns; the device sign-in uses none.

### What Pomerium does with a token

The friends route has
`bearer_token_format: idp_access_token`, so Pomerium checks the token once, at
its first use, against Pocket ID's userinfo endpoint and keeps the result for
the global `cookie_expire` (30 days), then checks again. Userinfo carries no
expiry and no audience, so a token issued to any Pocket ID client for an
admitted person is accepted.

The `llm-token` client's access and refresh tokens last a year
(`restapi_object.llm_token_lifetimes` in `terraform/pocket_id.tf`, since the
pocketid provider has no attribute for lifetimes), so a key pasted into Cursor,
which cannot renew one, keeps working; Claude Code and pi hold the same kind of
token and renew it ten minutes before the year is up. A token cannot be revoked
on its own: Pocket ID does not store access tokens. Revocation is per person,
and its timing is Pomerium's: removing someone from `family` and `friends`, or
deleting them, is seen at Pomerium's next check of their key, up to 30 days
after the last one. For immediate effect add a deny rule for their email to
the `llm.pod.haus` routes in `pomerium/config.yaml` and push; Pomerium applies
policy on every request. In the logs, Pomerium's authorize entries carry the
email and a session id that is a hash of the key, so one key is one session id
for its whole life wherever it is pasted; Caddy's lines on fractal carry the
email as `caller`.

## Handing the GPU to a game and back

### States

The watcher is always in one of four states, shown as the heading of the control
page and as the `llm_watcher_state` metric.

| State | Meaning | Leaves when |
|---|---|---|
| Serving | Model loaded, requests answered, GPU use watched for a game. | A game is seen, or the Yield button is pressed, or something other than the watcher unloaded the model. |
| Yielding | An unload has been requested. | The router reports the model gone. The watcher logs `handoff.yield`, and loads at once if Resume was pressed during the unload. |
| Yielded | Model away. | The GPU has been quiet long enough, no hold is active, and no retry wait is pending: the watcher requests a load. The Resume button does this at once. |
| Resuming | A load has been requested. | The router reports the model loaded (`handoff.resume`), or the load fails, times out, or the Yield button cancels it. |

Whenever the router's state becomes loaded or unloaded, whoever caused it (after
every load, every unload and every death of the model process), the watcher drops
the model file from the guest's file cache so that Windows gets the memory back. A
loaded model keeps only the pages it maps. The same drop happens on the first
tick after the watcher starts, if the router is then loaded or unloaded.

At start the watcher adopts whatever the router reports: loaded is Serving,
unloaded is Yielded, loading is Resuming. A freshly started watcher counts the
quiet period from its own start, so after a deploy the model loads only after the
GPU has been quiet for the quiet period. The router never loads the model by
itself (`--no-models-autoload`, `load-on-startup = false`), so a boot straight
into a game leaves the model out.

### What changes state

All thresholds are environment settings of `llm-watcher` in `llm/compose.yaml`;
the comment beside each gives its reason.

| Change | Rule | Settings |
|---|---|---|
| Serving to Yielding (automatic) | At least `WATCHER_ACTIVITY_SAMPLES` counted samples at or above `WATCHER_ACTIVITY_THRESHOLD_PERCENT` GPU utilisation within the last `WATCHER_ACTIVITY_WINDOW_SECONDS`. Samples are taken once a second. | those three |
| Yielded to Resuming (automatic) | `WATCHER_QUIET_SECONDS` have passed since the last sample at or above the activity threshold (or since the watcher started), and the hold and any retry wait have ended. Any single such sample restarts the quiet period. | `WATCHER_QUIET_SECONDS`, `WATCHER_ACTIVITY_THRESHOLD_PERCENT` |
| Resuming to Yielded (failure) | The router reports the model process exited, or the load has run longer than `WATCHER_LOAD_TIMEOUT_SECONDS`, in which case the watcher unloads it. Either counts as a failed load. | `WATCHER_LOAD_TIMEOUT_SECONDS` |
| Unexpected router state | The router reports a state the current state does not expect (for example a model loaded while Yielded). While Yielded with a hold or recent GPU activity, the watcher unloads it again (trigger `external_load`); otherwise it adopts the router's state and logs a `state.adopted` warning. | `WATCHER_QUIET_SECONDS`, `WATCHER_BUTTON_HOLD_SECONDS` |

`WATCHER_LOAD_TIMEOUT_SECONDS` must be longer than the slowest real load, because
a load that outlasts it is cancelled and counted as failed while still
progressing. A cold load in the container measured 53 seconds, and loads of 104 to
176 seconds were seen in the first hour after a WSL restart.

Constants in the code, not settings: the watcher ticks once a second
(`TICK_SECONDS`, `__main__.py`); a slot read gives up after 2 seconds
(`SLOT_READ_TIMEOUT_S`) and any other router request after 5
(`REQUEST_TIMEOUT_S`, both in `model_server.py`); a yield's record carries the
last 30 seconds of samples (`RECORD_SECONDS`); a failed load is retried after
15 seconds, doubling each time (`FIRST_RETRY_SECONDS`), for at most 5 attempts
(`LOAD_ATTEMPTS`); and failures are forgotten after 600 seconds of serving
(`STABLE_SECONDS`). The last three are in `state.py`.

### The Yield and Resume buttons

The control page is at `https://llm.pod.haus/control` (Nathan only) and
`http://127.0.0.1:8085/control` on fractal. It shows the state and has two
buttons, each a form post that redirects back to the page.

- **Yield** unloads the model at once, cancelling a load in progress
  (`handoff.resume_abandoned`, not logged if the model process had already ended
  on its own), and holds the model away for `WATCHER_BUTTON_HOLD_SECONDS`. The
  page shows "Held" while the hold lasts. Pressing it again extends the hold, and
  pressing it during an unload cancels a Resume pressed during that unload. The
  load waits for the later of the hold's end and the end of the quiet period. A
  hold is not kept across a watcher restart.
- **Resume** ends any hold and any retry wait, forgets earlier failed loads, and
  loads at once if the state is Yielded. Pressed while an unload is still in
  progress, it is remembered and the load starts when the unload ends. It ignores
  the quiet period, so with a game running the model loads on top of it and, once
  loaded and no longer blind, yields again.
- Posts that another site's page made the browser send (cross-site) are refused
  with 403. From fractal, `curl -X POST http://127.0.0.1:8085/control/resume`
  presses the same button.

### Blind windows

The watcher reads whole-GPU utilisation, which includes the model's own work. A
sample counts toward detecting a game only while the state is Serving and no slot
is busy at that sample or the one before. So the watcher cannot see a game:

- while the model generates or reads a prompt (a slot is busy);
- while there is no slot report (the model process answers only between steps,
  and saving or restoring a conversation runs inside one step, so a read can go
  unanswered; a read answered with an error, because the model process ended or
  began loading since the status read, is the same. Either counts as busy for
  that tick and the last report stands);
- while the model unloads or loads. Only the Yield button ends a load early, and
  `WATCHER_LOAD_TIMEOUT_SECONDS` bounds it. A game that starts during a load
  shares the GPU with it until the load ends, and the normal yield follows.

A game that starts in a blind window is seen once the model is idle again, or
once the load completes. Each `handoff.yield` event records `busy_before_s`, the
longest the watcher can have been blind, and `requests_cut`, the requests that
were in flight when the model was unloaded.

## What a client sees

| The model is | A request gets |
|---|---|
| Unloaded (Yielded, Yielding, or the server just restarted) | HTTP 400, "model is not loaded", from the model server itself |
| Exiting (the second or two after an unload, while the model process ends) | HTTP 500, "proxy error: Could not establish connection" |
| Loading (Resuming) | HTTP 503, "Loading model" |
| Unloaded while the request is in flight | The reply is cut. The router gives the model process `stop-timeout` (2 seconds as set in `models.ini`) to exit before killing it, so video memory is free about that long after the unload even with a reply streaming. A game always wins. |

The router answers at once; it does not hold a request for a model that is away
and does not load the model on a request.

## Recovery

### What restarts what

| Situation | What happens |
|---|---|
| `llm-server` fails its health check (the router's `/health`, which passes with no model loaded) | Autoheal restarts it (`autoheal` label). |
| The model process dies and the router keeps running | The router does not reload it. The watcher sees the router report it unloaded, logs a `state.adopted` warning and a `load.failed` error, and loads it again once the GPU has been quiet for `WATCHER_QUIET_SECONDS` and the retry wait has passed. See "The model process dies with a CUDA error" below. |
| `llm-server` is down or unreachable | Any unexpected answer from the router or the GPU ends the watcher's process, and Docker restarts it, until the router answers. Every restart of `llm-server` therefore restarts the watcher too. |
| The watcher's GPU sampling stalls longer than `WATCHER_SAMPLE_STALE_SECONDS` | A watchdog thread logs `watcher.unhealthy` with reason `sample_stale` and ends the process; Docker restarts it and it adopts the router's real state. Until then a game would share the GPU with the model. |
| The watcher reports unhealthy for any other reason | Nothing restarts it, deliberately: a restart resets the clocks that raise these conditions and would let the container read healthy while the cause remains. |
| fractal's Docker or WSL restarts | All containers come back (`unless-stopped`). The model stays unloaded until the watcher has seen a quiet GPU. |
| Fenwick cannot reach the model | Fenwick hands the run to Claude, within seconds when the request is refused and after 30 seconds when nothing answers, and logs `model unavailable, falling back`. A run that had already used one of its tools is not handed on; Fenwick tells the member it may be half done. A 403 in the `llm_lan` record means Caddy saw another address, which its `remote_ip` field names. No `llm_lan` record means the request never arrived: check that WSL is still in mirrored mode and the Hyper-V firewall rule is in place ([fractal's Windows-side settings](../hosts.html#fractal-windows)). |

### Why the watcher reports unhealthy

The watcher's health check is `GET /healthz`, which answers 503 with the reason
as its body. Each reason is logged once, as a `watcher.unhealthy` event, when it
starts.

| Reason | Condition | Look at |
|---|---|---|
| `yield_stuck` | Yielding for longer than `WATCHER_YIELD_STUCK_SECONDS`: the unload did not free the GPU, so a game cannot have the whole GPU. | `docker logs llm-server`; `nvidia-smi` on fractal. Restarting `llm-server` ends the model process. |
| `vram_at_limit` | Serving while whole-GPU memory use (the model and Windows together) is at or above `WATCHER_VRAM_LIMIT_MIB`, the level at which the reading stops rising because the card is full: the model has probably spilled into shared memory, where it reads prompts far slower. A collapse in reading speed (`llm_read_tps`) confirms it. | Windows applications holding video memory; `ctx-size`. Yield then Resume reloads the model. If it recurs, lower `ctx-size` and `LLM_POOL_TOKENS` together. |
| `load_given_up` | `LOAD_ATTEMPTS` failed loads in a row (a failed load, a timeout, or the model dying while serving). Failures are forgotten after `STABLE_SECONDS` of continuous serving, or when Resume is pressed. The model stays down until then. | The `load.failed` events (`attempt`, `error`). After fixing the cause, press Resume. |
| `server_unresponsive` | Slot reads unanswered for longer than `WATCHER_SERVER_SILENT_SECONDS`: the model process has hung, and the watcher cannot tell a game from the model working. | Restart `llm-server`. |

### Gatus alerts

Two checks in the group `Local model`, one per long-running container. Each
reads the container through Komodo every 60 seconds and fails unless it is
running and its Docker health is `healthy`; the alert follows after the default
three failures (see [Monitoring](../monitoring.html)).

- **Local model server (fractal, via Komodo)**: `llm-server` is down or its
  probe fails. A model yielded to a game does not trip it. Read
  `docker logs llm-server` and check the GPU runtime on fractal.
- **Local model watcher (fractal, via Komodo)**: the watcher is unhealthy, not
  running, or restarting. Read `docker logs llm-watcher`: the `watcher.unhealthy`
  line names the reason, and a watcher that keeps restarting shows repeated
  `sample_stale` or a crash from an unreachable router (every restart of
  `llm-server` does this until the router answers).

The alert text states the thresholds of `yield_stuck` (30 seconds) and
`server_unresponsive` (five minutes) in words, so changing those two settings
means editing the description in `gatus/conf/config.yaml` too.

A first deploy before the model file exists leaves both containers not started,
so both checks stay red until `llm-model` succeeds.

### The model process dies with a CUDA error

Seen three times in testing, twice on a trial build and once in the stock
container image, all on the same llama.cpp release: the model process dies with
"CUDA error: unknown error" while reading a very long prompt, with the GPU near
its power limit (about 575 W). The cause is not known.

What happens:

1. The request in flight fails.
2. The router keeps running and reports the model unloaded, with its failed flag
   set and the process's exit code. Further requests get HTTP 400 "model is not
   loaded".
3. The watcher logs a `state.adopted` warning and a `load.failed` error (`error`
   reads "model process exited with code N while serving"), counts one failed
   load, and returns to Yielded. It loads the model again once the GPU has been
   quiet for `WATCHER_QUIET_SECONDS` and the retry wait has passed. The retry wait
   is `FIRST_RETRY_SECONDS` doubled for each failure so far, and the crashed
   prompt's GPU activity restarts the quiet period, so for the first retries the
   quiet period is the longer wait.
4. A death while serving, a failed load and a load that timed out all count
   alike. After `LOAD_ATTEMPTS` failures in a row the watcher gives up and reports
   `load_given_up`. Failures are forgotten after `STABLE_SECONDS` of continuous
   serving, or when Resume is pressed, so crashes spaced further apart than that
   never accumulate.
5. Every saved conversation is lost, because they live in the model process's
   memory. Each conversation's next turn reads its whole prompt again from the
   start.

What to check:

- Windows Event Viewer, System log, source `nvlddmkm`, at the time of the fault.
- The "CUDA error" line and the "current device ... in function ..." line after
  it. ClickStack stores both as printed. The backtrace that follows is stored
  as "text removed"; `docker logs llm-server` on fractal has it.
- The `load.failed` events for the exit code and attempt count.

## Logs and metrics

All container output goes through fractal's Alloy to ClickStack like every other
service ([Logging](../logging.md)). Dashboards are not defined in the
repository; they are made by hand in HyperDX.

### Request record

There is no single request log. A request leaves two records, which share no
identifier and are lined up by time.

- **Caddy's access line**, one JSON line per request to `llm.pod.haus` on
  fractal-caddy's output, logger `http.log.access.llm_remote` (Pomerium path),
  `http.log.access.llm_local` (loopback) or `http.log.access.llm_lan` (Fenwick).
  Fields: `caller` (the signed-in email, remote only; nothing vouches for an
  email header on the other listeners), `remote_ip` (the caller's address, LAN
  only, so a refused request shows which address Caddy saw),
  `client` (User-Agent), `session_id` and `agent_id` (Claude Code's session and
  subagent headers), `path` (no query string), `status`, `duration`. The request
  object, response headers, sizes and user id are deleted, so no other header
  (the sign-in token included) and no body can reach it. Only `llm.pod.haus` is
  logged on the shared `:4443` listener; the docs server's requests are not.
  In ClickStack each field is an attribute under its own name and the body is
  the line's message, `handled request`.
- **The model server's own lines**, at `LLAMA_ARG_LOG_VERBOSITY` 4: slot choice,
  prompt size, tokens reused, tokens read and generated with timings, draft
  acceptance, forced full re-reads, conversation saves, restores and discards,
  pool exhaustion, and request errors. The `llm-server` Alloy module turns each
  kind into attributes (`llm_line` names the kind; `llm_slot` and `llm_task`
  tie lines of one request together). The server prints no path or status; those
  are in Caddy's line.

### What is deliberately not recorded

- **No prompt or response text, anywhere.** Level 4 prints counts and timings
  only. Level 5 prints request and reply bodies and the slot-debug switches
  print prompt text, so `llm/tests` requires level exactly 4 and rejects
  `LLAMA_SERVER_SLOTS_DEBUG` and `LLAMA_SERVER_SLOTS_N_DIFF`.
- Some server log entries can quote client text (a rejected tool definition,
  unparseable model output, an error naming a request's content), and the server
  image is not pinned, so a later release may print a new one. The `llm-server`
  Alloy module is therefore an allow-list: an entry is stored as printed only if it
  matches, in full, a known shape that carries no text. Every other entry is
  stored as its level, its heading (the source and function, and the slot and task
  numbers when printed) and the phrase "text removed". An entry with no level
  prefix that matches no known shape is stored as "text removed" alone. `llm_line`
  says which: one of the kinds above, `other` for the known fixed-wording lines,
  `text_removed`, or a kind that keeps a fixed phrase of its own
  (`output_unparsed`, `request_exception`, `server_exception`, `decode_failed`,
  `request_error`). The model loader's start-up lines are among those reduced.
  A person who needs a reduced line reads `docker logs llm-server` on fractal.
- The router's per-request "proxying request" line is dropped: it carries nothing
  and runs to tens of thousands a day.
- The watcher's log carries counts, flags and times only. Its HTTP request lines
  are silenced, since Caddy records every request that reaches the control page.

### Watcher events

The watcher writes one JSON object per line: `ts`, `level`, `event`, `msg` and
the event's fields. In ClickStack every field is an attribute under its own name
(each slot's figures as `slots.<n>.<field>`), the body is `msg`, and the
`llm-watcher` module also copies the event name to `llm_event`. The watcher measures every
duration on a monotonic clock; the timestamps in events are wall-clock times
converted from it, so the gaps between an event's times are true durations.

| Event | Meaning |
|---|---|
| `handoff.yield` | The model was unloaded. `trigger` is `automatic`, `button` or `external_load`. Carries `first_activity_ts`, `decided_ts`, `released_ts`, `requests_cut`, `busy_before_s`, guest memory used before and after, and the last 30 seconds of raw samples, so thresholds can be corrected from real sessions. |
| `handoff.resume` | The model is ready. `quiet_since_ts` is null for a load the watcher found already running. |
| `handoff.resume_abandoned` | The Yield button cancelled a load. Nothing else abandons a load. |
| `slots.changed` | The slot report changed: each slot's token count and busy flag, and the pool total against `pool_limit`. |
| `state.adopted` | The watcher took the router's state as its own: info at start, a warning (with `previous_state`) when it later finds the router in an unexpected state. |
| `load.failed` | A load failed, timed out, or the model died while serving. Carries `attempt` and `error`. |
| `watcher.unhealthy` | A health reason began (table above), or `sample_stale` as the watchdog ends the process. |

### Metrics

Alloy scrapes both containers every 15 seconds and bridges them to ClickStack
with `service.name` set to the container name and `host.name` to `fractal`.

- **`llm-watcher`**: `llm_watcher_state` (one series per state, 1 for the current
  one; the authoritative state), `llm_watcher_last_sample_age_seconds`,
  `llm_gpu_utilization_percent`, `llm_gpu_memory_used_mib`,
  `llm_gpu_memory_total_mib`, `llm_gpu_power_watts`,
  `llm_gpu_temperature_celsius`, `llm_guest_memory_available_mib`,
  `llm_guest_memory_total_mib`, `llm_pool_tokens`, `llm_pool_limit_tokens`.
- **`llm-server`**: llama.cpp's own request and token counters (`metrics = true`
  in `models.ini`). The router forwards `/metrics` to the model process, so the
  scrape names the model and sets `autoload=false`, which keeps a scrape from
  loading the model while a game has the GPU. With no model loaded the router
  answers 400 and the scrape fails; that is a yielded signal, but
  `llm_watcher_state` is the authoritative one.

## Memory and the kill order

fractal's WSL guest has a 25 GB memory limit, set in a Windows-side WSL
configuration file that Ansible cannot reach. The guest is shared with a
development session and has no early protection of its own, so every container is
bounded: `llm-model` 1g, `llm-server` 17g with 1 GiB of swap (`memswap_limit` is
memory plus swap), `llm-watcher` 256m.

The server's 17g is the 12 GiB of saved conversations (`cache-ram`, held in
memory) plus working memory. A conversation that does not fit in `cache-ram` is
dropped without warning.

If the whole guest runs out of memory, `llm-server` is killed first:
`oom_score_adj` 1000 puts it ahead of anything in a development session, for both
the kernel's killer and earlyoom (which on fractal follows the kernel's ranking;
see [Host provisioning](../host-provisioning.md)). Killing the model process
loses the saved conversations, and the watcher reloads the model. A container
that exceeds its own limit is killed by Docker's memory controller without
touching the rest of the guest.

Video memory is the other shared budget. The pool size (`ctx-size`) is chosen to
leave the Windows desktop room under `WATCHER_VRAM_LIMIT_MIB`; a larger pool
spills out of video memory and reads prompts far slower, which `vram_at_limit`
catches.

## Changing the service

### Settings and where they live

- **Watcher thresholds**: the `llm-watcher` environment in `llm/compose.yaml`.
  Every setting is required: a missing or malformed one stops the watcher at
  start, so a bad deploy fails visibly. Tests read the environment from this file,
  so they exercise the value deployed.
- **Model server settings**: `llm/server/models.ini`, the preset for the model.
  The router's own settings (listen address, preset path, `--no-models-autoload`)
  are on its command line in `compose.yaml`, because the router reads them from
  its arguments and strips them before it starts the model process. Everything
  else is in the preset, each setting beside its reason. The log level
  `LLAMA_ARG_LOG_VERBOSITY` is in `compose.yaml`.
- **Chat templates**: the model's own template raises on a system message in the
  middle of a conversation, which Claude Code sends. The preset uses
  `qwen3.8-late-system-as-user.jinja`, which renders a later system message as a
  user turn; the original it was derived from sits beside it.

Values that must change together:

| Value | Also appears in |
|---|---|
| The preset's section name `qwen3.8-27b` (the model's id on the API) | `LLM_MODEL_NAME` in `compose.yaml`; the `model` parameter of the `llm_server` scrape in `logging/fractal/alloy-conf/config.alloy`; every client's model name |
| `ctx-size` | `LLM_POOL_TOKENS`; a changed pool changes the video memory used, so revisit `WATCHER_VRAM_LIMIT_MIB` |
| `cache-ram` | `llm-server`'s `mem_limit` (the saved conversations plus working memory) |
| The model file name | `MODEL_FILE` and `LLM_MODEL_FILE` in `compose.yaml`; `model` in `models.ini` |
| `WATCHER_YIELD_STUCK_SECONDS`, `WATCHER_SERVER_SILENT_SECONDS` | The wording of the watcher alert in `gatus/conf/config.yaml` |

Constants listed under "What changes state" need a code change in
`llm/watcher/`; the tests in `llm/tests/` pin the behaviour and are run by
`tools/pre-commit`.

### What a push to `main` does

Every file under `llm/` is in the stack's content hash, and every service
carries the hash as a label, so any edit under `llm/` recreates all three
containers, whether it is a threshold, the preset, a template, the token command
or a test. The watcher image is rebuilt when `llm/watcher/` changes. A change to
the shared `init-tools` image recreates the other two containers as well, and the
llama.cpp image, which is not pinned, moves with its tag whenever Komodo pulls it.

In the running service a deploy means: the model is unloaded, requests in flight
are cut, the saved conversations are lost, `llm-model` runs first (it recomputes
the checksum of the file already present), a button hold is forgotten, and the
model then loads only after the watcher's quiet period, because the new watcher
counts it from its start. A
deploy while a game is running leaves the model away.

Edits outside `llm/` act on their own stacks: Caddy's listeners and paths and the
setup page's files (`caddy/fractal/llm-setup/`) on `fractal-caddy`, the routes on
`pomerium`, log parsers on the `logging` stacks of every host, and alerts on
`gatus`.

### The model download job

`llm-model` takes `MODEL_REPO`, `MODEL_FILE` and `MODEL_SHA256` from
`compose.yaml`; the checksum is the Hugging Face large-file object id of the file.

1. If the file is in the `llm-models` volume and its checksum matches, exit 0.
2. If it is present but does not match, delete it and download again.
3. Download to `<file>.part` with one plain stream, check the checksum, and only
   then rename it into place. A mismatch deletes the partial file and exits
   non-zero.

Every failure exits non-zero, and a leftover partial file is removed on exit. To
change the model, change the three variables and the places listed above; the
job never deletes other files in the volume, so the old file stays until removed
by hand. The volume is on Docker's default location on the root filesystem, never
under `/home`, which stays locked until Nathan logs in.

### Giving someone access

Access follows Pocket ID group membership (`family` or `friends`); neither
Pomerium's route nor the token command names a person. `/control` stays Nathan's
by email, in Pomerium and again in Caddy.
