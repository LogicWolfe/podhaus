# Logging

Every log row Alloy ships to ClickStack follows one schema, whichever host,
service or source wrote it. Alloy on each host reads container output, a few log
files and the systemd journal, and the shared modules in `logging/alloy-modules/`
fit each line to that schema before it ships. A new service fits by writing JSON
lines; the pipeline needs no change. The services that export their own
telemetry (fenwick, indy-service and the book services) bypass Alloy, and their
rows fit only once each sets the one line described under [Services that ship
their own telemetry](#services-that-ship-their-own-telemetry). This page covers what a row looks like, how to
find rows in HyperDX, and the rules a parser and a new service follow.
Alerting, the pipeline's own health, and ClickStack itself are in
[Monitoring](monitoring.html).

## The path

```text
container stdout/stderr ─┐
Plex, Flood, ClickHouse  ─┤  source module: names the service, records how the line was read
  log files              │
systemd journal          ─┘
        │
        ▼
chain.alloy               one parser module per service, each setting the level only
        │
        ▼
ship.alloy                everything after the parsers, the same on every host:
  Loki → OTLP bridge        labels become log attributes
        │
        ▼
  enrich.alloy              the schema: resource attributes, namespaced pipeline
        │                   attributes, severity, JSON fields, message body
        ▼
  batch → exporter → ClickStack collector → ClickHouse otel_logs (180 days)
```

The same modules run on every host, so a service that moves between hosts keeps
its parsing with no logging change. Each host's
`logging/<host>/alloy-conf/config.alloy` lists which source modules it runs and
gives the ship module its host name, the collector's address as that host
reaches it, and, for a host that ships through `logs-ingest.pod.haus`, its
client certificate. Two hosts also scrape metrics of their own (bilby: Gatus and
ESPHome; fractal: the local model service) and hand them to the ship module's
exporter. The ship module also carries Alloy's own metrics and the exporter's
retry and queue settings ([Monitoring](monitoring.html#alloy)).

## The schema

The pipeline's own facts live under namespaced names, and a service's own
fields keep the names the service gave them, so a JSON `host` or `service`
field lands beside the pipeline's names under its own name. The schema's names
are reserved. A service field spelled like one of the pipeline attributes in the
table (`log.source`, `log.iostream`, `compose.service`, `journal.unit`,
`journal.identifier`, `journal.transport`, `journal.priority`,
`journal.reader`), including a nested field that flattens to one, such as
`{"log":{"source":…}}`, is removed from every JSON line, so it is absent from a
body that keeps its JSON as well. A service field spelled like an attribute a
parser adds to that service's rows (`component`, `logger`, `llm_event`) is
discarded, and the row keeps the parser's value. Two more losses come from
flattening itself: an empty list or object leaves no attribute, and a key that
appears twice in one object keeps only its last value.

| Field | Where | Meaning | Example |
|---|---|---|---|
| `Timestamp` | column | When the line was written. Docker's nanosecond receive time for container lines and the journal's own time for journal lines; the line's own time only for tailed files, which have no other. | `2026-10-04 04:04:55.618` |
| `SeverityText` | column | The service's level, normalised to trace, debug, info, warn, error or fatal. Alloy sends it upper-case; the collector stores it lower-case. | `warn` |
| `SeverityNumber` | column | The OpenTelemetry number for that level: 1, 5, 9, 13, 17, 21. | `13` |
| `service.name` | resource | The service, the same on every host. | `flood` |
| `ServiceName` | column | The collector's copy of `service.name`, which HyperDX's service filter reads. | `flood` |
| `host.name` | resource | The machine that read the line. | `pinelake` |
| `service.instance.id` | resource | This running copy: `<host>/<container>`, or `<host>/<service>` for a journal row. Never shared by two containers. | `pinelake/pinelake-flood` |
| `service.namespace` | resource | The stack: the container's compose project. Container and file rows. | `pinelake-flood` |
| `container.name` | resource | The Docker container. Container and file rows. | `fractal-llm-llm-model-1` |
| `log.source` | attribute | How the line was read: `docker`, `journal`, or the path of the tailed file. | `docker` |
| `log.iostream` | attribute | `stdout` or `stderr`. Container rows only. | `stderr` |
| `compose.service` | attribute | The compose service key. Container rows in a compose project, and file rows. | `llm-model` |
| `log.file.path`, `log.file.name` | attribute | The tailed file, added by the bridge. File rows only. | `/var/log/podhaus/plex/Plex Media Server.log` |
| `journal.unit`, `journal.identifier`, `journal.transport`, `journal.priority` | attribute | The journal entry's systemd unit, syslog identifier, transport and priority (0–7). Journal rows only; an entry with no unit has no `journal.unit`. | `sshd.service`, `sshd-session`, `stdout`, `6` |
| `journal.reader` | attribute | Which of the journal reads below took the entry. | `podhaus.journal.run/loki.source.journal.sshd` |
| `Body` | column | The message. For a JSON line, its `msg`, else `message`, else `log_message`; a JSON line with none of the three keeps its JSON. A text line is kept whole as printed, less ANSI colour codes. | `authorize check` |
| everything else | attribute | The service's own JSON fields under their own names, nested objects and arrays flattened with dots, credential keys removed (see Secrets), reserved names discarded (above). | `email`, `request.headers.User-Agent.0`, `status` |

A few parser modules add one attribute of their own: Home Assistant and
Paperless keep the `[component]` logger name of a text line as `logger`,
HyperDX keeps the `[API]`-style prefix of its lines as `component`, the model
watcher copies its event name to `llm_event`, and the model server's allow-list
parser adds its `llm_*` attributes ([local model
runbook](runbooks/local-llm.md#logs-and-metrics)).

### How a container is named

`service.name` is the container name with the host's own `<host>-` prefix
removed, so `pinelake-flood` on Pinelake and `flood` on bilby are both `flood`,
and the two instances differ in `service.instance.id`, `service.namespace` and
`host.name`. A compose service without a `container_name` keeps Compose's
generated name minus that prefix (`llm-llm-model-1` for
`fractal-llm-llm-model-1`), and Lumen's per-worktree index containers are all
`lumen-warm`. A container with no compose project label is named for what it
is, with the real name in `container.name`: a Forgejo Actions job container is
`forgejo-actions-task`, and anything else, such as a `docker run` by hand, is
`unmanaged`. Lumen's index containers are started with plain `docker run` too,
but carry compose project `lumen` because Docker copies the labels of the
Compose-built image they run, so they are not `unmanaged`. These names are
given after the tailer, which still keys each container on its own name (see
the rules below).

Tailed files take the service name, compose project and compose service of the
container that writes them (`plex`, and `rtorrent` for the Flood job logs), so
they sit with that container's stdout. Journal rows are all service
`journald`.

### Severity

A parser module's level wins. Next comes the line's own JSON `level` field,
or its `severity` field, when the line is one JSON object and the field is a
string. Otherwise enrich reads the first level word
(trace, debug, info, warn, warning, error, err, fatal or panic, any case) in the
first 60 characters of the line, where the word follows the start of the line,
`[`, whitespace, `=` or `"` and is followed by `]`, `:`, whitespace, `"` or the
end. So uvicorn's `INFO:` in column one and logfmt's `level=warn` are read,
`[INFO] retrying after error` stays info, and "Total errors encountered: 0" is
not an error. Every level is normalised: WARNING to WARN, ERR to ERROR, PANIC
and zap's DPANIC to FATAL, MongoDB's D1–D5 to DEBUG. A line with no level at all
gets whatever the ClickStack collector guesses from its words. A known misread
in text lines: a level word in an earlier key or value is taken as the level,
which turns indy-service's `reset=Panic` lines into fatal.

### Time

Container rows keep Docker's receive time, which is right whatever zone the
container prints in. Only the three tailed-file sources parse a time, each in
the zone it is written in: Plex's log in the zone each host's `config.alloy`
passes (Perth on bilby, Edmonton on Pinelake), ClickHouse's error log in the
fleet `TZ` that bandicoot's logging stack passes as `CLICKHOUSE_TZ`, the Flood
job logs in UTC and `rtorrent.log` as epoch seconds.
`tools/lint-alloy-timestamps.py` rejects a timestamp stage in any other module
and any zone written into a module.

## Finding rows in HyperDX

HyperDX at <https://watch.pod.haus> searches with Lucene or SQL. In Lucene,
`field:value` is a substring match and map keys use dots
(`ResourceAttributes.host.name:pinelake`); in SQL, map keys use brackets and
`=` is exact. Use SQL when the value is a prefix of another.

| To see | SQL filter |
|---|---|
| One service on every host | `ServiceName = 'flood'` |
| Everything one host read | `ResourceAttributes['host.name'] = 'pinelake'` |
| One running copy | `ResourceAttributes['service.instance.id'] = 'pinelake/pinelake-flood'` |
| One user's sign-ins and requests | `ServiceName IN ('pomerium', 'pocket-id') AND LogAttributes['email'] = 'someone@example.com'` |
| Who ran what with sudo | `ServiceName = 'journald' AND LogAttributes['journal.identifier'] = 'sudo'` |

To compare instances, group a chart or table by
`ResourceAttributes['service.instance.id']`. A log attribute named `host` is
always the service's own field (Caddy's and Pomerium's request Host header),
never the machine; the machine is `host.name`.

## Adding a service

Write one JSON object per line to stdout, with a level field (`level` or
`severity`) and a message field (`msg`, `message` or `log_message`). That is the
whole contract: the service's fields arrive as attributes under their own names,
the body is the message, and nothing in the pipeline changes. The level field is
read directly, wherever it sits in the object; avoid field names the schema
reserves (above). A Komodo stack
gives the container its compose project, which becomes `service.namespace`.

A text-only service needs nothing either, as long as its level word is where the
severity rule above finds it. If it is not, add
`logging/alloy-modules/<service>.alloy` that sets the level and nothing else,
add one link to `chain.alloy`, and add a fixture for it to
`logging/tests/test_log_schema.py`. The module directory sits outside every
host's stack directory, so `logging/compose.shared.yaml` lists it under
`x-podhaus-content-paths`, which is what makes a module-only change redeploy
every host's Alloy. Each host's Alloy reads the modules once, when its
container starts (the `import.file` block in its `config.alloy`), so a module
change applies on that recreate and never inside a running Alloy.

## Rules for a source or parser module

- **A tailer's labels never change.** Each source module's tailer keys its
  saved read positions on its full label set (the container ID or file path
  plus every label), so adding, removing, renaming or revaluing a label makes
  every host re-read that source's retained logs from the start and ship them
  a second time with their original timestamps. The tailer's relabel rules,
  its arguments and the discovery settings may change, provided every existing
  container, file and journal entry keeps exactly the labels it has: the
  change applies when the container is recreated, and an Alloy that stops
  keeps every saved position. A new fact is derived in `enrich.alloy`, or set
  after the tailer in the module's own processing stage, never added to the
  tailer. Nor is a tailer, its `declare`, a host's instance label or the
  `import.file` label ever renamed: saved positions live under Alloy's storage
  path at `<import label>.<declare>.<instance label>/<component>.<label>/positions.yml`
  (`podhaus.docker_logs.run/loki.source.docker.containers/positions.yml`), so a
  rename loses every position and re-reads every retained log. The harness
  pins the Docker rule list, the Docker discovery settings, the Docker tailer's
  arguments and every tailer's labels, so a change fails `tools/pre-commit`
  until its pin is updated with it.
- **A parser never drops a field.** It sets the level (the `detected_level`
  label) and nothing else: it does not rewrite or shorten the body, does not
  delete a label, and does not parse JSON itself (enrich does that for every
  service). The exceptions are structural and named in the module header:
  HyperDX's `[COMP] {…}` prefix is moved to an attribute so the JSON after it
  can be parsed, Home Assistant's and Paperless's logger name is kept as an
  attribute, and the model server's allow-list redacts text (see Secrets).
- **A parser touches only its own service's lines**, selected by
  `stage.match` on the `service` label, and passes everything else through.
- **An attribute a parser adds must not be a name the service uses for a field
  of its own.** A parser's attribute is set before the JSON is merged, so the
  service's field of the same name is discarded.
- **No timestamp stage** outside the three tailed-file modules (see Time).
- **Whole lines are dropped only where the module header says why**: Alloy's
  zero-byte read reports, Plex's `/identity` healthcheck and `Completed:`
  response lines, the Flood `pinelake-stignore` heartbeat that changed nothing,
  the model router's per-request "proxying request" line, and the container
  copies of records that a service also exports itself (below).
- **Every module has a fixture** in `logging/tests/test_log_schema.py`, which
  runs the real modules, `ship.alloy` included, in a `grafana/alloy` container
  whose stand-in collector receives what the module exports. It checks each
  row's resource, attribute names, body and severity, and reads each tailer's
  labels back through Alloy's HTTP API. The same run checks that Alloy's own
  metrics arrive under the host's name, that spans written to the module's
  input arrive, and that the compose file's healthcheck passes against that
  Alloy. `tools/pre-commit` runs it; it needs Docker, and without Docker the
  whole test class is skipped with the reason printed.
- **Every module and host config is formatted, valid and loads.** Each file
  must be exactly what `alloy fmt` prints, `alloy validate` must pass on the
  module directory, and each host config, unmodified, must start in Alloy
  against the modules with no network. `tools/lint-alloy-config.py` checks all
  three in a `grafana/alloy` container from `tools/pre-commit`, prints the
  Alloy version it ran, and is skipped with the reason printed without Docker.
  Starting the config is the check that reaches into the modules a host config
  imports: `alloy validate` on a host config does not open them, so a wrong
  argument or a reference to an export a module does not have fails only when
  Alloy loads the config. A host's secrets, certificates and sockets are absent
  in the lint; they only leave components unhealthy and do not stop the load.

## Secrets

- **Credential keys are removed when the whole line is one JSON object**, by
  enrich, whatever the service: every key with `authorization`, `cookie`,
  `set-cookie`, `password`, `access_token`, `refresh_token` or `id_token` as any
  of its dotted parts, in any case, so `password.new` and
  `headers.Cookie.0.value` go along with `password`. A JSON line with no message
  field that lost a key keeps the rest of its JSON as the body.
- **JSON inside a message is not protected.** The stock ClickStack collector,
  kept on purpose, parses any `{…}` it finds in a body again, with no credential
  removal, and overwrites attributes of the same name. So a message that embeds
  a JSON object, or a text line that carries one (FerretDB's and Backrest's do),
  reaches ClickStack with every key of that object, credentials included.
- **Pomerium's OAuth `state` value is removed** from its lines by the `pomerium`
  module. `state` is an ordinary field elsewhere, so it is not removed
  fleet-wide. Pomerium's sign-in callback path still carries the one-time OAuth
  authorisation `code`, and Pocket ID's request `query` field still carries the
  OAuth `state` blob.
- **Text lines are stored as printed.** Nothing scrubs a secret out of plain
  text, so a service that prints one puts it in ClickStack for 180 days. The fix
  belongs in the service.
- **The model server is the one service whose lines are reduced for privacy**: an
  allow-list stores a line as printed only if it matches a known shape that
  carries no prompt or reply text ([local model
  runbook](runbooks/local-llm.md#what-is-deliberately-not-recorded)). Fractal's
  Caddy deletes the request object from its access lines for the same reason.

## Services that ship their own telemetry

fenwick, fenwick-web-agent, indy-service and the book services (bookshelf,
bookcard, bookbinder) export to the ClickStack collector themselves over OTLP,
so enrich never sees those rows. To keep each record from being stored twice,
the `fenwick` and `indy-service` modules drop those containers' output whole,
and the three book modules drop their JSON lines, letting through only the text
a process prints when it fails outside its exporter. fenwick-web-agent's
container output is collected like any container's.

To fit the schema, each sets its resource in its compose file, one line beside
its service name:

```yaml
environment:
  OTEL_SERVICE_NAME: <service>
  OTEL_RESOURCE_ATTRIBUTES: host.name=<host>,service.namespace=<compose project>,service.instance.id=<host>/<container name>
```

None of them sets `OTEL_RESOURCE_ATTRIBUTES` yet, so their rows carry only the
SDK's resource: `service.name`, and for bookcard a random
`service.instance.id`. None has `host.name` or `service.namespace`.

## What is collected

**Containers**, on every host: the stdout and stderr of every container,
running or stopped, except Lumen's throwaway code-search containers (Docker
label `podhaus.lumen` without a worktree label), whose output is the search
request stream with source snippets in it, and the containers podhaus's tests
and lints start (label `podhaus.harness=true`), which log with Docker's `none`
driver and have nothing to read. Discovery lists the containers every 5
seconds, and a container is read only once a listing has seen it, so one that
is removed within seconds of starting, such as a short `docker run --rm` job,
may never be read. A stopped container stays in discovery, so an init
container that has exited is read whole and one that Ofelia starts on a
schedule resumes where it stopped.
Every Alloy restart, whether the recreate a logging change brings or an
autoheal restart of a wedged exporter ([Monitoring](monitoring.html#exporter-stall)),
ships some lines twice: each stopped container's log is read again from the
start once, because a tailer forgets its position when the log stream ends,
and each running container's lines from the last second Alloy read are sent
again, because positions are saved to the second.

**Tailed files**, on the hosts that opt in with a few lines in `config.alloy`
and a read-only bind in the compose overlay:

- **Plex's `Media Server.log`** (bilby and Pinelake): playback decisions, client
  sessions and scanner results, at debug level on purpose because that is where
  the decisions are. Stdout carries three lines a day.
- **The Flood job logs and `rtorrent.log`** (bilby and Pinelake):
  `flood-publish`, `rtorrent-extract`, `plex-label-sync` and `pinelake-stignore`
  write to files under flood-db because rtorrent's finish hooks discard their
  stdout, and rtorrent's own log is opened by `flood/conf/rtorrent.rc`.
- **ClickHouse's error log** (bandicoot): the only place ClickHouse's own errors
  land, read from the end and parsed by the same module as its stdout.

**The systemd journal**, on bilby, bandicoot, Numbat, fractal and voltaire, read
five ways:

- priority 0–4 (warning and worse) from every unit: mount failures, kernel
  faults, OOM kills and every unit's warnings and errors;
- and priority 5–7 from four audit sources, whose routine events sit there:
  - **sshd**, matched by the identifiers `sshd` and `sshd-session`: each login's
    `Accepted publickey` line, its disconnect and its `session closed` line;
  - **sudo**: every command run through sudo, **with its full command line**, and
    its `session opened` lines;
  - **earlyoom**: its kill reports, stored as warn;
  - **dockerd**: the Docker daemon's whole log, with the severity read from each
    line's `level=` word.

So every command line typed after `sudo` on those hosts is in ClickStack.
Kangaroo (QTS) has no journald, and Pinelake's macOS unified log has no Alloy
source.

## Where things live

| Path | What it is |
|---|---|
| `logging/alloy-modules/docker-logs.alloy` | Container discovery and the service naming above |
| `logging/alloy-modules/journal.alloy` | The five journal reads and the priority-to-level mapping |
| `logging/alloy-modules/plex-server-log.alloy`, `flood-job-logs.alloy`, `clickhouse-error-log.alloy` | The tailed-file sources |
| `logging/alloy-modules/chain.alloy` | The order every parser module runs in |
| `logging/alloy-modules/<service>.alloy` | One service's parser |
| `logging/alloy-modules/enrich.alloy` | The schema: resource, namespaced attributes, severity, JSON, credential removal |
| `logging/alloy-modules/ship.alloy` | The Loki → OTLP bridge, enrich, batch, the exporter and Alloy's own metrics, the same on every host |
| `logging/<host>/alloy-conf/config.alloy` | Which sources a host runs, its own scrapes, and its values for the ship module |
| `logging/tests/test_log_schema.py` | The fixture harness, run by `tools/pre-commit` |
| `logging/tests/test_alloy_health.py` | The exporter-stall healthcheck run against live exporters, run by `tools/pre-commit` |
| `tools/lint-alloy-timestamps.py` | The time-parsing rule, run by `tools/pre-commit` |
| `tools/lint-alloy-config.py` | Every host config and module formatted as `alloy fmt` prints it, the module directory validated, and every host config loaded unmodified beside the modules, run by `tools/pre-commit` |
| `llm/tests/` | The model server parser's own tests |
