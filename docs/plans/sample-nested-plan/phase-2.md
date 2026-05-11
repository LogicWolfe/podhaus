# Phase 2 — second half

The other sibling sub-page. Two sub-pages is enough to demonstrate the
pattern; real plans will obviously have more.

## Removing a nested plan

Same as flat plans: `rm -r docs/plans/<dir>/` and it disappears from the
sidebar + index on next page load. No manifest to update.

## Converting a flat plan to nested

When a `.md` plan gets too long:

1. `mkdir docs/plans/<name>/`
2. `git mv docs/plans/<name>.md docs/plans/<name>/index.md`
3. Split content into `phase-1.md`, `phase-2.md`, etc.
4. Refresh — the nav switches from a flat entry to a parent entry
   automatically.
