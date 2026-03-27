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

Response shape is unchanged: `{ items: [...], total: int }`. The `total` reflects the filtered count (for correct pagination).

Each response item includes both `Document` fields and a flattened subset of `Extraction` fields needed for the table: `issuer_name`, `recipient_name`, `issue_date`, `total_amount`, `invoice_type`, `extraction_status`.

### 2. Batch export endpoint

`POST /api/batch/export`

**Request body:**
```json
{
  "document_ids": ["uuid1", "uuid2", ...],
  "format": "xlsx" | "csv" | "json"
}
```

**Behaviour:**
- Validates all document IDs exist and have a completed extraction
- Documents with no extraction are skipped (included in a `skipped` list in the response if all fail; otherwise silently omitted from ZIP)
- Calls existing per-document exporters for each valid document
- Assembles results into an in-memory ZIP (`zipfile.ZipFile` with `BytesIO`)
- Streams back `application/zip` with filename `docscanai_export_<timestamp>.zip`
- Maximum batch size: 50 documents (returns 400 if exceeded)

### 3. Job cancel endpoint

`POST /api/jobs/{job_id}/cancel`

**Behaviour:**
- Returns 404 if job not found
- Returns 400 if job is already `completed`, `failed`, or `cancelled`
- Sets `Job.status = "cancelling"` in DB
- Returns 200 immediately — cancellation is cooperative, not immediate

**Background task responsibility:**
- OCR and extraction background tasks check `Job.status == "cancelling"` at the start of each page/chunk iteration
- On detection: update status to `"cancelled"`, set `completed_at`, and return early
- No asyncio task cancellation — purely DB-flag-based cooperative cancellation

---

## Frontend

### Architecture — ES Module Split

`app.js` (currently 52KB monolith) is decomposed into focused ES modules. `index.html` loads `src/main.js` as `type="module"`.

```
frontend/
├── index.html
├── styles.css
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
- `Retry` → shown instead of Export for failed documents (triggers OCR + extraction)

**Sorting:** Clicking a column header toggles asc/desc for that column. Active sort column is highlighted with an arrow indicator.

**Pagination:** 20 documents per page. Shows "Showing X–Y of Z". Previous/Next + page number buttons.

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

- All existing API endpoints (documents, OCR, extract, chat, corrections, templates, export) are unchanged
- The extraction panel, field editing, corrections overlay, and template manager are unchanged
- The Chat tab is unchanged
- The database schema requires no new tables or columns
- Existing tests remain valid

---

## Testing

- `test_documents_filter.py` — parametrized tests for all filter combinations, sort orders, pagination with filtered counts
- `test_batch_export.py` — valid batch, mixed valid/no-extraction, over-limit, unknown IDs
- `test_job_cancel.py` — cancel pending, cancel running, cancel already-completed (400), cancel unknown (404)
- Frontend: no automated tests (existing pattern); manual test checklist in the implementation plan
