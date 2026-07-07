# skycroeser.net → Publii — validation gaps

> **Status (2026-07-07):** the site is now live at
> <https://skycroeser.net> (the `sky.pod.haus` staging host this
> validation first ran against has been retired). **G2/G3/G4** URL
> preservation is handled by the live Caddy redirect block and was
> validated end-to-end at cutover (dated-post, `/tag/` → `/tags/`,
> `/feed/` → `/feed.xml`). **G5** soft-404 is fixed. Still open, all
> Publii-side (Sky's side, non-blocking): **G1** nav menu, **G6** footer
> cruft, **G7** tag pages in sitemap.

Validation of the first full Publii publish against the old WordPress
site (source of truth: `leftoverwords.WordPress.2026-05-19.xml`). Goal:
restore the **old site structure + all content/images**; styling change
is accepted.

Method: crawled the live site (sitemap = 200 URLs), diffed against the
WXR (165 published posts, 6 published pages, 373 tags, 196 image
attachments), content-validated every check against the 404 page (the
404 is served as HTTP 200 — see G5 — so status codes alone lie).

---

## Clean — no action needed

- **Images: fully preserved.** All 260 unique images referenced across
  the site are self-hosted on `sky.pod.haus` and **all 260 return 200
  (zero broken)**. Zero images still hotlink `skycroeser.net` or
  `*.wordpress.com`. Publii downloaded and localised them.
- **All content present:** 165 posts + 6 pages all render.
- **Dated-post redirects work** (for posts whose slug matched —
  see G2): `/2016/10/13/overlapping-edges/` → 301 → `/overlapping-edges/`
  → 200. `/feed/` → `/feed.xml`, `/category/uncategorized/` → `/` both 301.
- **Archives + pagination render:** `/tags/<slug>/`, `/authors/sky-croeser/`,
  blog index, and `/page/2..28/` all serve real content.
- **The untitled draft is unpublished** (not in sitemap) — good.

---

## Gaps (severity-ordered)

### G1 — No navigation menu (HIGH · structure · Publii)
The homepage header contains only the site-title link. The old site's
nav was **not imported** (Publii's WP importer drops menus). Rebuild it
in Publii → **Menus**, then assign it to the Terminal theme's menu slot.

The old WordPress export contains **two** menus to recreate:

**Main page nav:**
| Order | Label | Target |
|---|---|---|
| 1 | Research ethics | `/research-ethics/` |
| 2 | Teaching | `/teaching/` |
| 3 | Publications | `/publications/` |
| 4 | My research and teaching | `/about/` (page — see G3) |
| 5 | Blog | the blog index (`/` or `/blog/`) |
| 6 | New research students | `/sketchmapforresearch/` (page — see G3) |

**Academic / social links:**
| Label | URL |
|---|---|
| Zotero | `https://www.zotero.org/scroeser` |
| ORCID | `https://orcid.org/0000-0002-6086-2783` |
| Mastodon | `https://kolektiva.social/@scroeser` |
| Academia.edu | `https://uwa.academia.edu/SkyCroeser` |

### G2 — Slug regeneration broke ~33 old post URLs (HIGH · URLs · decision needed)
Publii regenerated post slugs **from titles** instead of preserving the
WordPress `post_name`. So ~33 posts now live at a different slug, and the
old `/YYYY/MM/DD/<wp-slug>/` link 301-strips to a slug that 404s. Publii
also slugified `&` → `andamp` (e.g. `social-media-andamp-society-2014-…`)
— ugly *and* mismatched.

Old → new map (26 cleanly matched; ~7 more exist live under
`andamp`/punctuation-mangled slugs):

```
aies-ai-for-social-good                         → aies-ai-for-social-good-human-machine-interactions-and-trustworthy-ai
aies-day-1-artificial-agency-autonomy-and-lethality → aies-day-1-…-rights-and-principles
blueprint-for-the-future                        → blueprints-for-the-future
burning-man-individuality-and_community         → burning-man-individuality-and-community
burning-man-reaching-ou                         → burning-man-reaching-out
citizen-lab-summer-institute-day-1              → citizen-lab-summer-institute-on-monitoring-internet-openness-and-rights-day-1
compromised-data-day-two                        → compromised-data-the-social-life-of-data-…
contradictoryfeelings                           → quandaries-of-apparently-contradictory-feelings
creating-change-adshel-live-animal-exports-the-quick-and-easy-campaign → …-exports-and-the-quick-…
ica18-day-3-…-post-colonial-…                   → ica18-day-3-…-postcolonial-…
identity-humanity-affective-news-…              → ir13-plenaries-identity-humanity-…
ir13-epic-saturday                              → ir13-saturday-highlights-jedward-peppa-pig-…
ir13-sessions-protest-and-online-activism-…     → ir13-friday-session-protest-and-online-activism
linux-conference-australia-disaster-response-activism-copyrigh → …-activism-and-copyright
maintenance-creation                            → maintenancecreation
national-identity-scheme                        → national-identity-schemes
opening-activism                                → opening-activismsyzitisi-kai-ergastiri-anoihtoy-aktivismoy
post-arab-spring-tunisia-session-3              → post-arab-spring-tunisia-session-3-decentralisation-…
racism-and-censorship-in-athen                  → racism-and-censorship-first-impressions-of-athens
twitter-revolution-connections                  → connecting-to-the-twitter-revolution
upcomingooactivism                              → upcoming-oo-activism
web-presence-workshop-1                         → web-presence-workshop-1-activism-support-and-volcano-sacrifices
(+ ~10 more, incl. several &→"andamp" slugs)
```
Full machine map: `/tmp/slug_map.txt` (regenerate from the validation script).

**Two fix options — decide:**
- **(A) Set Publii slug = old WP slug** for each mismatched post (Publii
  post → URL/slug field). Preserves old URLs exactly; canonical going
  forward; ~33 manual edits in Publii. Some old slugs are ugly/truncated.
- **(B) Caddy redirect map** old-wp-slug → new-publii-slug (server-side,
  config-as-code, ~33 lines, no per-post work). Keeps Publii's slugs;
  old links 301 through. **Recommended** — less manual work, and it also
  cleanly fixes G3/G4 in the same redirect block.

### G3 — Two pages renamed (MEDIUM · URLs · Publii or Caddy)
- `/about/` → now `my-research-and-teaching` (page "My research and teaching")
- `/sketchmapforresearch/` → now `new-research-students`

Old page URLs 404. These are high-value (linked from CVs/profiles). Fix
by setting the two page slugs back (`about`, `sketchmapforresearch`) in
Publii, **or** fold into the G2(B) redirect map. The other 4 pages
(`publications`, `research-ethics`, `teaching`, `blog`) preserved fine.

### G4 — Tag/author URL prefix changed (MEDIUM · URLs · Caddy)
- WordPress `/tag/<x>/` → Publii `/tags/<x>/` (plural)
- WordPress `/author/<x>/` → Publii `/authors/<x>/` (plural)

Old singular forms 404. Fix with two Caddy redirects:
`/tag/*` → `/tags/*`, `/author/*` → `/authors/*` (before the bucket
rewrites). Server-side, trivial.

### G5 — 404s return HTTP 200 (FIXED)
Missing URLs used to serve the styled 404 page with status 200 (soft
404). Fixed by adding `replace_status 404` **inside** the
`handle_errors` `reverse_proxy` block (the earlier attempt placed it as
a standalone directive, which Caddy rejects). Now a genuine miss returns
the styled body with a real `404`. Applied to both `sky.pod.haus` and
`nathanbaxter.com`. See
`docs/plans/caddy-404-status-and-komodo-ifchanged.md`.

### G6 — Theme-credit cruft (LOW · extra content · Publii)
Homepage footer carries Terminal-theme credit links:
`getpublii.com/customization-service`, `github.com/panr`,
`github.com/panr/hugo-theme-terminal`. Remove via theme override /
footer setting (plan Phase 3).

### G7 — Tag pages absent from sitemap (LOW · SEO · Publii)
`/tags/<slug>/` pages render but none appear in `sitemap.xml` (only posts,
pages, and `/page/N/` pagination do). A few WXR tags (`2011`, `2015`,
unused tags) have no page at all — expected (no posts). Check Publii's
sitemap/SEO settings if tag indexing matters.

---

## Suggested fix order
1. **G1 navigation** (Sky/Publii) — biggest structural gap; needs the
   nav to feel like the old site.
2. **G2/G3/G4 URL preservation** — recommend one Caddy redirect block
   covering the slug map + page renames + tag/author prefixes (option B).
   Decide A-vs-B for G2 first.
3. **G6 footer cruft**, **G5 soft-404**, **G7 sitemap** — polish.

Images and content need no remediation.
