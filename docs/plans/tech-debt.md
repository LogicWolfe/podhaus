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

## Caddy and Pomerium collection discards structured diagnostic fields

**Status:** Open. Flood's collector already preserves its full error record.

`logging/alloy-modules/caddy.alloy` replaces each structured record with logger
name and message; `logging/alloy-modules/pomerium.alloy` keeps only service,
component and message. Their `stage.output` blocks discard the remaining
fields, so central logs cannot recover diagnostic context that exists in the
original container record.

Preserve useful structured diagnostics while retaining correct timestamps and
severity. Decide explicitly which request fields to redact before broadening
retention: richer diagnostics must not copy credentials or sensitive request
data into central storage. Verify representative error records end to end in
ClickStack and assert that credential canaries remain absent.
