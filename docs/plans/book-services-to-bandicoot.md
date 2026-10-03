# Book services to bandicoot

The three book services move from bilby to bandicoot for its disk: bookcard
is about to keep every downloaded book's source archive under
`/var/lib/bookcard/sources/` (up to about 9 GB), and bilby has 33 GB free to
bandicoot's 746 GB. This page is the cut-over procedure. Delete it once the
last section is done; `docs/` already describes the result.

## What moves, and where it is configured

| Piece | Today (bilby) | After (bandicoot) | Where it changes |
|---|---|---|---|
| Stacks `bookshelf`, `bookcard`, `bookbinder` | Komodo server `podhaus` | server `bandicoot` | **each book repository's `stack.toml`** (below) |
| Komodo Repos `bookshelf`, `bookcard`, `bookbinder` | server `podhaus` | server `bandicoot` | `komodo/sync/repos.toml` (this PR) |
| State | `/var/lib/bookshelf` (SQLite, covers), `/var/lib/bookcard` (SQLite, browser profile, downloads) | same paths on bandicoot, owned `1000:1000` | copied by hand (step 3) |
| `books.pod.haus` | Pomerium → bilby's Caddy → `bookshelf:8789` | Pomerium → bilby's Caddy → bandicoot's LAN address `:8789` | `caddy/Caddyfile` (this PR); Pomerium, DNS and Terraform unchanged |
| Gatus | three probes by container name | `bookshelf` on bandicoot's `:8789`; `bookcard` and `bookbinder` through Komodo's container inspect | `gatus/conf/config.yaml` (this PR) |
| Backups | bilby plans `bookcard` (04:15), `bookshelf` (04:25) | bandicoot plans `bookcard` (04:20, also excludes `sources/`), `bookshelf` (04:30); bilby's off-site copy expects both | `backup/{bilby,bandicoot}/…`, `backup/bilby/scripts/sync-bandicoot-copy` (this PR) |
| Nightly library check | label on the bookshelf container, run by bilby's Ofelia | the same label, run by `bandicoot-ofelia` (same Perth time zone) | nothing |
| Logs | shared parser modules, already in bandicoot's Alloy chain | unchanged | comments only (this PR) |
| Push-to-deploy | Forgejo webhooks → `book*-push-deploy` | unchanged; the procedures name no server | nothing; `terraform/forgejo.tf` unchanged |

The front door stays on bilby's Caddy, as for MeTube, Sonarr, HyperDX and
Fenwick. Fenwick has no bookshelf client yet, so there is no Fenwick setting
to change; once both run on bandicoot, its client can call
`http://bookshelf:8789` by name on `dockernet`.

### Edits in the book repositories

Prepare these as one commit per repository, **unpushed**, before starting.
Line numbers are at bookshelf `4f5fa57`, bookcard `f158583`, bookbinder
`dac3bb0`.

Required (the move does not happen without them):

| Repository | File:line | Now | Change to |
|---|---|---|---|
| bookshelf | `stack.toml:15` | `server = "podhaus"  # = bilby` | `server = "bandicoot"` |
| bookshelf | `stack.toml:12` | `tags = ["bookshelf", "bilby", "podhaus"]` | `tags = ["bookshelf", "bandicoot", "podhaus"]` |
| bookcard | `stack.toml:15` | `server = "podhaus"  # = bilby` | `server = "bandicoot"` |
| bookcard | `stack.toml:12` | `tags = ["bookcard", "bilby", "podhaus"]` | `tags = ["bookcard", "bandicoot", "podhaus"]` |
| bookbinder | `stack.toml:15` | `server = "podhaus"  # = bilby` | `server = "bandicoot"` |
| bookbinder | `stack.toml:12` | `tags = ["bookbinder", "bilby", "podhaus"]` | `tags = ["bookbinder", "bandicoot", "podhaus"]` |

Optional, same commits: on bandicoot these addresses can be container names
on the shared `dockernet`, as Fenwick's own stack does. The LAN addresses keep
working (Docker's proxy answers a published port on the host's own address),
but they tie each service to a port being published.

| Repository | File:line | Now | Could be |
|---|---|---|---|
| bookshelf | `stack.toml:35` | `FENWICK_URL=http://[[LAN_BANDICOOT_IPV4]]:8088` | `FENWICK_URL=http://fenwick:8088` |
| bookshelf | `stack.toml:39` | `OTEL_EXPORTER_OTLP_ENDPOINT=http://[[LAN_BANDICOOT_IPV4]]:4318` | `…=http://clickstack-otel:4318` |
| bookcard | `stack.toml:36` | same OTEL line | same change |
| bookbinder | `stack.toml:30` | `BOOKBINDER_OTLP_ENDPOINT=http://[[LAN_BANDICOOT_IPV4]]:4318` | `…=http://clickstack-otel:4318` |

Comments and docs that say bilby: bookshelf `stack.toml:1`, `:27-32`,
`compose.yaml:1`, `:55-57` (bandicoot's Ofelia), `:72-73` (bandicoot's
Backrest), `:76` (now: bilby's Caddy and Gatus call this port), `Dockerfile:1`,
`AGENTS.md:3`, `:164`, `README.md:3`, `:14`, `:31`; bookcard `stack.toml:1`,
`compose.yaml:1`, `:55`, `Dockerfile:3`, `AGENTS.md:34`, `README.md:114`,
`docs/architecture.md:489`, `:504-507`; bookbinder `stack.toml:1`,
`compose.yaml:1`, `Dockerfile:3`, `AGENTS.md:80`.

## Before you start

- This PR is green and unmerged; the three book commits are ready and unpushed.
- Pick a time outside **01:45–02:30** (bookshelf's 02:00 library check) and
  **03:30–06:15** (both hosts' backups, and bilby's 06:00 off-site copy, which
  fails that morning if bandicoot has no `bookcard`/`bookshelf` snapshot dated
  today).
- Run everything from a shell on bandicoot. Commands paste into fish or sh;
  the ones that reach bilby go through `ssh bilby.pod.haus`, whose login shell
  is fish, so anything with shell syntax runs under `sh -c` there.
- bilby's two state directories are never written by this procedure: they are
  the rollback until the last section.

## Cut-over

### 1. Confirm bookshelf is idle

```sh
ssh bilby.pod.haus "sudo sqlite3 -readonly /var/lib/bookshelf/bookshelf.db \"SELECT 'conversion', state, count(*) FROM conversions WHERE state IN ('queued','fetching','converting') GROUP BY state UNION ALL SELECT 'request', kind, count(*) FROM requests WHERE state = 'running' GROUP BY kind;\""
```

No output means idle: no conversion queued or under way, no request running.
When this page was written it printed `converting|1`, `queued|47` and
`text|48`; the 02:00 check queues conversions every night, so the queue is
emptiest late in the day. If it will not drain, stopping anyway is safe by
bookshelf's design: queued conversions and running requests are rows in the
database that carry on at the next start, and the one under way is marked
interrupted and queued afresh (its download starts over). Waiting for idle
only avoids that repeat.

### 2. Stop the three stacks on bilby

In Komodo, Stacks → `bookshelf` → **Stop**, then `bookcard`, then
`bookbinder` (callers first). bookshelf takes up to its 30 s grace period.
Stop, not Destroy: the stopped containers are the fastest rollback.

```sh
ssh bilby.pod.haus "docker ps -a --filter name=book --format '{{.Names}} {{.Status}}'"
```

Every line must read `Exited`. Re-run step 1: its counts must not move now.

### 3. Copy the state to bandicoot

If an earlier attempt left `/var/lib/bookshelf` or `/var/lib/bookcard` on
bandicoot, remove them first (`sudo rm -rf /var/lib/bookshelf /var/lib/bookcard`):
extracting over an old copy can leave a stale SQLite `-wal` file beside the new
database. Then copy both directories as one stream, keeping numeric owners and
modes (no SELinux labels; every book container runs `label:disable`):

```sh
ssh bilby.pod.haus "sudo tar -C /var/lib --numeric-owner -cpf - bookshelf bookcard" | sudo tar -C /var/lib --numeric-owner -xpf -
```

About 4.3 GB, most of it `bookcard/downloads`. Check the copy is identical and
owned by `1000:1000`, the uid and gid all three images run as (each stack's
`state-owner` one-shot runs `chown 1000:1000` on its directory at every deploy;
on bandicoot uid 1000 is `nathan`, as on bilby):

```sh
ssh bilby.pod.haus "sudo sh -c 'cd /var/lib && find bookshelf bookcard -type f -exec sha256sum {} + | sort -k2'" > /tmp/books-bilby.sha256
sudo sh -c 'cd /var/lib && find bookshelf bookcard -type f -exec sha256sum {} + | sort -k2' > /tmp/books-bandicoot.sha256
diff /tmp/books-bilby.sha256 /tmp/books-bandicoot.sha256 && echo identical
sudo stat -c '%u:%g %a %n' /var/lib/bookshelf /var/lib/bookshelf/bookshelf.db /var/lib/bookcard /var/lib/bookcard/bookcard.db /var/lib/bookcard/.browser_profile
```

Expect `identical` and `1000:1000` with modes 755, 644, 755, 600, 700.
`bookcard/config.json` is `0:0 444`: it is the mount point for the config
compose generates, and is replaced at deploy.

### 4. Merge this PR (the podhaus side)

The push to `main` runs `podhaus-push-deploy`. Its sync re-homes the three
Komodo Repos to `bandicoot`; its deploys recreate bilby's Caddy (books →
bandicoot `:8789`), Gatus (the new Books checks), both Backrests (bilby's
without the book plans, bandicoot's with their binds and plans) and every
host's Alloy (the shared parser comments changed). Wait for the procedure to
succeed in Komodo.

Until step 5 finishes, `books.pod.haus` answers 502 and Gatus's Books group is
red; that is the outage window.

Two checks:

```sh
ssh bilby.pod.haus "docker ps -a --filter name=book --format '{{.Names}} {{.Status}}'"
docker exec backrest grep -cE '"id": +"(bookcard|bookshelf)"' /config/config.json
```

bilby's three must still be `Exited`. The procedure's deploy-if-changed stage
covers every stack, but redeploys one only when its compose file changed since
its last deploy, which should not be the case for these; if one did start, stop
it again and redo step 3. The second command, against bandicoot's Backrest,
prints `2`.

### 5. Deploy on bandicoot (the book repositories)

Push the prepared commits to `main` in this order, each after the previous
one's procedure succeeds: **bookbinder, bookcard, bookshelf**. Each push fires
its `<name>-push-deploy` procedure: the stack sync moves the stack to server
`bandicoot`, then the deploy clones the repository on bandicoot's Periphery,
builds the image there and starts it. The first build on bandicoot starts from
a cold layer cache, so it is slower than later pushes; that is not a failure.
bookshelf goes last so its first start finds the other two.

If a deploy fails at "Git Init" with `NotFound`, run **Clone** on that Repo in
Komodo once, then run its procedure again (`docs/komodo.html`, "Moving a Repo to
a new server needs one CloneRepo first").

### 6. Ansible

No playbook applies. This change touches no inventory, host variables or role,
and everything the move relies on already exists on bandicoot: `dockernet`
(`docker` role), the firewall's acceptance of the home LAN, so bilby reaches
`:8789` (`firewall`), and Jump mounted under its Backrest (`storage`). No new
host directory needs managing, because the stacks' `state-owner` one-shots set
ownership.

To confirm those three are converged anyway, use a scratch clone (never
`~/repos/podhaus`, which carries uncommitted work):

```sh
git clone https://github.com/LogicWolfe/podhaus.git /tmp/podhaus-books
cd /tmp/podhaus-books
mise install
sh -c 'mise exec -- pipenv install --dev --python "$(mise which python)"'
cd ansible
mise exec -- pipenv run ansible-galaxy collection install -r requirements.yml
op-vault dev -- mise exec -- pipenv run ansible-playbook playbooks/bandicoot.yml --check --diff --tags docker,firewall,storage
```

Expect `changed=0`. Anything else is drift that predates this move: stop and
read the diff rather than applying it as part of the cut-over.

## Verify

- [ ] **Containers.** `docker ps --filter name=book --format '{{.Names}} {{.Status}} {{.Ports}}'`
  on bandicoot lists `bookshelf`, `bookcard`, `bookbinder`, each `(healthy)`,
  bookshelf with `0.0.0.0:8789->8789/tcp`. Komodo shows all three stacks on
  server `bandicoot`, running.
- [ ] **Health.** From bilby, the path Caddy and Gatus take:
  `ssh bilby.pod.haus "curl -fsS http://bandicoot.pod.haus:8789/health"` →
  `{"status":"ok"}`. Between the services, by name:
  `docker exec bookshelf curl -fsS http://bookcard:8788/health` and
  `docker exec bookshelf curl -fsS http://bookbinder:8787/health`.
- [ ] **Data carried over.** The latest activity lines predate the cut-over
  (bandicoot has no `sqlite3`, so ask bookshelf itself):
  `docker exec bookshelf sh -c 'curl -fsS -H "Authorization: Bearer $BOOKSHELF_TOKEN" -H "X-Bookshelf-Caller: cutover" "http://127.0.0.1:8789/api/activity?limit=3"'`.
  A queue left at step 1 carries on: conversions resume without a new request.
- [ ] **Bearer path from Fenwick's position.** The bot shares bandicoot's
  `dockernet` with bookshelf now:
  ```sh
  sh -c 'docker exec -e T="$(docker exec bookshelf printenv BOOKSHELF_TOKEN)" fenwick deno eval "const r = await fetch(\"http://bookshelf:8789/api/activity?limit=1\", {headers: {Authorization: \"Bearer \" + Deno.env.get(\"T\"), \"X-Bookshelf-Caller\": \"fenwick\"}}); Deno.exit(r.ok ? 0 : 1)" && echo bearer-ok'
  ```
  prints `bearer-ok` (the exit status carries the answer, because these Deno
  containers can send console output to telemetry instead of the terminal).
  The other direction, bookshelf's notifications to Fenwick:
  `docker exec bookshelf sh -c 'curl -fsS "$FENWICK_URL/health"'` succeeds.
- [ ] **Sign-in.** `https://books.pod.haus` in a browser signs in through
  Pocket ID and shows the history, notes and covers as before.
- [ ] **Gatus.** Books group: `bookbinder (bandicoot, via Komodo)`,
  `bookcard (bandicoot, via Komodo)`, `bookshelf` green.
- [ ] **HyperDX.** At `watch.pod.haus`, `ServiceName = 'bookshelf'` has new
  traces since bookshelf started on bandicoot (Deno traces each request it
  serves, the healthcheck's included); bilby's container is stopped, so they
  are bandicoot's. The services' own OpenTelemetry export names no host;
  container lines that come through Alloy carry
  `ResourceAttributes['host'] = 'bandicoot'`. Same check for `bookcard` and
  `bookbinder`.
- [ ] **Backrest.** `http://bandicoot.pod.haus:9898` lists plans `bookcard` and
  `bookshelf`. Run **Backup now** on each: both succeed, and bookcard's snapshot
  holds no `downloads/` or `sources/`.
- [ ] **Next morning.** Gatus `Backrest Nightly (bandicoot)` and
  `Backrest Nightly` (bilby, which now requires bandicoot's two new plans) green.
- [ ] **Library check.** Right after step 5,
  `docker logs bandicoot-ofelia 2>&1 | grep bookshelf-library-check` shows
  `New job registered`. After the next 02:00 it shows `Job start`, and
  bookshelf's activity shows the night's check. Ofelia's run may end
  `error non-zero exit code: 22` with `409`: bookshelf's own in-process
  schedule fires at the same second and answers Ofelia 409 while its check
  runs. bilby's Ofelia logged exactly that at 2026-10-03 02:00, so it is not a
  result of the move.

## Rollback

bilby's state directories and stopped containers are untouched until the last
section, so going back is a matter of where the newer data is.

**Before step 5** (nothing has run on bandicoot):

1. On bilby: `docker start bookbinder bookcard bookshelf`.
2. Revert this PR on GitHub and merge the revert; `podhaus-push-deploy` puts
   Caddy, Gatus, both Backrests and the Repos back on bilby.
3. On bandicoot: `sudo rm -rf /var/lib/bookshelf /var/lib/bookcard`.

**After step 5** (the services have run on bandicoot and may hold newer
purchases, loans, notes or texts):

1. In Komodo, Stop `bookshelf`, `bookcard`, `bookbinder` (now on bandicoot).
2. To keep what bandicoot wrote, move bilby's copies aside and copy back:
   ```sh
   ssh bilby.pod.haus "sudo mv /var/lib/bookshelf /var/lib/bookshelf.pre-rollback; sudo mv /var/lib/bookcard /var/lib/bookcard.pre-rollback"
   sudo tar -C /var/lib --numeric-owner -cpf - bookshelf bookcard | ssh bilby.pod.haus "sudo tar -C /var/lib --numeric-owner -xpf -"
   ```
   To discard it instead, skip this; bilby's directories are as they were at
   step 2.
3. Revert the three book commits and push, bookbinder, bookcard, then
   bookshelf. Each procedure moves its stack back to `podhaus` and deploys on
   bilby from its warm cache.
4. Revert this PR and merge the revert.
5. Check the old Gatus probes and `books.pod.haus`, then on bandicoot remove
   the containers (`docker rm bookshelf bookcard bookbinder bookshelf-state-owner-1 bookcard-state-owner-1`),
   the images (`docker image rm bookshelf:local bookcard:local bookbinder:local`)
   and `/var/lib/bookshelf`, `/var/lib/bookcard`.

## Remove from bilby

Once every check above has passed, including one night's backups:

1. Containers and images on bilby:
   ```sh
   ssh bilby.pod.haus "docker rm bookshelf bookcard bookbinder bookshelf-state-owner-1 bookcard-state-owner-1; docker image rm bookshelf:local bookcard:local bookbinder:local"
   ssh bilby.pod.haus "docker ps -a --filter name=book --format '{{.Names}}'"
   ```
   The second prints nothing.
2. Komodo's old clones on bilby (the stacks built from these):
   `ssh bilby.pod.haus "sudo rm -rf /etc/komodo/repos/bookbinder /etc/komodo/repos/bookcard /etc/komodo/repos/bookshelf"`.
3. The state: `ssh bilby.pod.haus "sudo rm -rf /var/lib/bookshelf /var/lib/bookcard"`
   (and the `.pre-rollback` copies, if a rollback made them).
4. Komodo has nothing else to delete: the stacks, Repos, syncs and procedures
   are the same resources, now on bandicoot. Its container list for server
   `podhaus` shows no book containers.
5. bilby's restic repository keeps the snapshots its own `bookcard` and
   `bookshelf` plans made (tags `plan:bookcard` or `plan:bookshelf` with
   `created-by:podhaus-bilby`); with the plans gone, no retention run forgets
   them. Keep them as history, or forget them by snapshot ID when they are no
   longer wanted. Nothing depends on them.
6. Delete this page and mark the book services moved in
   `docs/plans/bandicoot-migration.md`.
