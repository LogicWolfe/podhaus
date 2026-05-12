# ~~Paperless stabilization~~ — closed 2026-05-12

End-of-project cleanup for the Phase 10 OneNote → Paperless bulk import.
The import landed 2026-04-18/19 — 1,120 documents across 3 batches. A
two-week passive-use window was planned to catch miscategorizations in
real usage before committing to the import.

All sweep items completed 2026-05-12. The Paperless instance is in
steady-state operation; see [Paperless runbook](/runbooks/paperless.html).

## What landed

- **`unknown` bucket review** — manually swept in the Paperless UI.
- **Legacy `$value` files deleted** — 917 files, ~1.76 GB freed on Pouch.
- **Paperless Trash** — left to auto-expire at the 30-day soft-delete window.
- **Storage relocation Pouch → Jump** — documents tree moved to
  `/mnt/jump/paperless`. Pouch's 24 TB / 82% full bucket isn't a great
  fit for random small-doc reads, and Jump's 363 GB free easily absorbs
  the 1.6 GB. Local NVMe state (`paperless-data` + `pgdata`) stayed on
  NVMe — Jump-over-NFS would have been a downgrade.
- **Documents added to restic** — previously the documents tree had no
  restic snapshot (only NVMe state was backed up). Now covered by the
  existing daily `paperless` plan via a new
  `/mnt/jump/paperless/documents:/userdata/paperless/documents:ro`
  bind mount in `backup/bilby/compose.yaml`.
- **Migration provenance committed** — `~/repos/podhaus-migration-state/`
  promoted from a plain directory on bilby's NVMe to a git repo pushed
  to `LogicWolfe/podhaus-migration-state` (private). Holds the curation
  yaml, the diff plan, the import sidecar SQLite, and the audit logs.
- **iOS app working** — Swiftless on iOS, configured with
  `https://paperless.pod.haus` + CF-Access-Client-Id/Secret headers from
  the `Cloudflare Access — Paperless iOS Service Token` 1P item + a DRF
  token from `Paperless API Token (iOS)`.

## Stretch (not done; future intake patterns)

These aren't blockers; capture for later if useful:

- **Zip-watcher sidecar stack** for transparent scanner/email zip
  consumption. `paperless-extract-zips.py` already has the extraction
  logic that would run continuously — wrap in a watch loop.
- **md-content threshold tuning** — currently 200 chars in
  `curation.md_content_threshold`. "Sweetie" poem (147 chars of real
  content) was noise-classified. Drop to 100–120 if more false
  negatives appear; rerun `paperless-tag-audit` + reconsider affected
  canonicals.
- **Per-person classification refinement** — currently section-based
  only. Title-regex additions would need to be carefully scoped
  ("Blue Sky Trust" overlaps with `sky`; "Nathan Baxter" appears in
  many non-person-specific docs).

## Stretch: future intake patterns

These aren't blockers; capture for later if useful:

- **Zip-watcher sidecar stack** for transparent scanner/email zip
  consumption. `paperless-extract-zips.py` already has the extraction
  logic that would run continuously — wrap in a watch loop.
- **md-content threshold tuning** — currently 200 chars in
  `curation.md_content_threshold`. "Sweetie" poem (147 chars of real
  content) was noise-classified. Drop to 100–120 if more false
  negatives appear; rerun `paperless-tag-audit` + reconsider affected
  canonicals.
- **Per-person classification refinement** — currently section-based
  only. Title-regex additions would need to be carefully scoped
  ("Blue Sky Trust" overlaps with `sky`; "Nathan Baxter" appears in
  many non-person-specific docs).
