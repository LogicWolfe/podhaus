# OneNote to Paperless-ngx Migration

*Complete plan and working notes for migrating a document archive from Microsoft OneNote to self-hosted Paperless-ngx.*

*March 2026*

---

## Why Paperless-ngx

OneNote is a note-taking tool, not a document archive. The core frustrations:

- **Email ingestion is broken.** Microsoft disabled email-to-OneNote.
- **Scanner integration is unreliable.** Third-party scanner integrations are flaky.
- **Wrong mental model.** OneNote is for freeform note-taking, not archiving tax documents and immigration paperwork.
- **Poor attachment search.** Finding text inside scanned documents or PDF attachments is weak.

Paperless-ngx is a self-hosted, open-source document management system built for this use case.

| Capability | How Paperless-ngx Delivers |
|---|---|
| OCR & Search | Tesseract OCR on all scans; full-text search with autocomplete |
| Email Ingestion | Built-in IMAP monitoring with rule-based processing, auto-tagging |
| Scanner Support | Consumption folder watches for new files; works with any scanner that outputs to SMB/FTP/NFS |
| File Formats | PDF, PNG, JPEG, TIFF, GIF, WebP natively; Word, Excel, PowerPoint via Tika/Gotenberg |
| Auto-Classification | ML assigns tags, correspondents, and document types based on learned patterns |
| Data Ownership | Self-hosted, open-source, original files preserved unmodified with checksums |
| Mobile Access | Responsive web UI + SwiftPaperless native iOS app |

---

## Phase 1: Paperless-ngx Setup (COMPLETE)

Deployed as a Komodo stack on podhaus with five containers: paperless, redis, postgres, tika, gotenberg.

- Accessible at `https://paperless.pod.haus` via Cloudflare Tunnel
- DNS CNAME managed by DNSControl
- Secrets: 1Password -> komodo-op -> Komodo Variables -> compose env
- Tika + Gotenberg enabled for Office/Markdown file support
- Barcode support enabled for future scanner use
- Admin user: nathan

### Key Config

Stack files: `paperless/compose.yaml`, `paperless/stack.toml`
Tunnel ingress in `cloudflare-tunnel/compose.yaml`: `paperless.pod.haus -> http://paperless:8000`

### Document Storage Model

Paperless stores two versions of every document:
- **Original:** Never modified. Checksums verified. Source of truth.
- **Archive:** PDF/A with OCR text layer (for scans) or rendered preview (for Office/Markdown).

### Future Setup (Not Yet Done)

- **Scanner consumption folder:** Mount an SMB/NFS share as the Paperless consumption directory
- **Email ingestion:** Fastmail alias + IMAP monitoring (see detailed plan below)
- **Mobile access:** SwiftPaperless iOS app with Cloudflare Zero Trust service token
- **Backup:** Nightly `document_exporter` + rclone to OneDrive (see Phase 4)

---

## Phase 2: Export from OneNote

### Notebook Inventory

15 notebooks on personal OneDrive (onedrive.live.com), `C:\Users\Owner` on Windows machine:

| Notebook | Sections | Pages | Description |
|---|---|---|---|
| Blue Sky Trust | 2 | 4 | Corporate governance, taxes |
| Family Life | 6 | 10 | Family member records |
| Financial | 2 | 8 | Nathan's and Sky's taxes |
| Fractal Seed | 3 | 14 | Company documents, AI Chat Investor, Orijin |
| Immigration Stuff | 7 | 24 | Visas, passports, permanent residency |
| Interesting Designs | 28 | 51 | Web dev bookmarks and references |
| Life | 112 | 894 | The big one — property, finance, medical, immigration, etc. |
| Nathan's Notebook | 2 | 5 | Quick notes, scanner output |
| Orijin Plus | 2 | 18 | Resumes, business docs |
| Pod Foundation | 5 | 22 | Audits, finance, minutes |
| Property | 2 | 20 | 16 Lakeview Cr, 29 Riverview Rd |
| Shadow | 1 | 1 | Single page |
| Sky | 8 | 25 | Personal notes, writing |
| Switch | 3 | 9 | Employment, meeting notes |
| Travel | 2 | 6 | Pine Lake, Tasmania trips |

### First Attempt: onenote-md-exporter (FAILED)

**Tool:** [alxnbl/onenote-md-exporter](https://github.com/alxnbl/onenote-md-exporter) v1.5/1.6
**Date:** 2026-03-06
**Output:** `/mnt/NFSPouch/Nathan/Notes Export/`

#### What Worked

- 1,111 markdown pages with full text content
- YAML frontmatter on every page (title, created, updated)
- Notebook/section/page hierarchy preserved as folder tree
- 486 resource files (450 PNG, 29 PDF, 3 JPEG, 2 ZIP, 2 JPG) properly linked from markdown
- Near-perfect resource integrity (485/486 referenced, 1 orphaned)

#### What Failed

**369 file attachments missing.** They appear as text markers in the markdown:

```
\<\<Certificate of Title 2700-605 16 Lakeview Crescent, BRIDGETOWN 6255.pdf\>\>
\<\<LOAN AGREEMENT - draft.docx\>\>
```

The actual files (PDFs, Word docs, Excel files, etc.) were never extracted. Breakdown:

| Type | Missing |
|---|---|
| PDF | 309 |
| ZIP | 11 |
| Word (.doc/.docx) | 11 |
| JPEG/JPG | 6 |
| Email (.eml) | 4 |
| AutoCAD (.dwg) | 4 |
| Excel (.xls/.xlsx) | 4 |
| Audio (.m4a) | 2 |
| SketchUp (.skf) | 2 |
| Other (.rtf, .pages) | 2 |
| Bare UUID (no filename) | ~14 |

789 pages (71%) reference at least one missing attachment. These are the most valuable documents — property titles, tax returns, immigration forms, loan agreements.

Some missing PDFs have PNG page renders following them in the markdown (OneNote's visual preview), but these lose searchable text, original format, and fidelity. ~14 pages have bare UUID attachment refs with no visual representation at all.

**Root cause:** Known bug — [GitHub issue #115](https://github.com/alxnbl/onenote-md-exporter/issues/115). Multiple attachments outside text containers fail to extract. Confirmed in v1.5 and v1.6, no fix available.

**Tags almost entirely lost.** Only 10/1,111 files contain tag symbols. Frontmatter has title/created/updated only — no tag metadata.

#### Why Not Re-Export with onenote-md-exporter

- The attachment bug is in the tool's code, not the config — no setting fixes it
- All tools using the same pipeline (OneNote -> Word interop -> Pandoc) likely share this bug, including [alopezrivera/OneNoteExporter](https://github.com/alopezrivera/OneNoteExporter)
- `.one` file cache on Windows is limited to ~10 notebooks (OneNote evicts the rest), so the [strick-j/onenote-exporter](https://github.com/strick-j/onenote-exporter) approach (direct `.one` parsing) isn't viable
- The notebooks are cloud-only on personal OneDrive

#### onenote-md-exporter appSettings.json Reference

Retained here for reference in case the Graph API exporter falls short and we revisit this tool. The config file lives next to the .exe:

```json
{
  "ResourceFolderName": "resources",
  "PageTitleMaxLength": 50,
  "AddFrontMatterHeader": true,
  "FrontMatterDateFormat": "yyyy-MM-ddTHH:mm:ss",
  "MdMaxFileLength": 50,
  "ProcessingOfPageHierarchy": "HierarchyAsFolderTree",
  "PageHierarchyFileNamePrefixSeparator": "_",
  "ResourceFolderLocation": "RootFolder",
  "OneNoteLinksHandling": "ConvertToWikilink",
  "PanDocMarkdownFormat": "gfm",
  "PostProcessingMdImgRef": true,
  "UseHtmlStyling": true,
  "KeepOneNoteTempFiles": false,
  "IndentingStyle": "LeaveAsIs",
  "DisablePageXmlPreProcessing": false,
  "DeduplicateLinebreaks": true,
  "MaxTwoLineBreaksInARow": true,
  "PostProcessingRemoveQuotationBlocks": true,
  "PostProcessingRemoveOneNoteHeader": true
}
```

If revisiting, change: `ResourceFolderLocation` -> `"PageParentFolder"`, `PageTitleMaxLength` -> `100`, `MdMaxFileLength` -> `100`, `OneNoteLinksHandling` -> `"Remove"`, `UseHtmlStyling` -> `false`, `KeepOneNoteTempFiles` -> `true`.

### New Approach: Microsoft Graph API (NEXT STEP)

**Tool:** [hkevin01/onenote-exporter](https://github.com/hkevin01/onenote-exporter)

Pulls notebooks directly from OneDrive via the Microsoft Graph API. Completely different pipeline — no Word interop, no Pandoc, no attachment bug. Docker-based, runs on Linux.

- Downloads images and attachments directly from Microsoft's servers
- Outputs markdown with `assets/` directory for all media
- Also supports DOCX and JSONL output
- Device code auth flow (browser login, token cached)

#### Setup Steps

1. **Azure App Registration** (one-time, ~5 min):
   - https://portal.azure.com -> App registrations -> New registration
   - Name: `OneNote Exporter`
   - Account type: **Personal Microsoft accounts only**
   - Redirect URI: leave blank
   - API permissions (delegated): `Notes.Read`, `offline_access`
   - Copy the **Application (client) ID**
   - No admin consent required for personal accounts

2. **Run on podhaus:**
   ```bash
   git clone https://github.com/hkevin01/onenote-exporter.git
   cd onenote-exporter
   ./setup.sh

   # Configure
   cat > .env << 'EOF'
   TENANT_ID=common
   CLIENT_ID=<application-client-id>
   EOF

   # Verify access
   docker compose run --rm onenote-exporter --list

   # Test with one notebook first
   docker compose run --rm onenote-exporter --notebook "Property" --formats md

   # Full export
   docker compose run --rm onenote-exporter --formats md
   ```

3. **Verify the test export** before running the full export (see checklist below)

#### Test Export Checklist (Run on "Property" Notebook First)

- [ ] Are PDF/Word/Excel attachments actually downloaded to `assets/`?
- [ ] Do attachments keep their original filenames?
- [ ] Is the notebook/section/page hierarchy preserved?
- [ ] Are embedded images full resolution?
- [ ] Check for tag/metadata preservation (see tag investigation below)
- [ ] Compare against the first export — are the 21 previously-missing Property attachments now present?

#### Tag Investigation

The notes were originally in Evernote with extensive tagging, then migrated to OneNote. The tags may have survived as:

- **OneNote tags** — The Graph API returns page content as HTML. OneNote tags appear as `data-tag` attributes on HTML elements. Check whether the exporter preserves these in its markdown output.
- **Section names** — The "Life" notebook has 112 sections with names like "taxes", "immigration", "insurance", "mortgage" that look like they could be former Evernote tags converted to sections.
- **Inline text** — Some Evernote importers paste tags as text at the top/bottom of pages.
- **Lost entirely** — Possible if the Evernote -> OneNote migration tool didn't map tags.

During the test export, examine:
1. Raw HTML output (if the tool exposes it) for `data-tag` attributes
2. Page content for any Evernote tag remnants (look for lines like `Tags: ...` or `#tag` patterns)
3. Whether the section-heavy structure of Life/Immigration Stuff correlates with Evernote's tag-based organization

---

## Phase 3: Import into Paperless-ngx

### Tagging Strategy

The upload script tags documents with their OneNote source context:

- **Notebook name** -> Paperless tag (e.g. "Property", "Immigration Stuff")
- **Section name** -> Paperless tag (e.g. "16 Lakeview Cr", "Taxes")
- **Recovered Evernote/OneNote tags** -> additional Paperless tags (if found)

These are flat tags. They preserve the original organizational context.

### Linking Related Files

For pages with attachments, use Paperless-ngx's **document link** custom field to create navigable relationships. The script uploads all files for a page, waits for consumption, then links them.

### Upload Script

To be written after the Graph API export is complete and we know the output format. Core logic:

1. Walk the export directory
2. For each page: identify .md file and associated assets
3. Upload via Paperless API (`POST /api/documents/post_document/`)
4. Poll for consumption (`GET /api/tasks/`)
5. Apply tags (notebook + section)
6. Set created/updated dates from metadata
7. Link related documents via custom field
8. Log failures and missing items

### Post-Import Verification

- Search for known documents to confirm OCR and indexing
- Spot-check tags
- Verify previously-missing attachments are now present
- Classify a few dozen documents to seed the ML auto-classifier
- OneNote becomes read-only archive after verification

---

## Phase 4: Backup & Disaster Recovery (NOT STARTED)

### Strategy

| Failure Mode | Protection | Recovery |
|---|---|---|
| Accidental deletion | OneDrive file version history (25 versions, 30 days) | Restore from OneDrive version history |
| Bulk wipe | OneDrive full restore (rewind, 30 days) | OneDrive -> Restore your OneDrive -> pick a date |
| House fire / NAS loss | Full Paperless export on OneDrive | Download export, run `document_importer` on fresh instance |

### Components

1. **Nightly `document_exporter`** to a stable directory on the NAS
2. **rclone sync** to OneDrive (incremental — only new/changed files)
3. **Uptime Kuma push monitor** to alert on backup failures (25-hour heartbeat)

### Backup Script

```bash
#!/bin/bash
PUSH_URL="https://uptime.yourdomain.com/api/push/xxxxxxxx"
COMPOSE_FILE="/path/to/docker-compose.yml"
EXPORT_DIR="/path/to/paperless-export"
LOG_FILE="/var/log/rclone-paperless.log"

docker compose -f "$COMPOSE_FILE" exec -T webserver document_exporter "$EXPORT_DIR"
if [ $? -ne 0 ]; then
    curl -s "${PUSH_URL}?status=down&msg=Export+failed"
    exit 1
fi

rclone sync "$EXPORT_DIR" onedrive:Paperless-Backup --log-file "$LOG_FILE"
if [ $? -ne 0 ]; then
    curl -s "${PUSH_URL}?status=down&msg=Rclone+sync+failed"
    exit 1
fi

curl -s "${PUSH_URL}?status=up&msg=OK"
```

Schedule: `0 2 * * *` via cron.

---

## Future Setup: Email Ingestion

### Fastmail IMAP

1. Create alias: `paperless@yourdomain.com`
2. Create folder: "Paperless Ingest"
3. Filter rule: recipient matches alias -> file into folder
4. Generate app password with IMAP access
5. Configure in Paperless: `imap.fastmail.com:993`, SSL, app password
6. Create mail rule for the folder with auto-tagging

### Mobile Access: SwiftPaperless

- Native iOS app, free
- Cloudflare Zero Trust: create Service Token, add `CF-Access-Client-Id` and `CF-Access-Client-Secret` headers in app settings

---

## Reference Links

- [Paperless-ngx Documentation](https://docs.paperless-ngx.com/)
- [Paperless-ngx GitHub](https://github.com/paperless-ngx/paperless-ngx)
- [hkevin01/onenote-exporter (Graph API, current plan)](https://github.com/hkevin01/onenote-exporter)
- [alxnbl/onenote-md-exporter (first attempt, attachment bug)](https://github.com/alxnbl/onenote-md-exporter)
- [onenote-md-exporter issue #115 (attachment bug)](https://github.com/alxnbl/onenote-md-exporter/issues/115)
- [strick-j/onenote-exporter (.one file parser, needs local files)](https://github.com/strick-j/onenote-exporter)
- [SwiftPaperless iOS App](https://apps.apple.com/us/app/swift-paperless/id6448698521)
- [Cloudflare Service Tokens Docs](https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/)
