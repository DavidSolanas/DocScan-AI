# Sprint 7 Design Spec — Document Library, Search, Batch Export, Job Abort

**Date:** 2026-03-27
**Status:** Approved
**Sprint:** 7 of 8

---

## Scope

Sprint 7 delivers four features on top of the completed Sprint 6 codebase:

1. **Document Library view** — dedicated full-page document management UI
2. **Search & filtering** — column-based filters on the document list
3. **Bulk export** — select multiple documents, download as ZIP
4. **Job abort** — cancel in-progress OCR/extraction jobs

### Explicitly deferred (not in Sprint 7)

- WebSockets / Server-Sent Events for real-time job progress (polling stays, UX improves)
- Tags and notes per document
- Bulk re-extraction
- Automatic job retry on failure
- Full-text search inside OCR'd document content (SQLite FTS5)

---

## Backend

### 1. Enhanced document filter endpoint

Extend `GET /api/documents/` with optional query parameters. A new `list_documents_filtered()` CRUD function performs a `LEFT JOIN` between `Document` and `Extraction` to expose extraction-derived fields for filtering.

**New query parameters:**

| Parameter | Type | Filters on |
|-----------|------|------------|
| `q` | string | `Document.filename` LIKE |
| `vendor` | string | `Extraction.issuer_name` OR `Extraction.recipient_name` LIKE |
| `status` | string | `Document.status` exact match |
| `invoice_type` | string | `Extraction.invoice_type` exact match |
| `date_from` | date string (dd/mm/yyyy) | `Extraction.issue_date` >= |
| `date_to` | date string (dd/mm/yyyy) | `Extraction.issue_date` <= |
| `amount_min` | decimal string | `Extraction.total_amount` >= |
| `amount_max` | decimal string | `Extraction.total_amount` <= |
| `sort_by` | enum | `upload_date` \| `issue_date` \| `total_amount` \| `filename` (default: `upload_date`) |
| `sort_order` | enum | `asc` \| `desc` (default: `desc`) |
| `skip` / `limit` | int | unchanged (pagination) |

**Date parsing:** `date_from` and `date_to` are accepted in `dd/mm/yyyy` format (matching the UI). The CRUD function parses them to ISO 8601 before comparing against `Extraction.issue_date` (stored as ISO 8601 strings).

**Response shape:** Unchanged key name — `{ "documents": [...], "total": int }` matching the existing `DocumentListResponse` schema. The `total` reflects the filtered count (for correct pagination).

Each item in `documents` is an extended `DocumentDetail` — a new `DocumentLibraryItem` schema subclasses `DocumentDetail` and adds the following optional fields (null when no extraction exists): `issuer_name`, `recipient_name`, `issue_date`, `total_amount`, `invoice_type`, `extraction_status`. The `DocumentListResponse.documents` field type is updated from `list[DocumentDetail]` to `list[DocumentLibraryItem]`. Since all new fields are `Optional`, existing consumers and existing tests remain valid.

### 2. Batch export endpoint

`POST /api/batch/export`

**Request body:**
```json
{
  "document_ids": ["uuid1", "uuid2", ...],
  "format": "xlsx" | "csv" | "json"
}
```

**Supported formats (intentional subset of per-document formats):**
- `xlsx` — calls existing `ExcelExporter`
- `csv` — calls existing CSV export path
- `json` — writes the raw extraction JSON file (`Extraction.json_path`) contents as-is for each document

SII, FacturaE, DOCX, and Markdown formats are intentionally excluded from batch export — they are specialist outputs best used one document at a time.

**Behaviour:**
- Returns 400 if `document_ids` is empty or exceeds 50 items
- Documents that exist but have no completed extraction are silently skipped; if _all_ provided IDs are skipped, returns 400 with a clear message
- Calls existing per-document exporters for each valid document
- Assembles results into an in-memory ZIP (`zipfile.ZipFile` with `BytesIO`), one file per document named `<filename>.<ext>`
- Streams back `application/zip` with filename `docscanai_export_<timestamp>.zip`
- Returns 404 if any `document_id` does not exist in the DB

### 3. Job cancel endpoint

`POST /api/jobs/{job_id}/cancel`

**Behaviour:**
- Returns 404 if job not found
- Returns 400 if job status is already `completed`, `failed`, `cancelled`, or `cancelling` (idempotent guard — a second cancel request on an in-progress cancellation gets a clean 400, not a 404)
- Sets `Job.status = "cancelling"` in DB
- Returns 200 immediately — cancellation is cooperative, not immediate

**Background task responsibility:**
- OCR and extraction background tasks check `Job.status == "cancelling"` at the start of each page/chunk iteration
- On detection: update status to `"cancelled"`, set `completed_at`, and return early
- **Auto-extraction suppression:** The OCR background task currently auto-triggers an extraction job on completion. If cancellation is detected mid-OCR, the auto-extraction trigger is skipped — no extraction job is created for a cancelled OCR run.
- No asyncio task cancellation — purely DB-flag-based cooperative cancellation

---

## Frontend

### Architecture — ES Module Split

`app.js` (currently 52KB monolith) is decomposed into focused ES modules. `index.html` is updated to load `src/main.js` as `type="module"` (replacing the current `./app.js` script tag). `app.js` is deleted after the split is complete.

```
frontend/
├── index.html          ← script tag updated: app.js → src/main.js
├── styles.css          ← restructured with CSS custom properties for theming
└── src/
    ├── main.js         # Entry point, global state object, view routing
    ├── api.js          # All fetch wrappers (apiFetch, apiJson) + endpoint constants
    ├── ui.js           # Shared utilities: toast, spinner, theme toggle, confirm dialog
    ├── library.js      # Library view: table, filters, sort, pagination, batch selection
    ├── viewer.js       # PDF viewer: PDF.js, zoom, page navigation, toolbar
    ├── jobs.js         # Job panel: polling loop, progress bar, cancel button
    └── tabs/
        ├── ocr.js      # OCR tab
        ├── invoice.js  # Invoice/extraction tab + field editing
        └── chat.js     # Chat tab
```

**Global state** lives in `main.js` and is imported by modules that need it. No module mutates another module's state directly — they call exported functions.

**View routing**: `state.view` is either `'library'` or `'viewer'`. `main.js` toggles CSS classes on two top-level containers. The nav bar is always visible.

### Theming — Dark/Light Mode

All colors are CSS custom properties defined on `:root` (charcoal/amber dark theme by default). A `[data-theme="light"]` selector on `<html>` overrides them to the warm white/amber light theme.

**Dark theme (default):**
- Background: `#0e0c08` / `#1c1814` / `#2a2420`
- Surface: `#141008`
- Accent: `#fbbf24` (amber)
- Text primary: `#f5f0e8`
- Text muted: `#6b5f4f`
- Border: `#2a2420`
- Status valid: `#4ade80`
- Status review: `#fb923c`
- Status failed: `#f87171`
- Status pending: `#94a3b8`

**Light theme:**
- Background: `#ffffff` / `#fdf8f0` / `#faf5ec`
- Surface: `#fdf8f0`
- Accent: `#b45309` (dark amber)
- Text primary: `#1c1814`
- Text muted: `#78716c`
- Border: `#e7e0d5`
- Status colors: same semantic meaning, adjusted lightness

**Toggle**: A sun/moon button in the top nav bar. Calls `ui.toggleTheme()` which sets `document.documentElement.dataset.theme` and persists to `localStorage`. Applied on page load before first render to avoid flash.

### Library View

Activated via "Library" button in the nav bar. Replaces the 3-panel viewer container.

**Layout:**
- **Top bar**: "DocScan AI" logo, "Library" tab (active), "← Back to Viewer" link, search input, theme toggle, Upload button
- **Left filter panel** (200px fixed): Status checkboxes (All / Completed / Needs review / Pending / Failed), Invoice type dropdown, Date range (from/to), Amount range (min/max), Clear filters button
- **Main area**: Document count + active filter summary, sort dropdown, sortable table, pagination
- **Batch action bar** (fixed at bottom, only visible when ≥1 row selected): "N documents selected", format selector (xlsx/csv/json), "Export ZIP" button, "Clear selection" link

**Table columns:** ☐ | Filename | Issuer | Recipient | Issue Date | Total | Status | Actions

**Per-row actions:**
- `Open` → switches to viewer view and loads document
- `Export` → single-document export (existing flow)
- `Retry` → shown instead of Export for failed documents; fires `POST /api/ocr/{id}` only (auto-extraction follows via the existing OCR completion trigger)

**Sorting:** Clicking a column header toggles asc/desc for that column. Active sort column is highlighted with an arrow indicator.

**Pagination:** 20 documents per page. Shows "Showing X–Y of Z". Previous/Next + page number buttons.

**Selection scope:** Row selection is page-local — navigating to a different page clears the current selection. The batch bar disappears on page change.

**Empty states:** Distinct messages for "no documents uploaded yet" vs "no documents match filters."

### Viewer View Changes

- **Nav bar added** at top: "DocScan AI" logo, "📚 Library" button (navigates to library view), theme toggle
- **Job panel**: Cancel button appears next to in-progress jobs. Clicking calls the cancel endpoint and updates the job status indicator optimistically.
- No other changes to the viewer, tabs, or extraction panel.

---

## Data Flow

### Library filter flow
```
User changes filter → library.js debounces 300ms → api.js GET /api/documents/?[params] →
library.js re-renders table rows + updates pagination + updates "X documents" count
```

### Bulk export flow
```
User selects rows → batch bar appears → user picks format → clicks Export ZIP →
api.js POST /api/batch/export → streams ZIP → browser downloads file
```

### Job cancel flow
```
User clicks Cancel on job → jobs.js POST /api/jobs/{id}/cancel →
optimistic UI update (status → "Cancelling...") → polling picks up "cancelled" status →
final UI update
```

---

## What Is Not Changed

- All existing API endpoints (documents, OCR, extract, chat, corrections, templates, export) are unchanged in their behaviour
- The extraction panel, field editing, corrections overlay, and template manager are unchanged
- The Chat tab is unchanged
- The database schema requires no new tables or columns
- Existing tests remain valid

---

## Testing

- `test_documents_filter.py` — parametrized tests for all filter combinations, sort orders, pagination with filtered counts, date format parsing (dd/mm/yyyy → ISO comparison)
- `test_batch_export.py` — valid batch (xlsx/csv/json), mixed valid/no-extraction, all-skipped (400), over-limit (400), unknown IDs (404)
- `test_job_cancel.py` — cancel pending job, cancel running job, cancel already-completed (400), cancel already-cancelling (400), cancel unknown (404), verify auto-extraction suppressed after OCR cancel
- **`conftest.py`:** Any new API module (`api/batch.py`, `api/jobs.py` if extended) that uses `AsyncSessionLocal` directly must be added to the `db_session` fixture patch list alongside the existing modules
- Frontend: no automated tests (existing pattern); manual test checklist in the implementation plan
