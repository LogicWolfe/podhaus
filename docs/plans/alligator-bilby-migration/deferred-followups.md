# Deferred platform debt

These are the remaining non-blocking platform improvements discovered during
the Alligator to Bilby migration. Remove each section when the work lands and
delete this file when it is empty.

## Remove the Ofelia restart workaround after an upstream release

The released Ofelia image reads labels at startup and doesn't reliably apply
label-value changes after a target container is recreated. The push procedure
therefore restarts the `ofelia` stack in Stage 3 after every deployment run.

Upstream PRs add event-driven or polling-based refresh. Before removing Stage
3, verify the behaviour against a released image by changing a live schedule,
deploying the target stack, and confirming Ofelia adopts the new value without
a restart. Then remove Stage 3 from `komodo/sync/procedures.toml` and update
`docs/scheduling.html` and `AGENTS.md`.

## Make bilby's host package set reproducible

The disaster-recovery guide lists the packages a rebuilt bilby needs, but the
set is still installed by hand. Capture the canonical package set in a dnf
manifest or an idempotent host installer and make the rebuild guide call it.

The current known set includes `docker`, the Docker Compose plugin, `git`,
`op`, `restic`, `rclone`, `zellij`, and `sqlite3`. Include any host utilities
that the bootstrap and recovery scripts actually invoke.

## Automate the first Komodo API key on a fresh database

`komodo-start` reads the `Komodo API OnePassword Sync` item before it can call
the Komodo API. A restored database already contains the matching key, but a
truly new database doesn't. The current recovery path requires one UI login to
mint the first key and save it to 1Password.

Add a first-boot branch that detects the authentication failure, logs in with
the bootstrap admin account, creates the API key, updates the existing 1Password
item, and resumes the normal bootstrap. Keep the manual recovery path documented
until the automated path is tested against an empty database.

## Submit the komodo-op multi-arch fix upstream

The upstream `ghcr.io/0dragosh/komodo-op` build hard-codes amd64. Podhaus builds
`onepassword/komodo-op.Dockerfile` locally for arm64 instead.

Submit the `BUILDPLATFORM` and `TARGETPLATFORM` fix upstream. Remove the local
Dockerfile only after an upstream release is verified on bilby and the stack
has been switched back without emulation.

## Tune ClickHouse insert batching

The collector's frequent small inserts create enough MergeTree parts to make
cold attachment expensive. `async_load_databases` keeps ClickHouse reachable
during attachment, but it treats the symptom rather than reducing part churn.

Measure part creation and merge pressure, then tune the collector or ClickHouse
insert path. Prove lower part growth under normal telemetry volume before
removing the async-load safeguard.

## Decide whether Terraform should resolve every provider credential

Most Terraform provider credentials still arrive through the PWD-scoped,
chezmoi-rendered environment. The 1Password provider cannot read the current
items cleanly because their root fields have random IDs. Moving them requires
restructuring the items and updating every `op read` and komodo-op consumer.

Either keep the environment path as the documented design, or migrate one
credential class at a time with a zero-diff plan between each move. Do not turn
this into a second Terraform root or a host-specific wrapper.

## Manage MagicDNS settings in Terraform

The Tailscale nodes and Docker daemon forwarding rely on tailnet-wide MagicDNS,
but that setting is still managed in the Tailscale admin UI. Extend the existing
OAuth client's scopes with `dns:write`, import or declare the current DNS
settings, and require a zero-diff plan before applying.

## Add an external dead-man check for Gatus

Gatus monitors the services and Fenwick monitors the alert delivery path, but a
dead Gatus instance cannot report its own failure. Choose a small external
monitor that checks `gatus.pod.haus` through an intentional authentication path
and alerts independently of Gatus and Fenwick. Keep this separate from service
checks so an edge outage does not masquerade as every backend failing.
