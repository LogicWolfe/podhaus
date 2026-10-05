# Technical debt

Known architectural problems that are worth fixing, but are not part of an
active migration unless a plan says otherwise.

## Flat dockernet trust domain

**Status:** Open, deliberately separate from the Numbat edge architecture.

Bilby's shared `dockernet` is both an ingress network and a broad east-west
trust domain. A compromised member can discover and connect directly to other
members, bypassing Pomerium and Caddy. Application-native
authentication still applies where it exists, but edge-auth-only services and
otherwise private backend ports have no equivalent boundary. The same shared
network also couples unrelated stacks to one Docker network's lifecycle and
attach failures.

The Pomerium migration narrows cross-host access to named rathole services and
protects its private Caddy origin with mTLS. It does not solve this Bilby-local
problem, and should not grow to include it.

A future design should:

- put public and protected ingress in separate network namespaces;
- keep public ingress off networks containing protected backends;
- keep databases and internal dependencies on per-stack private networks;
- add only explicit, minimal networks for necessary cross-stack connections.

The debt is resolved when compromise of a public-facing container does not
provide network reachability to protected application, administration, or
database endpoints. Any migration must preserve the legitimate Komodo,
monitoring, backup, and secret-delivery paths explicitly.

## Isolate Terraform-only 1Password items

**Status:** Deferred. Do not change vault layout as part of the Numbat migration.

The Homelab vault is readable by <code>komodo-op</code>, so Terraform-only items
such as the BinaryLane credential and Numbat's break-glass root password appear
as unused Komodo Variables. Move them to a Terraform-only vault and service
account in one deliberate credential migration, then delete the stale Komodo
variables and verify stock Terraform still runs from any chezmoi-managed
machine. Runtime certificates and service tokens used by stacks remain in the
Homelab vault.

## Terraform state backend identity has broad storage access

**Status:** Deferred. Keep this permission migration separate from the storage retirement.

The RustFS Terraform backend account, whose credential is held in the
**RustFS Terraform User** 1Password item, has RustFS's built-in `readwrite`
policy. It can access buckets beyond `terraform-state`, although the backend
needs only its state object, versions, and S3 lock object.

Create a Terraform-managed state-only identity and policy while the current
credential still works. Switch a fresh Terraform process to the new credential,
then verify state reads, writes, versioning, locking, and denial for other
buckets. Revoke the broad account only after those checks pass. This is a
deliberate credential rotation in exchange for a narrower storage boundary.

## Deployment failures can leave the parent procedure green

**Status:** Open. Inspect individual deployment results until corrected.

The `podhaus-inject-content-hashes` action in `komodo/sync/actions.toml` awaits
`DeployStack` without checking the returned update's success, increments its
deployed count unconditionally, and logs caught exceptions without failing the
action. During the Flood migration on 2026-09-26, Gatus deployment
`6ab725b59b43c5b181c5b181` failed to build, while parent procedure
`6ab725409b43c5b181c5b0b8` reported success. The normal procedure also invokes
`BatchDeployStackIfChanged`; its child-failure propagation needs coverage.

Make a failed child deployment fail the action and enclosing procedure, with
the affected stack named in the error. Verify both a returned unsuccessful
update and a thrown execution error, plus the batch deployment path. A failed
image build must never produce an overall successful deployment result.

## Numbat compose files default a variable that is set nowhere

**Status:** Open. Ship it as a push of its own.

`relay/numbat/compose.yaml` and `pomerium/compose.yaml` mount their checkout
through `${NUMBAT_REPO_PATH:-/opt/komodo-periphery/etc-komodo/repos/podhaus-numbat}`.
No `stack.toml`, Komodo variable file or Ansible role sets `NUMBAT_REPO_PATH`,
so the default is always the path used, and the variable only suggests a knob
that does not exist. `logging/numbat/compose.yaml` and
`logging/fractal/compose.yaml` had the same pattern and now name the fixed
path.

Replace each with the fixed path. Both edits change the compose text, so the
push recreates Numbat's rathole server, which carries every host's tunnels, and
Pomerium, which every protected name goes through. Push it on its own, when a
short drop of both is acceptable, and confirm afterwards that the tunnels and a
protected route are back.

## ClickStack's comments name the old log shipping paths

**Status:** Open. Fold into the next change to the ClickStack stack.

Three comments in the ClickStack stack describe who ships to the collector as
it was before bandicoot and fractal shipped directly. `clickstack/compose.yaml`
says, in its header list (around line 16) and above the published OTLP port
(around lines 157–158), that port 4318 is published for kangaroo's and bilby's
Alloy and for `logs-ingest.pod.haus`, and that bilby's Caddy forwards every
other host. `clickstack/stack.toml` (around line 17) says the ingestion key is
added to bilby's and kangaroo's logging stacks only. Today bandicoot's Alloy
reaches the collector by container name, bilby, kangaroo and fractal use the
published port, only Numbat, voltaire and Pinelake come through
`logs-ingest.pod.haus`, and every host's logging stack carries the key
([Monitoring](../monitoring.html#alloy) is current).

They were left because any edit in `clickstack/` changes the stack's content
hash, and the push then recreates ClickHouse, HyperDX and the collector. Correct
them in the same commit as the next ClickStack change, which recreates the
stack anyway.

## Two log-ingest client certificates nothing uses

**Status:** Open. Removal needs a `terraform apply`.

`terraform/pomerium.tf` still issues log-ingest client certificates for
bandicoot and fractal (`bandicoot_log_client` and `fractal_log_client`, each a
private key and a certificate signed by the log-ingest CA, valid for five
years), and publishes them as the `bandicoot_cert_b64`, `bandicoot_key_b64`,
`fractal_cert_b64` and `fractal_key_b64` fields of the **Log Ingest PKI**
1Password item. Neither host ships through `logs-ingest.pod.haus` any more, so
nothing reads them. Bilby's Caddy trusts every certificate the CA signed, so
until they expire either one still authenticates to `logs-ingest.pod.haus` for
anyone who holds its key.

Remove both resource sets and their four fields, run `terraform plan` to see
only those deletions, and apply. No stack references the matching
`OP__KOMODO__LOG_INGEST_PKI__BANDICOOT_*` or `…__FRACTAL_*` Komodo Variables
any more; afterwards, delete any of them Komodo still lists.
