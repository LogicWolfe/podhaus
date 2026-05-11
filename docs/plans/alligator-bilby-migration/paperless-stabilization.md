# Paperless stabilization

End-of-project cleanup for the Phase 10 OneNote → Paperless bulk import.
The import landed 2026-04-18/19 — 1,120 documents across 3 batches.
A two-week passive-use window was planned to catch miscategorizations
in real usage before committing to the import.

That window has long elapsed (this is being written 2026-05-11). Time
to do the final sweep so the import provenance lands in
`podhaus-migration-state/` and the Paperless instance starts a
fresh chapter with no migration scaffolding hanging off it.

## Checklist

### 1. `unknown` bucket review

~16 pages are tagged `unknown` (the MATCH_NONE fallback bucket).
Each is a canonical page that didn't match any content rule in the
curation yaml.

Two ways to handle each one:

- **Manual tagging in the Paperless UI** — open the doc, pick the
  right tags, save. Fastest for one-offs.
- **Add a `per_page_overrides` entry** to
  `paperless-curation.yaml` for provenance — captures the rule in the
  source-of-truth file so it's preserved if the import is ever rerun.

Recommendation: do per-page overrides for the ones that fit a
recognizable pattern, manual tagging for genuine one-offs.

### 2. Delete legacy `$value` files

917 leftover `$value`-named files from the old OneNote export still
sit in the documents tree. They're shadowed by the properly-named
recovery files; Paperless ignores them. Disk space + clarity:

```sh
find "/mnt/pouch/Nathan/Notes Export Graph API" -type f -name '$value' -delete
```

### 3. Hard-delete Paperless Trash

Paperless soft-deletes for 30 days by default. Any documents removed
during the stability window are still recoverable via Trash. Once
satisfied, empty Trash in the Paperless admin UI (or via the bulk-edit
API) so the rows actually leave Postgres.

### 4. Commit final sidecar DB

The authoritative migration record is
`~/repos/podhaus-migration-state/paperless-imports.sqlite`. After the
above three items are done, that sidecar is the canonical "what got
imported" record. Commit it (and the curation yaml + diff plan +
logs/) into the `podhaus-migration-state` repo so the migration
provenance is durable.

## Decision: relocate Paperless storage from Pouch to Jump?

User-flagged 2026-05-01. Paperless's access pattern (small documents,
frequent random reads on UI, OCR-heavy on imports) fits Jump's
"durable + IOPS" bucket better than Pouch's bulk-content bucket.

Decision deferred — discuss before moving:

- Capacity on Jump: ~280 GB free, Paperless's documents dir is small
  (~6 GB documents + ~80 MB pgdata + small classifier state).
- Migration: stop stack, rsync `/mnt/pouch/Paperless` →
  `/mnt/jump/Paperless`, update bind mount, restart.
- Downtime: ~10 min including the rsync.

Out of scope for this stabilization sweep — track separately.

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
