# SSH auth push — Pomerium sign-in links delivered through fenwick

Pomerium's native SSH auth parks the connection and delivers its sign-in
URL only through the keyboard-interactive channel — headless clients
(agents, git, ansible) hang silently with no way to see it. This plan
adds a numbat sidecar that surfaces every pending SSH authentication as
an event to fenwick, which notifies the right person on Signal with a
clickable sign-in link. Approving within the code TTL completes the
original parked connection; nothing client-side is wrapped or enumerated.

## Verified wire contract (pomerium v0.33.0, from source)

- The sign-in URL exists in exactly two places: the keyboard-interactive
  prompt to the client, and the **databroker** — never in logs at any
  level (`pkg/ssh/auth.go handleLogin`).
- Record type `type.googleapis.com/session.SessionBindingRequest`;
  **record id = the `user_code`**, so
  `https://authenticate.pod.haus/.pomerium/sign_in?user_code=<id>`.
  Payload: `protocol`, `key`, `state` (`InFlight`/`Accepted`/`Revoked`),
  `created_at`, `expires_at`, `details{source_addr}`.
- `key = "sshkey-SHA256:" + base64raw(sha256(pubkey))` — same digest
  `ssh-keygen -lf` prints, so per-machine mapping is easy config.
- The **target route** is not in the record. It appears only in the
  debug-level log line `ssh keyboard-interactive auth request`
  (fields `username`, `hostname`, `publickey-fingerprint` = the same
  base64, no prefix). Hence `log_level: debug` on Pomerium and a
  fingerprint join in the sidecar, log line first (it is emitted just
  before the record write).
- Databroker gRPC: **plaintext** behind envoy's ingress listener on
  `127.0.0.1:5443` (host network; nftables drops it externally). Auth
  is an HS256 JWT over the base64-decoded `SHARED_SECRET`, claims
  `{exp}`, sent in gRPC metadata key `jwt`
  (`pkg/grpcutil/options.go WithSignedJWT`).
- Stream pattern: `SyncLatest(type)` for current records + versions,
  then `Sync(server_version, record_version, type, wait: true)` for
  pushed changes; on `ABORTED` re-run `SyncLatest`.

## Design

One new build-mode service in the existing `pomerium/` stack
(`ssh-auth-notify`): host-networked Python service with two inputs and
one output.

- Input 1: databroker Sync stream → pending/resolved
  `SessionBindingRequest` records (code → URL, source address, expiry).
- Input 2: docker-socket follow of the pomerium container's logs →
  route + username context, joined on fingerprint with a short wait
  (the log line strictly precedes the record write).
- Output: one normalized event POSTed to fenwick per record state
  change. Fenwick owns everything person-shaped: the
  fingerprint → person routing (so adding Sky is a fenwick config
  entry, not sidecar code), message wording, and Signal delivery
  through its normal inbound-event stack.

Event payload (`pomerium-ssh-auth`): `user_code`, `url`, `state`,
`fingerprint`, `source_addr`, `route`, `username`, `created_at`,
`expires_at`. Route/username may be null if the log join misses.

The sidecar is deliberately dumb: no recipients, no wording, no
approval logic. Fail fast — unrecoverable errors exit the process and
`unless-stopped` restarts it.

## Work items

- [x] `pomerium/config.yaml`: `log_level: debug` (route context; envoy
      verbosity is separate and unchanged).
- [x] `pomerium/ssh-auth-notify/`: Dockerfile + service + vendored
      `databroker.proto`/`session.proto` (v0.33.0), stubs compiled at
      image build; full content-hash consumer wiring (label, build
      args, Dockerfile ARG/ENV pair).
- [x] `pomerium/compose.yaml`: the service — host network, docker
      socket ro, `SHARED_SECRET` + fenwick endpoint/credential env.
- [x] Fenwick-side source + routing: landed (fenwick `143ee13`, plan
      0025 there). Notable: the in_flight link is delivered
      **deterministically** — fenwick composes the Signal message in
      code and sends it directly, no LLM in the path (speed
      requirement); only resolutions run an agent turn.
- [ ] Deploy the podhaus side via push (held for the concurrent-agent
      all-clear — dirty `pomerium/` files mean any push force-restarts
      numbat-pomerium); end-to-end verify with a throwaway-key SSH
      attempt → Signal message.
- [ ] Clean up the numbat dev containers (`ssh-auth-notify-dev`,
      `sink-dev`) and `/tmp/ssh-auth-notify-dev/` (holds a test.env
      with SHARED_SECRET).
- [ ] Retire this plan into `docs/networking.html` (SSH auth flow) and
      the stack's runbook notes.

## Deferred / follow-ups

- Upstream PR: add the route hostname to the record's `Details` map
  (drops the log join and the debug log level) and/or log the prompt
  URI next to `client requesting authentication`.
- Databroker proto is Pomerium's internal contract; `image: latest`
  means an upgrade can shift it. The sidecar pins nothing — if the
  stream breaks post-upgrade, the failure is loud (restart loop +
  missing notifications), and the vendored protos get refreshed then.
