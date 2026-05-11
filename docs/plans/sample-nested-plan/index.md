# Sample nested plan

This is the entry point for a multi-page plan. The directory
`docs/plans/sample-nested-plan/` is treated as a single nav item titled
"Sample Nested Plan", landing on this `index.md`. Sub-pages alongside it
in the same directory show up as indented children in the sidebar
**only when this plan or one of its sub-pages is active** — so the
top-level nav stays tidy for plans that aren't being worked on right
now.

## When to use a nested plan

Plans like `alligator-bilby-migration.md` get heavy enough that scrolling
the whole thing becomes painful. Splitting into a directory plan lets each
phase live on its own page with its own TOC, while staying grouped in
the sidebar under one heading.

A reasonable rule of thumb: if a plan's resumption-pointer section is
more than two screens of text, or it's grown past ~50 KB of markdown,
break it up.

## Conventions

- The directory name becomes the nav title (with hyphens converted to
  spaces and words capitalised). Use kebab-case for the directory.
- `index.md` (or `index.html`) is the landing page when a user clicks the
  parent in the sidebar.
- Sub-pages can be `.md` or `.html`. Order is alphabetical by filename, so
  prefix with `01-`, `02-`, etc. if you want explicit ordering.
- Sub-pages do **not** need a `doc-group` / `doc-order` meta — they're
  scoped under their parent automatically.

## Sub-pages of this sample

See [phase-1](phase-1.md) and [phase-2](phase-2.md) — or use the sidebar.
