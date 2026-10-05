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

## Gatus's metrics carry no host name

**Status:** Open.

Bilby's Alloy scrapes Gatus's Prometheus metrics and sets only their
`service.name` to `gatus` (the `svc_gatus` transform in
`logging/bilby/alloy-conf/config.alloy`). Every other series Alloy ships has a
`host.name`: its own metrics through the shipping module, bilby's ESPHome
scrape and fractal's two model-service scrapes through their own transforms.
A query that selects Gatus's series by `host.name`, as the telemetry heartbeats
do for Alloy's, finds nothing. Alloy's own spans have no `host.name` either:
they reach the shipping module's input with only the resource Alloy's tracer
gives them (`service.name = alloy`, version and SDK), as the log schema harness
in `logging/tests/test_log_schema.py` shows.

Add `host.name = bilby` to `svc_gatus`, as `svc_esphome` does. For the spans,
add the host in the shipping module's path for them, so every host gets it.
Either change recreates the Alloys it touches, which is harmless.
