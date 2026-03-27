// frontend/src/library.js
// Owns: Library view — document table, filter panel, sorting, pagination, batch export.

import * as api from './api.js';
import { showToast } from './ui.js';
import { state, setView } from './main.js';

const PAGE_SIZE = 20;

// ── State local to library ────────────────────────────────────
let filters = {};
let sortBy = 'upload_date';
let sortOrder = 'desc';
let currentPage = 1;
let totalDocs = 0;
let selectedIds = new Set();
let debounceTimer = null;

// ── Entry point ───────────────────────────────────────────────
export function initLibrary() {
  renderShell();
  bindFilterEvents();
  loadPage();
}

// ── Shell HTML ────────────────────────────────────────────────
function renderShell() {
  document.getElementById('library-container').innerHTML = `
    <div class="library-layout">
      <aside class="library-filters" id="lib-filters">
        <div class="filter-section-title">Filters</div>

        <div class="filter-group">
          <label class="filter-label">Status</label>
          <div class="filter-checkboxes" id="lib-status-checks">
            ${['all','completed','needs_review','pending','failed','uploaded'].map(s => `
              <label class="filter-check">
                <input type="checkbox" name="status" value="${s}" ${s==='all'?'checked':''}>
                ${s.replace('_',' ')}
              </label>`).join('')}
          </div>
        </div>

        <div class="filter-group">
          <label class="filter-label">Invoice Type</label>
          <select id="lib-type" class="filter-select">
            <option value="">All types</option>
            <option value="STANDARD">Standard</option>
            <option value="SIMPLIFIED">Simplified</option>
            <option value="RECTIFICATIVE">Rectificative</option>
            <option value="CREDIT_NOTE">Credit note</option>
          </select>
        </div>

        <div class="filter-group">
          <label class="filter-label">Issue Date</label>
          <input type="text" id="lib-date-from" class="filter-input" placeholder="dd/mm/yyyy">
          <input type="text" id="lib-date-to"   class="filter-input" placeholder="dd/mm/yyyy" style="margin-top:4px">
        </div>

        <div class="filter-group">
          <label class="filter-label">Amount (€)</label>
          <div style="display:flex;gap:4px;align-items:center">
            <input type="number" id="lib-amount-min" class="filter-input" placeholder="Min" style="width:50%">
            <span class="filter-label" style="margin:0">–</span>
            <input type="number" id="lib-amount-max" class="filter-input" placeholder="Max" style="width:50%">
          </div>
        </div>

        <button id="lib-clear-filters" class="filter-clear-btn">Clear filters</button>
      </aside>

      <main class="library-main">
        <div class="library-toolbar">
          <span id="lib-doc-count" class="lib-count">Loading…</span>
          <div style="flex:1"></div>
          <label class="filter-label" style="margin:0">Sort by</label>
          <select id="lib-sort" class="filter-select" style="width:160px">
            <option value="upload_date:desc">Upload date ↓</option>
            <option value="upload_date:asc">Upload date ↑</option>
            <option value="issue_date:desc">Issue date ↓</option>
            <option value="issue_date:asc">Issue date ↑</option>
            <option value="total_amount:desc">Amount ↓</option>
            <option value="total_amount:asc">Amount ↑</option>
            <option value="filename:asc">Filename A–Z</option>
            <option value="filename:desc">Filename Z–A</option>
          </select>
        </div>

        <div class="library-table-wrap">
          <table class="library-table">
            <thead>
              <tr>
                <th><input type="checkbox" id="lib-select-all"></th>
                <th>Filename</th>
                <th>Issuer</th>
                <th>Recipient</th>
                <th>Issue Date</th>
                <th class="text-right">Total</th>
                <th class="text-center">Status</th>
                <th class="text-center">Actions</th>
              </tr>
            </thead>
            <tbody id="lib-tbody">
              <tr><td colspan="8" class="lib-empty">Loading…</td></tr>
            </tbody>
          </table>
        </div>

        <div class="library-pagination" id="lib-pagination"></div>
      </main>
    </div>

    <div class="batch-bar" id="lib-batch-bar" style="display:none">
      <span id="lib-sel-count">0 selected</span>
      <span class="batch-sep">|</span>
      <span class="filter-label" style="margin:0">Export as</span>
      <select id="lib-export-fmt" class="filter-select" style="width:120px">
        <option value="xlsx">Excel (.xlsx)</option>
        <option value="csv">CSV</option>
        <option value="json">JSON</option>
      </select>
      <button id="lib-export-btn" class="batch-export-btn">⬇ Export ZIP</button>
      <div style="flex:1"></div>
      <button id="lib-clear-sel" class="filter-clear-btn">✕ Clear selection</button>
    </div>
  `;
}

// ── Data loading ──────────────────────────────────────────────
async function loadPage() {
  const skip = (currentPage - 1) * PAGE_SIZE;
  const params = {
    skip, limit: PAGE_SIZE,
    sort_by: sortBy, sort_order: sortOrder,
    ...filters,
  };
  try {
    const data = await api.listDocuments(params);
    totalDocs = data.total;
    renderTable(data.documents);
    renderPagination();
    document.getElementById('lib-doc-count').textContent =
      `${totalDocs} document${totalDocs !== 1 ? 's' : ''}`;
  } catch (err) {
    showToast('Failed to load documents: ' + err.message, 'error');
  }
}

// ── Table rendering ───────────────────────────────────────────
function renderTable(docs) {
  const tbody = document.getElementById('lib-tbody');
  if (!docs.length) {
    const msg = Object.keys(filters).length
      ? 'No documents match the current filters.'
      : 'No documents uploaded yet.';
    tbody.innerHTML = `<tr><td colspan="8" class="lib-empty">${msg}</td></tr>`;
    return;
  }
  tbody.innerHTML = docs.map(doc => {
    const checked = selectedIds.has(doc.id) ? 'checked' : '';
    const rowClass = selectedIds.has(doc.id) ? 'row--selected' : '';
    const statusBadge = renderStatusBadge(doc.extraction_status || doc.status);
    const canExport = doc.extraction_status && doc.status === 'completed';
    const isFailed = doc.status === 'failed';
    const actions = canExport
      ? `<button class="row-action" data-action="open" data-id="${doc.id}">Open</button>
         <span class="row-sep">|</span>
         <button class="row-action" data-action="export" data-id="${doc.id}">Export</button>`
      : isFailed
      ? `<button class="row-action" data-action="open" data-id="${doc.id}">Open</button>
         <span class="row-sep">|</span>
         <button class="row-action row-action--warn" data-action="retry" data-id="${doc.id}">Retry</button>`
      : `<button class="row-action" data-action="open" data-id="${doc.id}">Open</button>`;
    return `
      <tr class="lib-row ${rowClass}" data-id="${doc.id}">
        <td><input type="checkbox" class="row-check" data-id="${doc.id}" ${checked}></td>
        <td class="col-filename" title="${doc.filename}">${doc.filename}</td>
        <td class="col-vendor">${doc.issuer_name || '<span class="text-muted">—</span>'}</td>
        <td class="col-vendor">${doc.recipient_name || '<span class="text-muted">—</span>'}</td>
        <td>${doc.issue_date || '<span class="text-muted">—</span>'}</td>
        <td class="text-right">${doc.total_amount ? '€\u00A0' + parseFloat(doc.total_amount).toLocaleString('es-ES', {minimumFractionDigits:2}) : '<span class="text-muted">—</span>'}</td>
        <td class="text-center">${statusBadge}</td>
        <td class="text-center">${actions}</td>
      </tr>`;
  }).join('');
}

function renderStatusBadge(status) {
  const map = {
    valid: ['status-valid', 'Valid'],
    needs_review: ['status-review', '⚠ Review'],
    invalid: ['status-review', '⚠ Invalid'],
    completed: ['status-valid', 'Completed'],
    failed: ['status-failed', 'Failed'],
    pending: ['status-pending', 'Pending'],
    uploaded: ['status-pending', 'Uploaded'],
    running: ['status-pending', 'Processing…'],
  };
  const [cls, label] = map[status] || ['status-pending', status || '—'];
  return `<span class="status-badge status-badge--${cls}">${label}</span>`;
}

// ── Pagination ────────────────────────────────────────────────
function renderPagination() {
  const totalPages = Math.ceil(totalDocs / PAGE_SIZE);
  const el = document.getElementById('lib-pagination');
  if (totalPages <= 1) { el.innerHTML = ''; return; }
  const pages = Array.from({length: totalPages}, (_, i) => i + 1);
  el.innerHTML = `
    <span class="lib-page-info">Showing ${(currentPage-1)*PAGE_SIZE+1}–${Math.min(currentPage*PAGE_SIZE,totalDocs)} of ${totalDocs}</span>
    <button class="page-btn" data-page="${currentPage-1}" ${currentPage===1?'disabled':''}>← Prev</button>
    ${pages.slice(Math.max(0,currentPage-3), currentPage+2).map(p =>
      `<button class="page-btn ${p===currentPage?'page-btn--active':''}" data-page="${p}">${p}</button>`
    ).join('')}
    <button class="page-btn" data-page="${currentPage+1}" ${currentPage===totalPages?'disabled':''}>Next →</button>
  `;
}

// ── Event binding ─────────────────────────────────────────────
function bindFilterEvents() {
  const container = document.getElementById('library-container');

  // Search (live from nav bar input)
  const searchInput = document.getElementById('nav-search');
  if (searchInput) {
    searchInput.addEventListener('input', () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        filters.q = searchInput.value || undefined;
        currentPage = 1;
        selectedIds.clear();
        loadPage();
      }, 300);
    });
  }

  // Filter panel — delegated events
  container.addEventListener('change', (e) => {
    if (e.target.name === 'status') {
      const checked = [...document.querySelectorAll('[name="status"]:checked')].map(i => i.value);
      filters.status = checked.includes('all') || !checked.length ? undefined : checked[0];
    }
    if (e.target.id === 'lib-type') filters.invoice_type = e.target.value || undefined;
    if (e.target.id === 'lib-sort') {
      const [by, order] = e.target.value.split(':');
      sortBy = by; sortOrder = order;
    }
    currentPage = 1; selectedIds.clear(); loadPage();
  });

  container.addEventListener('input', (e) => {
    if (['lib-date-from','lib-date-to','lib-amount-min','lib-amount-max'].includes(e.target.id)) {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        filters.date_from = document.getElementById('lib-date-from').value || undefined;
        filters.date_to   = document.getElementById('lib-date-to').value || undefined;
        filters.amount_min = document.getElementById('lib-amount-min').value || undefined;
        filters.amount_max = document.getElementById('lib-amount-max').value || undefined;
        currentPage = 1; selectedIds.clear(); loadPage();
      }, 400);
    }
  });

  // Clear filters
  container.addEventListener('click', async (e) => {
    if (e.target.id === 'lib-clear-filters') {
      filters = {}; currentPage = 1; selectedIds.clear();
      document.getElementById('lib-date-from').value = '';
      document.getElementById('lib-date-to').value = '';
      document.getElementById('lib-amount-min').value = '';
      document.getElementById('lib-amount-max').value = '';
      document.getElementById('lib-type').value = '';
      document.querySelectorAll('[name="status"]').forEach(c => { c.checked = c.value === 'all'; });
      loadPage(); updateBatchBar(); return;
    }

    // Select all checkbox
    if (e.target.id === 'lib-select-all') {
      const rows = [...document.querySelectorAll('.row-check')];
      rows.forEach(c => {
        c.checked = e.target.checked;
        e.target.checked ? selectedIds.add(c.dataset.id) : selectedIds.delete(c.dataset.id);
      });
      updateBatchBar(); return;
    }

    // Row checkbox
    if (e.target.classList.contains('row-check')) {
      e.target.checked ? selectedIds.add(e.target.dataset.id) : selectedIds.delete(e.target.dataset.id);
      e.target.closest('tr').classList.toggle('row--selected', e.target.checked);
      updateBatchBar(); return;
    }

    // Pagination
    if (e.target.dataset.page) {
      const p = parseInt(e.target.dataset.page);
      if (p >= 1 && p <= Math.ceil(totalDocs / PAGE_SIZE)) {
        currentPage = p; selectedIds.clear(); loadPage(); updateBatchBar();
      }
      return;
    }

    // Row actions
    if (e.target.dataset.action === 'open') {
      const docId = e.target.dataset.id;
      setView('viewer');
      import('./viewer.js').then(({ selectDocument }) => selectDocument && selectDocument(docId));
      return;
    }
    if (e.target.dataset.action === 'export') {
      const docId = e.target.dataset.id;
      window.location.href = `/api/extract/${docId}/export?format=xlsx`;
      return;
    }
    if (e.target.dataset.action === 'retry') {
      const docId = e.target.dataset.id;
      try {
        await api.startOcr(docId, {});
        showToast('OCR restarted', 'success');
        loadPage();
      } catch (err) { showToast(err.message, 'error'); }
      return;
    }

    // Clear selection
    if (e.target.id === 'lib-clear-sel') {
      selectedIds.clear();
      document.querySelectorAll('.row-check').forEach(c => c.checked = false);
      updateBatchBar(); return;
    }

    // Export ZIP
    if (e.target.id === 'lib-export-btn') {
      const fmt = document.getElementById('lib-export-fmt').value;
      try {
        e.target.disabled = true;
        e.target.textContent = 'Preparing…';
        const resp = await api.batchExport({ document_ids: [...selectedIds], format: fmt });
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = `docscanai_export.zip`; a.click();
        URL.revokeObjectURL(url);
        showToast(`${selectedIds.size} document(s) exported`, 'success');
      } catch (err) {
        showToast('Export failed: ' + err.message, 'error');
      } finally {
        e.target.disabled = false;
        e.target.textContent = '⬇ Export ZIP';
      }
    }
  });
}

function updateBatchBar() {
  const bar = document.getElementById('lib-batch-bar');
  bar.style.display = selectedIds.size > 0 ? 'flex' : 'none';
  const countEl = document.getElementById('lib-sel-count');
  if (countEl) countEl.textContent = `${selectedIds.size} document${selectedIds.size !== 1 ? 's' : ''} selected`;
}
