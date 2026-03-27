// frontend/src/tabs/invoice.js
// Invoice/extraction tab — start extraction button, display invoice fields,
// field editing/corrections, re-extract field, template manager, export.

import * as api from "../api.js";
import { showToast } from "../ui.js";

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderDict(obj, depth = 0) {
  if (typeof obj !== 'object' || obj === null) return escHtml(String(obj));
  let html = '<dl style="margin:0;padding-left:' + (depth * 12) + 'px">';
  for (const [k, v] of Object.entries(obj)) {
    html += `<dt style="font-weight:600;color:var(--text-muted,#888);font-size:0.85em">${escHtml(k)}</dt><dd style="margin:0 0 4px 12px">`;
    if (Array.isArray(v)) {
      html += v.map(item => typeof item === 'object' ? renderDict(item, depth + 1) : escHtml(String(item))).join(', ');
    } else if (typeof v === 'object' && v !== null) {
      html += renderDict(v, depth + 1);
    } else {
      html += escHtml(String(v ?? ''));
    }
    html += '</dd>';
  }
  return html + '</dl>';
}

export function initInvoiceTab(state) {
  const $ = (id) => document.getElementById(id);

  // ── Invoice download handlers ─────────────────────────────────────────────────
  $('download-md-btn').addEventListener('click', async () => {
    if (!state.activeDocId) return;
    try {
      const resp = await fetch(`/api/extract/${state.activeDocId}/export?format=md`);
      if (!resp.ok) { showToast('No extraction available', 'warning'); return; }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `invoice-${state.activeDocId}.md`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      showToast(`Download failed: ${err.message}`, 'error');
    }
  });

  $('download-csv-btn').addEventListener('click', async () => {
    if (!state.activeDocId) return;
    try {
      const resp = await fetch(`/api/extract/${state.activeDocId}/export?format=csv`);
      if (!resp.ok) { showToast('No extraction available', 'warning'); return; }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `invoice-${state.activeDocId}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      showToast(`Download failed: ${err.message}`, 'error');
    }
  });

  $('download-xlsx-btn').addEventListener('click', () => {
    if (!state.activeDocId) return;
    const tmplId = $('template-select').value;
    const url = `/api/extract/${state.activeDocId}/export?format=xlsx${tmplId ? '&template_id=' + tmplId : ''}`;
    window.location.href = url;
  });

  $('download-docx-btn').addEventListener('click', () => {
    if (!state.activeDocId) return;
    const tmplId = $('template-select').value;
    const url = `/api/extract/${state.activeDocId}/export?format=docx${tmplId ? '&template_id=' + tmplId : ''}`;
    window.location.href = url;
  });

  $('run-extraction-btn').addEventListener('click', async () => {
    if (state.activeDocId) await runExtraction(state.activeDocId, state);
  });

  // ── Invoice panel event delegation (edit / lock / re-extract) ────────────────
  $('invoice-panel').addEventListener('click', async (e) => {
    const docId = state.activeDocId;
    if (!docId) return;

    // Edit button
    if (e.target.closest('.edit-btn')) {
      const btn = e.target.closest('.edit-btn');
      const fieldPath = btn.dataset.field;
      const row = btn.closest('.field-row');
      if (!row) return;
      const valueSpan = row.querySelector('.field-value');
      if (!valueSpan) return;
      const currentVal = valueSpan.textContent;

      const input = document.createElement('input');
      input.className = 'field-edit-input';
      input.value = currentVal;
      valueSpan.replaceWith(input);
      input.focus();

      btn.textContent = '';
      const saveBtn = document.createElement('button');
      saveBtn.className = 'field-action-btn';
      saveBtn.title = 'Save';
      saveBtn.textContent = '\u2713';
      const cancelBtn = document.createElement('button');
      cancelBtn.className = 'field-action-btn';
      cancelBtn.title = 'Cancel';
      cancelBtn.textContent = '\u2715';
      btn.replaceWith(saveBtn);
      saveBtn.after(cancelBtn);

      saveBtn.addEventListener('click', async () => {
        const newVal = input.value.trim();
        const result = await saveCorrectionFn(docId, fieldPath, newVal, state);
        if (result) {
          showToast('Correction saved', 'success');
          await loadInvoicePanel(docId, state);
        } else {
          showToast('Failed to save correction', 'error');
        }
      });

      cancelBtn.addEventListener('click', () => {
        loadInvoicePanel(docId, state);
      });

      return;
    }

    // Lock button
    if (e.target.closest('.lock-btn')) {
      const btn = e.target.closest('.lock-btn');
      const fieldPath = btn.dataset.field;
      const correction = state.corrections[fieldPath];
      if (!correction) {
        showToast('Save a correction first to lock it', 'warning');
        return;
      }
      const newLocked = !correction.is_locked;
      const result = await toggleLockFn(docId, fieldPath, newLocked, state);
      if (result) {
        showToast(newLocked ? 'Field locked' : 'Field unlocked', 'info');
        await loadInvoicePanel(docId, state);
      } else {
        showToast('Failed to toggle lock', 'error');
      }
      return;
    }

    // Re-extract button
    if (e.target.closest('.reextract-btn')) {
      const btn = e.target.closest('.reextract-btn');
      const fieldPath = btn.dataset.field;
      const origText = btn.textContent;
      btn.innerHTML = '<span class="re-extract-spinner"></span>';
      btn.disabled = true;
      const result = await reextractFieldFn(docId, fieldPath);
      btn.disabled = false;
      btn.textContent = origText;
      if (result) {
        showToast('Field re-extracted', 'success');
        await loadInvoicePanel(docId, state);
      } else {
        showToast('Re-extract failed', 'error');
      }
      return;
    }
  });

  // ── Template form buttons ─────────────────────────────────────────────────────
  $('new-template-btn').addEventListener('click', () => {
    renderTemplateFieldCheckboxes();
    $('template-form').style.display = 'block';
  });

  $('cancel-template-btn').addEventListener('click', () => {
    $('template-form').style.display = 'none';
  });

  $('save-template-btn').addEventListener('click', async () => {
    const name = $('template-name-input').value.trim();
    if (!name) return;
    const checkboxes = document.querySelectorAll('#template-field-checkboxes input:checked');
    const fields = Array.from(checkboxes).map(cb => ({
      field_path: cb.value,
      display_name: cb.parentElement.textContent.trim(),
      include: true,
    }));
    if (await createTemplateFn(name, fields)) {
      $('template-form').style.display = 'none';
      $('template-name-input').value = '';
      await loadTemplates(state);
    }
  });

  // IVA summary download
  const ivaSummaryBtn = $('iva-summary-download-btn');
  if (ivaSummaryBtn) {
    ivaSummaryBtn.addEventListener('click', downloadIvaSummary);
  }
}

export async function loadInvoicePanel(docId, state) {
  const $ = (id) => document.getElementById(id);

  if (state.extractionPolling) {
    clearInterval(state.extractionPolling);
    state.extractionPolling = null;
  }

  $('invoice-download-bar').style.display = 'none';
  $('extraction-not-started').style.display = 'none';
  $('invoice-empty').style.display = 'none';
  $('invoice-processing').style.display = 'none';
  $('invoice-panel').style.display = 'none';
  $('invoice-panel').innerHTML = '';

  try {
    const data = await api.apiJson(`/extract/${docId}`);
    const status = data.job_status;

    if (status === 'not_started') {
      $('extraction-not-started').style.display = 'block';
    } else if (status === 'pending' || status === 'running') {
      $('invoice-processing').style.display = 'block';
      state.extractionPolling = setInterval(async () => {
        if (state.activeDocId !== docId) {
          clearInterval(state.extractionPolling);
          state.extractionPolling = null;
          return;
        }
        try {
          const d = await api.apiJson(`/extract/${docId}`);
          if (d.job_status === 'completed' || d.job_status === 'failed') {
            clearInterval(state.extractionPolling);
            state.extractionPolling = null;
            await loadInvoicePanel(docId, state);
          }
        } catch {}
      }, 2000);
    } else if (status === 'failed') {
      $('invoice-panel').innerHTML = `
        <p>Extraction failed.</p>
        <button id="retry-extraction-btn" class="btn btn-primary">Retry Extraction</button>
      `;
      $('invoice-panel').style.display = 'block';
      $('retry-extraction-btn').addEventListener('click', async () => {
        await runExtraction(docId, state);
      });
    } else if (status === 'completed' && data.invoice_json_available && data.invoice) {
      try {
        const corrResp = await fetch(`/api/corrections/${docId}`);
        if (corrResp.ok) {
          const corrData = await corrResp.json();
          state.corrections = {};
          for (const c of corrData.corrections) {
            state.corrections[c.field_path] = c;
          }
        }
      } catch {}
      await loadTemplates(state);
      renderInvoiceData(data, state.corrections);
    } else {
      $('invoice-empty').style.display = 'block';
    }
  } catch {
    document.getElementById('invoice-empty').style.display = 'block';
  }
}

async function runExtraction(docId, state) {
  try {
    await api.startExtraction(docId);
    showToast('Extraction started', 'info');
    await loadInvoicePanel(docId, state);
  } catch (err) {
    showToast(`Extraction failed to start: ${err.message}`, 'error');
  }
}

function renderField(fieldPath, label, rawValue, corrections) {
  const correction = corrections[fieldPath];
  const displayValue = correction ? correction.new_value : (rawValue ?? '');
  const isCorrected = !!correction;
  const isLocked = correction && correction.is_locked;

  return `
    <div class="field-row ${isCorrected ? 'corrected' : ''} ${isLocked ? 'locked' : ''}"
         data-field="${escHtml(fieldPath)}" style="position:relative;display:flex;align-items:center;gap:6px;padding:4px 0;">
      <span style="min-width:140px;font-weight:500;color:#374151;">${escHtml(label)}:</span>
      <span class="field-value" style="flex:1;">${escHtml(String(displayValue))}</span>
      <button class="field-action-btn edit-btn" title="Edit" data-field="${escHtml(fieldPath)}">&#x270E;</button>
      <button class="field-action-btn lock-btn" title="${isLocked ? 'Unlock' : 'Lock'}" data-field="${escHtml(fieldPath)}">${isLocked ? '&#x1F512;' : '&#x1F513;'}</button>
      <button class="field-action-btn reextract-btn" title="Re-extract" data-field="${escHtml(fieldPath)}">&#x27F3;</button>
    </div>
  `;
}

function renderInvoiceData(data, corrections) {
  corrections = corrections || {};
  const invoicePanel = document.getElementById('invoice-panel');
  const invoice = data.invoice;
  const anchor = invoice.anchor || {};
  const discovered = invoice.discovered || {};
  const allIssues = data.validation_issues || invoice.issues || [];

  document.getElementById('invoice-download-bar').style.display = 'block';

  let html = '';
  if (invoice.requires_review) {
    html += `<div class="manual-review-banner"><strong>&#x26A0;&#xFE0F; This invoice requires manual review</strong></div>`;
  }

  html += `<div style="margin-bottom:12px"><strong>Critical Fields</strong><div style="margin-top:6px">`;
  const editableFields = [
    ['anchor.invoice_number', 'Invoice Number', anchor.invoice_number ?? null],
    ['anchor.issue_date',     'Date',           anchor.issue_date ?? null],
    ['anchor.issuer_name',    'Issuer',         anchor.issuer_name ?? null],
    ['anchor.issuer_cif',     'Issuer CIF',     anchor.issuer_cif ?? null],
    ['anchor.recipient_name', 'Recipient',      anchor.recipient_name ?? null],
    ['anchor.recipient_cif',  'Recipient CIF',  anchor.recipient_cif ?? null],
    ['anchor.base_imponible', 'Base Imponible', anchor.base_imponible ?? null],
    ['anchor.iva_rate',       'IVA Rate',       anchor.iva_rate ?? null],
    ['anchor.iva_amount',     'IVA Amount',     anchor.iva_amount ?? null],
    ['anchor.irpf_rate',      'IRPF Rate',      anchor.irpf_rate ?? null],
    ['anchor.irpf_amount',    'IRPF Amount',    anchor.irpf_amount ?? null],
    ['anchor.total_amount',   'Total',          anchor.total_amount ?? null],
  ];
  for (const [fieldPath, label, rawValue] of editableFields) {
    html += renderField(fieldPath, label, rawValue, corrections);
  }
  html += `</div></div>`;

  if (Object.keys(discovered).length > 0) {
    html += `<details style="margin-bottom:12px"><summary><strong>Additional Details</strong></summary><div style="margin-top:6px">`;
    html += renderDict(discovered);
    html += `</div></details>`;
  }

  if (allIssues.length > 0) {
    html += `<div style="margin-bottom:12px"><strong>Issues & Observations</strong><ul style="list-style:none;padding:0;margin:6px 0 0">`;
    for (const issue of allIssues) {
      const icon = issue.severity === 'error' ? '&#x274C;' : issue.severity === 'warning' ? '&#x26A0;&#xFE0F;' : '&#x2139;&#xFE0F;';
      const fieldNote = issue.field ? ` <code>${escHtml(issue.field)}</code>:` : '';
      html += `<li style="padding:4px 0;border-bottom:1px solid var(--border,#eee)">${icon}${fieldNote} ${escHtml(issue.message)}</li>`;
    }
    html += `</ul></div>`;
  }

  invoicePanel.innerHTML = html;
  invoicePanel.style.display = 'block';
}

// ── Field editing helpers ─────────────────────────────────────────────────────
async function saveCorrectionFn(docId, fieldPath, newValue, state) {
  const resp = await fetch(`/api/corrections/${docId}`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ field_path: fieldPath, new_value: String(newValue) }),
  });
  if (resp.ok) {
    const data = await resp.json();
    state.corrections[fieldPath] = data;
    return data;
  }
  return null;
}

async function toggleLockFn(docId, fieldPath, isLocked, state) {
  const resp = await fetch(`/api/corrections/${docId}/lock`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ field_path: fieldPath, is_locked: isLocked }),
  });
  if (resp.ok) {
    const data = await resp.json();
    state.corrections[fieldPath] = data;
    return data;
  }
  return null;
}

async function reextractFieldFn(docId, fieldPath) {
  const resp = await fetch(`/api/extract/${docId}/reextract-field?field=${encodeURIComponent(fieldPath)}`, {
    method: 'POST',
  });
  return resp.ok ? await resp.json() : null;
}

// ── Template manager ──────────────────────────────────────────────────────────
async function loadTemplates(state) {
  const resp = await fetch('/api/templates');
  if (resp.ok) {
    state.templates = await resp.json();
    renderTemplateManager(state.templates);
    const sel = document.getElementById('template-select');
    if (!sel) return;
    const existing = sel.value;
    sel.innerHTML = '<option value="">No template</option>';
    state.templates.forEach(t => {
      const opt = document.createElement('option');
      opt.value = t.id;
      opt.textContent = t.name;
      sel.appendChild(opt);
    });
    if (existing) sel.value = existing;
  }
}

function renderTemplateManager(templates) {
  const list = document.getElementById('template-list');
  if (!list) return;
  if (!templates.length) {
    list.innerHTML = '<p style="color:#9ca3af;font-size:13px;">No templates</p>';
    return;
  }
  list.innerHTML = templates.map(t => `
    <div style="display:flex;align-items:center;gap:8px;padding:2px 0;">
      <span style="flex:1;font-size:13px;">${escHtml(t.name)}</span>
      <button class="field-action-btn" onclick="deleteTemplateFn('${escHtml(String(t.id))}')">&#x2715;</button>
    </div>
  `).join('');
}

function renderTemplateFieldCheckboxes() {
  const container = document.getElementById('template-field-checkboxes');
  if (!container) return;
  const ANCHOR_FIELDS = [
    {path:'anchor.invoice_number', label:'Invoice Number'},
    {path:'anchor.issuer_name', label:'Issuer Name'},
    {path:'anchor.issuer_cif', label:'Issuer CIF'},
    {path:'anchor.recipient_name', label:'Recipient Name'},
    {path:'anchor.recipient_cif', label:'Recipient CIF'},
    {path:'anchor.issue_date', label:'Issue Date'},
    {path:'anchor.total_amount', label:'Total Amount'},
    {path:'anchor.base_imponible', label:'Base Imponible'},
    {path:'anchor.iva_amount', label:'IVA Amount'},
    {path:'anchor.iva_rate', label:'IVA Rate'},
    {path:'lines', label:'Line Items'},
  ];
  container.innerHTML = ANCHOR_FIELDS.map(f => `
    <label style="display:block;font-size:13px;">
      <input type="checkbox" value="${escHtml(f.path)}" checked> ${escHtml(f.label)}
    </label>
  `).join('');
}

async function createTemplateFn(name, fields) {
  const resp = await fetch('/api/templates', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ name, fields }),
  });
  return resp.ok;
}

async function deleteTemplateFn(id) {
  const resp = await fetch(`/api/templates/${id}`, { method: 'DELETE' });
  if (resp.ok) {
    // Reload templates — we need the state, but this is called from inline onclick
    // so we re-fetch and re-render
    const listResp = await fetch('/api/templates');
    if (listResp.ok) {
      const templates = await listResp.json();
      renderTemplateManager(templates);
      const sel = document.getElementById('template-select');
      if (sel) {
        sel.innerHTML = '<option value="">No template</option>';
        templates.forEach(t => {
          const opt = document.createElement('option');
          opt.value = t.id;
          opt.textContent = t.name;
          sel.appendChild(opt);
        });
      }
    }
  }
}

// Expose deleteTemplateFn for inline onclick handlers in renderTemplateManager
window.deleteTemplateFn = deleteTemplateFn;

// ── IVA summary ───────────────────────────────────────────────────────────────
function downloadIvaSummary() {
  const $ = (id) => document.getElementById(id);
  const dateFrom = $('iva-date-from') ? $('iva-date-from').value : '';
  const dateTo = $('iva-date-to') ? $('iva-date-to').value : '';
  const role = $('iva-role') ? $('iva-role').value : 'recipient';

  let url = '/api/export/iva-summary/csv';
  const params = [];
  if (dateFrom) params.push(`date_from=${encodeURIComponent(dateFrom)}`);
  if (dateTo) params.push(`date_to=${encodeURIComponent(dateTo)}`);
  if (role) params.push(`role=${encodeURIComponent(role)}`);
  if (params.length) url += '?' + params.join('&');

  const a = document.createElement('a');
  a.href = url;
  a.download = 'iva-summary.csv';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}
