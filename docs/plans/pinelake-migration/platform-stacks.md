# Pinelake platform stacks

Add Pinelake overlays for logging, Autoheal, and Backrest. Add a local Ofelia
stack only when a containerised service has a concrete label-driven schedule.
These depend on [Host bootstrap](host-bootstrap.md) and the
`podhaus-pinelake` Linked Repo.

Use `file_paths` in each `stack.toml` to compose the host overlay with the
shared definition. Don't add Compose `include:` blocks.

## Logging

Create `logging/pinelake/` by mirroring the Kangaroo overlay:

- `stack.toml` targets server `pinelake`, uses
  `linked_repo = "podhaus-pinelake"`, and lists `compose.yaml` plus
  `../compose.shared.yaml`.
- `compose.yaml` adds the absolute directory bind for `alloy-conf/`.
- `alloy-conf/config.alloy` stamps `host = "pinelake"` and sends OTLP/HTTP to
  `https://logs-ingest.pod.haus` with a Pinelake client certificate.
- `alloy-conf/parsers/` contains only the parser chain required by Pinelake's
  containers.

The cross-network exporter must follow the working Numbat and Fractal
outbound-ingest settings:

```alloy
otelcol.exporter.otlphttp "clickstack" {
  client {
    endpoint            = "https://logs-ingest.pod.haus"
    disable_keep_alives = true
    headers = {
      "authorization" = sys.env("CLICKSTACK_INGESTION_KEY"),
    }
    tls {
      cert_file = "/run/podhaus-secrets/pinelake-cert.pem"
      key_file  = "/run/podhaus-secrets/pinelake-key.pem"
    }
  }

  retry_on_failure {
    max_elapsed_time = "30m"
  }
}
```

Fresh connections avoid the stale conntrack mapping that can survive a
ClickStack collector recreation. The bounded retry prevents a stuck batch from
blocking forever. Also copy Kangaroo's host-stamped Alloy self-metrics so Gatus
can detect a stale telemetry pipeline.

The existing `ClickStack Ingestion Key` supplies application auth. Terraform
also creates a distinct Pinelake log-ingest client certificate and stores the
handoff in 1Password.

## Autoheal

Create `autoheal/pinelake/` with a minimal host overlay and a `stack.toml` that
targets `pinelake`, uses `podhaus-pinelake`, and lists the local and shared
compose files.

The shared service already mounts `/var/run/docker.sock` and watches containers
labelled `autoheal=true`. Don't add host ports or a healthcheck to Autoheal
itself.

Verify it with a disposable unhealthy container or a safe test service. Don't
pause a stateful production process to manufacture the test.

## Backrest

Create `backup/pinelake/` using the existing shared Backrest contract:

- `stack.toml` uses `linked_repo = "podhaus-pinelake"`, `run_build = true`,
  and `ignore_services = ["backrest-init"]`.
- `compose.yaml` builds `backrest-init` from the shared `init-tools` context and
  adds Pinelake's source and repository binds.
- `config.json.tmpl` declares the Pinelake plans and the OneDrive mirror hook.
- All host paths are directory binds. The native Plex plist must be copied into
  a backed-up directory or captured by a one-shot init process; don't add a
  single-file bind to the long-running Backrest container.

Use a local restic repository on the TerraMaster or internal NVMe according to
the backup-target decision in the index. The OneDrive mirror is the off-site
copy. Give Pinelake its own restic password and rclone token so another host
can't race the refresh-token update.

Add Gatus push heartbeats for every scheduled plan. Reuse the current endpoint
ID convention, `<group>_<name>`, and the standard bearer-token path. Map the
shared Backrest contract's `GATUS_BACKREST_PUSH_TOKEN` to the existing
general-purpose `GATUS_HEARTBEAT_PUSH_TOKEN`; do not mint another per-host
token. One pipeline heartbeat after the state plan and OneDrive mirror is
enough when all plans share the nightly schedule. Add separate heartbeats only
for plans with an independent cadence.

## Ofelia (conditional)

Ofelia isn't currently a shared stack. Do not add it merely for symmetry.
Native Plex and Syncthing own their own scheduling; Flood's existing hooks may
not require another scheduler. Add `ofelia/pinelake/` only when a managed
container has a real recurring job that belongs in container labels.

Critical jobs must push a Gatus heartbeat.

The push procedure restarts bilby's `ofelia` stack in Stage 3. That doesn't
restart a separate Pinelake scheduler. Extend the procedure deliberately so
both scheduler stacks refresh labels after a push, or choose a Pinelake Ofelia
image that has verified live label refresh.

## Deployment order

1. Logging, then verify fresh Pinelake rows and self-metrics in ClickStack.
2. Autoheal, then run the safe unhealthy-container test.
3. Backrest init and UI, then create and run the first snapshots.
4. OneDrive mirror, then verify the remote repository contents.
5. Ofelia only if a target service has a label-driven schedule.
6. Gatus checks and heartbeats after each producer is live.

## Acceptance criteria

- Pinelake logs, traces, and Alloy self-metrics reach ClickStack.
- Recreating the ClickStack collector doesn't wedge Pinelake's exporter.
- Autoheal restarts a labelled unhealthy test container.
- Backrest completes and verifies every configured plan.
- The off-site mirror contains current restic repository objects.
- Every scheduled backup and maintenance job has a green Gatus heartbeat.
- If Ofelia is added, it loads Pinelake's labels after a normal push deployment.
