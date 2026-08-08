# Postmortems — conventions

How we write incident postmortems for podhaus.

## When to write one

Write a postmortem any time we hit any of these:

- **User-visible service degradation** lasting more than a few minutes (something wasn't loading, returning errors, or actively broken).
- **Data-loss risk averted** — even if no data was lost, if a near-miss surfaced (e.g. backups silently going to the wrong disk).
- **Manual recovery required** that wasn't routine maintenance — power-cycle, hand-mounting NFS, killing wedged containers, force-redeploying past a stuck migration.
- **Repeated incidents of the same shape** — if something has bitten us twice in a quarter, the second one gets a postmortem even if the individual incidents were small.

If you're unsure, write one. Postmortems are cheap to produce and the alternative (no record of what happened) is expensive when it happens again.

We do **not** write postmortems for:

- Routine maintenance, planned downtime, upgrades that went as planned.
- "Investigated, turned out to be nothing" — a paragraph in the relevant runbook is fine.
- Configuration changes that worked the first time.

## File layout

```text
docs/postmortems/
  conventions.md              ← this file
  YYYY-MM-DD-short-slug.md    ← one file per incident
```

The docs server generates the directory listing automatically.

**Naming:** `YYYY-MM-DD-<short-slug>.md`. Date is incident date (when the user-visible thing happened), not when you got around to writing it. Slug is 2–5 words describing the failure mode, not the system — `pouch-jump-mount-failure` not `flood-broken`; the same root cause might surface across multiple systems.

## Structure

Every postmortem has these sections, in this order:

1. **Title** — `YYYY-MM-DD — <one-line description>`.
2. **Front-matter block** — Status (open / resolved), Severity (low / medium / high / critical), Trigger (one phrase).
3. **Summary** — 1–3 paragraphs. What happened, what was visible, why it mattered. A reader should be able to stop after this section and understand the incident.
4. **Timeline** — table of `Time | Event`. Cover trigger → user impact → discovery → diagnosis → fix. Times in AWST. If the system clock was unreliable (power-cycle, OOM lockup), say so and use approximate times.
5. **Root cause** — what actually went wrong, separated from what was *visible*. Frequently two or three latent defects compounded; name each one.
6. **Impact** — what users / services / data were affected. Be specific about "no data loss" vs "no data loss yet" vs "data loss" — the third category requires escalation outside this doc.
7. **Resolution** — bulleted action items, grouped by where the fix lives (host / in-repo / docs / operational). Each one a markdown checkbox. **Mark items done with the completion date in bold:** `- [x] **YYYY-MM-DD**: <what you did>`. Items still open stay `- [ ]` until they're done — postmortems get updated over time, not frozen at write-time.
8. **What we learned** — generalizable lessons. Not "this incident was bad" — patterns to apply or avoid going forward. If the lesson is "we need this convention going forward", that's its own commit and that commit should reference this postmortem.
9. **Out of scope** (optional) — concurrent issues, follow-up work, decisions explicitly deferred. Lists what we *didn't* do and why.
10. **Related** — links to the docs pages updated during remediation, related postmortems, and the upstream/library issue if applicable.

## Action-item discipline

The Resolution checklist is the load-bearing part. Conventions:

- **Every fix is a checkbox.** Even ones marked done at write-time — they belong as `[x]` items so the postmortem captures the full remediation as one auditable list.
- **Completion dates are explicit and bolded.** `- [x] **2026-05-23**: fstab rewritten`. The date is when the fix landed, not when the postmortem was first written.
- **Update postmortems over time.** When a deferred action item completes, edit the postmortem in-place to flip the checkbox and add the date. Don't write a follow-up postmortem just to record "the action item from the last one finally landed."
- **Group by where the fix lives** — host-persistent, in-repo, docs, operational/runbook. Makes it easy to scan what surface area the remediation touched.

## Tone

- Direct and impersonal. "fenwick OOMed bilby" not "I made bilby OOM" — the postmortem is about the system, not blame.
- Reference real timestamps, file paths, line numbers, error messages. Vague summaries age into uselessness.
- Don't editorialize ("this was a bad miss"). Let the timeline and impact speak.
- Future-self is the audience: someone hitting a similar symptom six months later, grepping `docs/postmortems/` for keywords.

## Indexing

When you write a new postmortem:

1. Put the dated postmortem in `docs/postmortems/`; the docs server generates the directory listing.
2. Add a one-line entry to the **Postmortems** section in `AGENTS.md`. Format: `- YYYY-MM-DD: <short slug>: <one-sentence what-and-why>`. This is what every agent/contributor sees when they load the root instruction file, so the line earns its place by being scannable and informative.
3. If the postmortem produces a new convention or hard rule, that change goes in its own appropriate doc (`docs/stack-conventions.html`, hard-rules section of `AGENTS.md`, etc.) and the postmortem links to it.

## Related

- `AGENTS.md`: postmortems are linked there too
- `docs/postmortems/`: the docs server renders the directory listing
