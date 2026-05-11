# Test plan — auto-discovery smoke test

This file exists to verify that dropping a new `.md` file into
`docs/plans/` makes it appear in the plans index automatically, with no
manifest edit, no container restart, and no rebuild.

## What should happen

1. This file is on disk at `docs/plans/test-plan.md`.
2. nginx's autoindex JSON at `/_listing/plans/` now lists it alongside the
   migration plan.
3. `docs/plans/index.html` calls `plan-list.js` which fetches that JSON
   and renders a row for every `.md` / `.html` entry — newest first by
   mtime.
4. Clicking the row navigates to
   `/plans/plan-viewer.html?file=test-plan.md`, which fetches this file
   and renders it through `marked.js` into the shared docs shell.
5. The right-hand "On this page" TOC is built from the `##` headings in
   this markdown — so the **What should happen** / **Why both work** /
   **Cleanup** sections below show up as anchor links.

## Why both `.md` and `.html` work

The plans viewer treats this `.md` file as content — the styling, theme
toggle, sidebar nav, and TOC are all injected by the same shell scripts
every other docs page uses. A plan authored as `.html` skips the viewer
entirely (it's already a full shell page) and is linked directly from the
plans index. Either way the visual result matches.

## Example formatting

Plain prose renders through Tailwind Typography. Inline `code spans` and
**bold** / *italic* work. A fenced code block:

```yaml
services:
  test:
    image: nginx:alpine
    networks: [dockernet]
```

A table:

| Capability | Where it lives |
|---|---|
| Listing | `nginx autoindex` |
| Rendering | `marked.min.js` |
| Theming | `tailwind.config.js` + `style.css` |
| Discovery | `nav.js` + `plan-list.js` |

A blockquote:

> If you're reading this in a styled view, the pipeline works.

## Cleanup

Once verification is done, delete this file:

```sh
rm docs/plans/test-plan.md
```

It will disappear from the plans index on next refresh — same mechanism
in reverse.
