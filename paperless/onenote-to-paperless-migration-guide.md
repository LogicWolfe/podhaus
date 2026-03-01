# OneNote to Paperless-ngx Migration Guide

*A complete walkthrough for migrating your document archive from Microsoft OneNote to a self-hosted Paperless-ngx instance.*

*March 2026*

---

## Why Paperless-ngx

OneNote is a note-taking tool, not a document archive. The core frustrations that drove this migration:

- **Email ingestion is broken.** Microsoft disabled email-to-OneNote, removing a key ingest pathway.
- **Scanner integration is unreliable.** Third-party scanner integrations with OneNote are flaky and poorly maintained.
- **Wrong mental model.** OneNote is designed for active note-taking with freeform layouts. Archiving tax documents and immigration paperwork in it is fighting the tool's design.
- **Poor attachment search.** Finding text inside scanned documents or PDF attachments is weak compared to purpose-built DMS tools.

Paperless-ngx is a self-hosted, open-source document management system purpose-built for exactly this use case: scan, index, archive, and search documents. It was selected over Obsidian (thinking-first, not capture-first), Joplin (notes-focused with bolt-on OCR), and commercial alternatives.

| Capability | How Paperless-ngx Delivers |
|---|---|
| OCR & Search | Tesseract OCR on all scans; full-text search with autocomplete across every document |
| Email Ingestion | Built-in IMAP monitoring with rule-based processing, auto-tagging, and attachment extraction |
| Scanner Support | Consumption folder watches for new files; works with any scanner that outputs to SMB/FTP/NFS |
| File Formats | PDF, PNG, JPEG, TIFF, GIF, WebP natively; Word, Excel, PowerPoint via Tika/Gotenberg |
| Auto-Classification | Machine learning assigns tags, correspondents, and document types based on learned patterns |
| Data Ownership | Self-hosted, open-source, original files preserved unmodified with checksums |
| Mobile Access | Responsive web UI + SwiftPaperless native iOS app (free, actively maintained) |

---

## Phase 1: Set Up Paperless-ngx

### Docker Stack

Paperless-ngx runs as a set of Docker containers. The recommended stack includes Tika and Gotenberg for extended file format support:

| Container | Purpose |
|---|---|
| `webserver` | Paperless-ngx application server and web UI |
| `redis` | Message broker for background task queue |
| `postgres` | Database for document metadata, tags, correspondents, and search index |
| `tika` | Apache Tika for parsing Office documents (Word, Excel, PowerPoint) |
| `gotenberg` | Converts Office docs and Markdown to PDF for preview; renders formatted archives |

### Key Configuration

Essential environment variables for the Paperless-ngx container:

```env
PAPERLESS_URL=https://paperless.yourdomain.com
PAPERLESS_CSRF_TRUSTED_ORIGINS=https://paperless.yourdomain.com
PAPERLESS_ALLOWED_HOSTS=paperless.yourdomain.com
PAPERLESS_OCR_LANGUAGE=eng
PAPERLESS_TIKA_ENABLED=true
PAPERLESS_TIKA_GOTENBERG_ENDPOINT=http://gotenberg:3000
PAPERLESS_TIKA_ENDPOINT=http://tika:9998
PAPERLESS_EMAIL_TASK_CRON=*/10 * * * *
```

### Document Storage Model

Paperless-ngx stores two versions of every document:

- **Original:** Never modified. Checksums verified. Stored exactly as ingested. This is your source of truth.
- **Archive:** A PDF/A version with OCR text layer (for images/scans) or rendered preview (for Office docs and Markdown). Used for web UI display.

*Both versions are downloadable from the web UI at any time. Paperless-ngx never modifies your original files.*

### Remote Access: Cloudflare Tunnels + Zero Trust

Remote access uses Cloudflare Tunnels with the Zero Trust layer for authentication. This avoids exposing any ports on the host network.

> **Cloudflare + Mobile App:** The SwiftPaperless iOS app supports custom HTTP headers. Create a Cloudflare Service Token and add the `CF-Access-Client-Id` and `CF-Access-Client-Secret` headers in the app settings. This bypasses the interactive Zero Trust login page while keeping protection active. Browser access works normally through the standard Zero Trust login flow.

### Scanner → Consumption Folder

Configure your scanner to output to a network share (SMB or FTP) that is mounted as the Paperless consumption folder. Paperless monitors this folder continuously and automatically processes any new files: OCR, indexing, classification, and filing.

- Recommended scanners: Brother ADS series, Fujitsu ScanSnap (any model with network output)
- Enable barcode support (`PAPERLESS_CONSUMER_ENABLE_BARCODES`) for automatic document splitting and ASN assignment
- Scanned images are converted to searchable PDF/A with embedded OCR text layer

### Email → IMAP Ingestion (Fastmail)

Create a free alias on your Fastmail account (e.g. `paperless@yourdomain.com`) rather than using a user slot. Fastmail allows up to 600 aliases at no extra cost. Then set up a Fastmail rule to file anything sent to this alias into a dedicated folder (e.g. "Paperless Ingest"). This keeps archive-bound emails visible in your normal mailbox while giving Paperless a clean folder to monitor.

#### Fastmail Setup

1. **Create alias:** Settings → My email addresses → Add address → Create an alias → `paperless@yourdomain.com`
2. **Create folder:** Create a folder called "Paperless Ingest" in your mailbox
3. **Create rule:** Settings → Filters & Rules → New Rule → match recipient `paperless@yourdomain.com` → file into "Paperless Ingest"
4. **Generate app password:** Settings → Privacy & Security → Manage app passwords → create one named "Paperless" with IMAP access. Use this instead of your main password.

#### Paperless Mail Account Config

In the Paperless-ngx web UI under Mail Accounts, configure:

- **IMAP server:** `imap.fastmail.com`
- **Port:** 993 (SSL)
- **Username:** your Fastmail username
- **Password:** the app-specific password from above

#### Paperless Mail Rule Config

Create a mail rule pointing at the "Paperless Ingest" folder. Configure what Paperless should do with matching emails: extract attachments, assign tags, and choose a post-processing action (mark read, move to an "Archived" subfolder, etc.).

Rules can filter and process incoming emails based on sender, recipient, subject line, body text, attachment name, and file type. Available actions per rule:

- Auto-assign tags, correspondent, and document type
- Mark as read, flag, move to folder, or delete after processing
- Process attachments only, email body only, or both

Email bodies are converted to PDF for archiving. For better email-to-PDF formatting, consider the community tool **emails-html-to-pdf** which produces cleaner rendered output than the built-in converter.

#### Security Considerations

Giving Paperless IMAP access with an app password grants read/write access to your entire Fastmail mailbox, not just the monitored folder. The risk is bounded by your existing security layers (Cloudflare Zero Trust, Docker networking, home network). The app-specific password can be instantly revoked under Fastmail settings if you ever suspect compromise, without affecting your main login or other app connections.

### Mobile Access: SwiftPaperless (iOS)

The recommended iOS app is **SwiftPaperless** by Paul Gessinger, available free on the App Store.

🔗 [Download SwiftPaperless on the App Store](https://apps.apple.com/us/app/swift-paperless/id6448698521)

Key features:

- Native Swift app with Face ID / Touch ID support
- Full document search, filtering by tags/correspondents/types
- Built-in camera scanner for scanning physical documents
- iOS Share menu integration for uploading from any app
- Custom HTTP header support for Cloudflare Zero Trust service tokens
- Actively maintained with regular updates for latest Paperless-ngx API versions

#### Cloudflare Zero Trust Setup for Mobile

1. In Cloudflare Zero Trust dashboard, create a Service Token under Access > Service Credentials > Service Tokens.
2. Add a Service Auth policy to your Paperless Access Application.
3. In SwiftPaperless, enter your Paperless URL and add two custom HTTP headers:

```
Header Key:   CF-Access-Client-Id
Header Value: <your-client-id>.access

Header Key:   CF-Access-Client-Secret
Header Value: <your-client-secret>
```

4. Save and connect. The app will bypass the interactive login while maintaining Zero Trust protection.

---

## Phase 2: Export from OneNote

### Tool

**onenote-md-exporter** ([github.com/alxnbl/onenote-md-exporter](https://github.com/alxnbl/onenote-md-exporter))

This tool exports OneNote notebooks to Markdown files with all attachments extracted and the full notebook hierarchy preserved as a folder structure.

### Prerequisites

- **OneNote desktop app** (2016+ with File menu — not the UWP Store app)
- **Microsoft Word desktop** (2016+, used internally for conversion)
- **Windows only** (uses OneNote COM API)

### What Gets Exported

- All typed note content as Markdown files
- All attachments (PDFs, images, Word docs) extracted as separate files
- Notebook/Section/Page hierarchy preserved as folder tree
- OneNote tags translated to text symbols (✅ ⭐ etc.)
- Optional: PDF snapshots of each page alongside the Markdown

### What Gets Lost

- Handwritten ink annotations (unless using PDF snapshot export)
- Freeform spatial page layouts
- Audio/video embeds
- Real-time collaboration features

### Running the Export

Open OneNote desktop and ensure all notebooks are synced. Expand any collapsed paragraph groups (an Onetastic macro is available for bulk expansion). Unlock any password-protected sections. Then run the exporter:

```bash
onenote-md-exporter.exe --all-notebooks --output C:\OneNoteExport

# Output structure:
# C:\OneNoteExport/
#   MyNotebook/
#     Section1/
#       Page1.md
#       Page1_attachments/
#         document.pdf
#         scan.png
#     Section2/
#       ...
```

> **Tip:** Run the export overnight for large notebook collections. The tool processes each page through Word for conversion, which is thorough but not fast.

---

## Phase 3: Import into Paperless-ngx

### Upload Script

A Python script walks the exported folder tree and uploads each file to Paperless-ngx via the REST API, preserving the organizational structure as tags. Notebook names and section names each become a tag, so a document at `Work/Taxes/2024-return.pdf` gets tagged with both "Work" and "Taxes".

```python
import requests, os, sys
from pathlib import Path

PAPERLESS_URL = "https://paperless.yourdomain.com"
API_TOKEN = "your-api-token-here"
EXPORT_DIR = Path("C:/OneNoteExport")

headers = {"Authorization": f"Token {API_TOKEN}"}

def get_or_create_tag(name):
    # Check if tag exists, create if not
    resp = requests.get(f"{PAPERLESS_URL}/api/tags/",
        params={"name__iexact": name}, headers=headers)
    results = resp.json()["results"]
    if results:
        return results[0]["id"]
    resp = requests.post(f"{PAPERLESS_URL}/api/tags/",
        json={"name": name}, headers=headers)
    return resp.json()["id"]

for filepath in EXPORT_DIR.rglob("*"):
    if filepath.is_dir():
        continue
    parts = filepath.relative_to(EXPORT_DIR).parts
    notebook = parts[0] if len(parts) > 1 else "Unsorted"
    section = parts[1] if len(parts) > 2 else None
    tag_ids = [get_or_create_tag(notebook)]
    if section:
        tag_ids.append(get_or_create_tag(section))
    with open(filepath, "rb") as f:
        requests.post(
            f"{PAPERLESS_URL}/api/documents/post_document/",
            headers=headers,
            data={"title": filepath.stem, "tags": tag_ids},
            files={"document": f},
        )
```

### How Markdown Files Are Handled

Markdown (.md) files are not natively consumed from the consumption folder, but they work fine when uploaded via the API. With Gotenberg enabled, Paperless renders each Markdown file into a formatted PDF/A for the web UI preview (with proper headings, bold, etc.) while preserving the original .md file verbatim on disk. The full text content is indexed and searchable.

### Post-Import Verification

After the import completes:

- Search for a few known documents to confirm OCR and full-text indexing are working.
- Spot-check that notebook/section tags were applied correctly.
- Manually classify a few dozen documents with correspondents and document types to seed the ML auto-classifier. It improves over time as you correct and confirm its suggestions.
- OneNote becomes a read-only legacy archive. All new documents go into Paperless-ngx.

---

## Organization & Search

### Tagging System

Paperless-ngx uses a flat tagging model with optional hierarchy (nested tags up to 5 levels deep). After migration, your OneNote notebook and section names become tags. Additional organizational tools:

| Concept | Description |
|---|---|
| Tags | Flexible labels applied to documents. Supports nesting and color coding. Auto-assigned via ML. |
| Correspondents | The person or organization a document is associated with (e.g. IRS, your employer, a landlord). |
| Document Types | Category of document (e.g. Tax Return, Lease Agreement, Receipt, Immigration Form). |
| Saved Views | Pre-configured filter and sort combinations pinnable to the dashboard for quick access. |

### Search

Full-text search covers all document content including OCR'd text from scans. Search supports autocomplete, relevance ranking, and advanced query syntax. Typical lookup time from opening the app to viewing a document is a few seconds.

---

## Phase 4: Backup & Disaster Recovery

This phase sets up off-site backup to OneDrive using the Paperless built-in exporter and rclone. The goal is to protect against two failure modes: accidental deletion via the UI, and catastrophic loss (house fire, NAS failure beyond hardware redundancy).

### Strategy Overview

| Failure Mode | Protection | Recovery |
|---|---|---|
| Accidental deletion | OneDrive per-file version history (25 versions, 30 days) | Browse OneDrive version history, restore specific files |
| Bulk accidental wipe | OneDrive full restore (rewind to point in time, 30 days) | OneDrive Settings → Restore your OneDrive → pick a date |
| House fire / NAS failure | Full Paperless export on OneDrive | Pull export directory, run `document_importer` on fresh instance |

### Step 1: Set Up the Nightly Export

The Paperless `document_exporter` creates a self-contained archive: all original documents, archive versions, thumbnails, and a `manifest.json` with all metadata (tags, correspondents, document types, custom fields). This is everything needed to rebuild a Paperless instance from scratch.

Create a stable export directory on your NAS and schedule a nightly cron job:

```bash
# Export to a fixed directory (overwrites in place for efficient rclone sync)
docker compose exec -T webserver document_exporter /path/to/paperless-export
```

Important: always export to the same directory. If you create timestamped directories, rclone will treat each run as entirely new content and re-upload everything.

### Step 2: Set Up rclone to OneDrive

Install rclone and configure a OneDrive remote:

```bash
# Configure (interactive, follow prompts for OneDrive auth)
rclone config

# Test the connection
rclone lsd onedrive:

# Initial sync (will upload everything the first time)
rclone sync /path/to/paperless-export onedrive:Paperless-Backup --progress
```

After the initial full upload, subsequent syncs are incremental. Rclone compares file size and modification time, and only uploads documents that are new or changed. Since Paperless originals are immutable once ingested, the bulk of your data stays static — only newly added documents and the updated `manifest.json` get uploaded each night.

### Step 3: Schedule the Sync

Add rclone to the same cron schedule, running after the export completes:

```bash
# Example crontab entry: export at 2am, sync at 3am
0 2 * * * docker compose -f /path/to/docker-compose.yml exec -T webserver document_exporter /path/to/paperless-export
0 3 * * * rclone sync /path/to/paperless-export onedrive:Paperless-Backup --log-file /var/log/rclone-paperless.log
```

### How OneDrive Provides Versioning

OneDrive automatically versions every file that rclone overwrites. This means each nightly sync creates an implicit snapshot without any extra tooling:

- **Per-file version history:** OneDrive retains up to 25 previous versions of each file for 30 days. If a document gets corrupted or the manifest is damaged, you can right-click any file in OneDrive and restore a previous version.
- **Full OneDrive restore:** With a Microsoft 365 subscription, you can rewind your entire OneDrive to any point in the last 30 days. This is the nuclear option for recovering from bulk accidental deletion or ransomware.
- **Recycle bin:** Deleted files go to the OneDrive recycle bin and are recoverable for 30 days (93 days for work/school accounts).

### Recovery Procedures

**Single document accidentally deleted from Paperless:**
Browse to the export directory in OneDrive, find the original file, download it, and re-upload to Paperless via the web UI or consumption folder.

**Bulk accidental deletion or database corruption:**
Use OneDrive's "Restore your OneDrive" feature to rewind to before the incident. Then pull the export directory back to your NAS and run the importer:

```bash
docker compose exec -T webserver document_importer /path/to/paperless-export
```

**Total NAS loss (house fire):**
Spin up a fresh Paperless-ngx stack (Docker Compose, same config). Download the full export directory from OneDrive. Run `document_importer`. Everything — documents, tags, correspondents, document types, custom fields — is restored.

## Maintenance

### Updates

```bash
docker compose pull
docker compose up -d
# Migrations run automatically on startup
```

---

## Reference Links

- [Paperless-ngx Documentation](https://docs.paperless-ngx.com/)
- [Paperless-ngx GitHub](https://github.com/paperless-ngx/paperless-ngx)
- [onenote-md-exporter](https://github.com/alxnbl/onenote-md-exporter)
- [SwiftPaperless iOS App](https://apps.apple.com/us/app/swift-paperless/id6448698521)
- [SwiftPaperless GitHub](https://github.com/paulgessinger/swift-paperless)
- [Cloudflare Service Tokens Docs](https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/)
- [Paperless-ngx Scanner & Software Recommendations](https://github.com/paperless-ngx/paperless-ngx/wiki/Scanner-&-Software-Recommendations)
