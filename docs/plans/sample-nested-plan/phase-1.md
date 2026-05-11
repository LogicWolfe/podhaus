# Phase 1 — first half

A sub-page inside the `sample-nested-plan/` directory. The sidebar shows
this entry indented under "Sample Nested Plan" while you're viewing
either the parent or any sibling sub-page.

## How navigation works

When you're on this page, the sidebar renders the Plans group as:

```
Plans
  All plans
  …other flat plans…
  Sample Nested Plan
    ├ Phase 1     ← you are here
    └ Phase 2
```

When you click "All plans" or any other plan, the children collapse and
you go back to a tidy sidebar.

## Linking between sub-pages

Use relative links between sibling pages: `[phase 2](phase-2.md)` works
because the plan-viewer treats the `?file=` parameter as a path inside
`/plans/`. Internally it points at
`/plans/plan-viewer.html?file=sample-nested-plan/phase-2.md`.

## Things to note

This file's title in the sidebar is derived from its filename
(`phase-1.md` → "Phase 1"). If you want a different label, rename the
file. For consistency I'd recommend keeping filenames descriptive.
