/**
 * DocScan AI – Frontend application (ES module)
 *
 * API base: same origin, /api prefix
 * PDF rendering: PDF.js (vendored at ./lib/pdf.mjs)
 */

import * as pdfjsLib from "./lib/pdf.mjs";

// ─── PDF.js worker ───────────────────────────────────────────────────────────
pdfjsLib.GlobalWorkerOptions.workerSrc = "./lib/pdf.worker.mjs";

// ─── State ────────────────────────────────────────────────────────────────────
const state = {
  /** @type {number|null} */
  activeDocId: null,
  /** @type {import("pdfjs-dist").PDFDocumentProxy|null} */
  pdfDoc: null,
  currentPage: 1,
  totalPages: 1,
  scale: 1.5,
  /** @type {Map<number,ReturnType<typeof setInterval>>} */
  pollingTimers: new Map(),
  rendering: false,
  activeTab: "text",
  /** @type {ReturnType<typeof setInterval>|null} */
  extractionPolling: null,
};

// ─── DOM refs ─────────────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);

const uploadArea      = $("upload-area");
const uploadBtn       = $("upload-btn");
const fileInput       = $("file-input");
const docList         = $("doc-list");
const docListEmpty    = $("doc-list-empty");
const docCount        = $("doc-count");
const refreshBtn      = $("refresh-btn");

const viewerToolbar   = $("viewer-toolbar");
const viewerFilename  = $("viewer-filename");
const viewerEmpty     = $("viewer-empty");
const canvasWrapper   = $("canvas-wrapper");
const imageWrapper    = $("image-wrapper");
const pdfCanvas       = $("pdf-canvas");
const docImage        = $("doc-image");
const prevPageBtn     = $("prev-page");
const nextPageBtn     = $("next-page");
const pageInfo        = $("page-info");
const zoomOutBtn      = $("zoom-out");
const zoomInBtn       = $("zoom-in");
const zoomLevel       = $("zoom-level");

const textPanelActions = $("text-panel-actions");
const copyTextBtn     = $("copy-text-btn");
const textEmpty       = $("text-empty");
const textProcessing  = $("text-processing");
const progressBarWrap = $("progress-bar-wrapper");
const progressBar     = $("progress-bar");
const progressLabel   = $("progress-label");
const textContent     = $("text-content");

const tabText         = $("tab-text");
const tabOcr          = $("tab-ocr");
const tabInvoice      = $("tab-invoice");
const textTabContent  = $("text-tab-content");
const ocrTabContent   = $("ocr-tab-content");
const invoiceTabContent  = $("invoice-tab-content");
const reviewQueueSection = $("review-queue-section");
const reviewCount     = $("review-count");
const reviewList      = $("review-list");
const ocrEmpty        = $("ocr-empty");
const runOcrBtn       = $("run-ocr-btn");
const ocrProcessing   = $("ocr-processing");
const ocrProgressWrap = $("ocr-progress-wrapper");
const ocrProgressBar  = $("ocr-progress-bar");
const ocrProgressLabel = $("ocr-progress-label");
const ocrResults      = $("ocr-results");
const ocrSummary      = $("ocr-summary");
const ocrPages        = $("ocr-pages");

const toastContainer  = $("toast-container");

// ─── Toast ────────────────────────────────────────────────────────────────────
/**
 * @param {string} message
 * @param {"success"|"error"|"info"|"warning"} [type]
 * @param {number} [duration] ms
 */
function showToast(message, type = "info", duration = 4000) {
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  toastContainer.appendChild(toast);
  setTimeout(() => {
    toast.style.animation = "toast-out 200ms ease forwards";
    setTimeout(() => toast.remove(), 200);
  }, duration);
}

// ─── API helpers ──────────────────────────────────────────────────────────────
const API = "/api";

async function apiFetch(path, options = {}) {
  const res = await fetch(`${API}${path}`, options);
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try { const j = await res.json(); msg = j.detail || j.message || msg; } catch {}
    throw new Error(msg);
  }
  return res;
}

async function apiJson(path, options = {}) {
  const res = await apiFetch(path, options);
  return res.json();
}

// ─── Document list ────────────────────────────────────────────────────────────
async function loadDocumentList() {
  try {
    const data = await apiJson("/documents/?skip=0&limit=50");
    const docs = data.documents ?? [];
    renderDocumentList(docs);
    loadReviewQueue(docs);
  } catch (err) {
    showToast(`Failed to load documents: ${err.message}`, "error");
  }
}

/**
 * @param {Array<object>} docs
 */
function renderDocumentList(docs) {
  // Remove all existing document items (keep the empty placeholder)
  Array.from(docList.querySelectorAll(".doc-item")).forEach((el) => el.remove());

  const count = docs.length;
  docCount.textContent = `${count} document${count !== 1 ? "s" : ""}`;
  docListEmpty.hidden = count > 0;

  docs.forEach((doc) => {
    docList.appendChild(buildDocItem(doc));
  });
}

/**
 * @param {object} doc
 */
function buildDocItem(doc) {
  const isPdf = (doc.format ?? doc.filename ?? "").toLowerCase().endsWith("pdf") ||
                (doc.format ?? "").toLowerCase() === "pdf";

  const li = document.createElement("li");
  li.className = "doc-item";
  li.dataset.id = doc.id;
  if (doc.id === state.activeDocId) li.classList.add("active");

  const iconColor = isPdf ? "pdf-icon" : "img-icon";
  const iconPath = isPdf
    ? `<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
       <polyline points="14,2 14,8 20,8"/>
       <path d="M9 15h6M9 18h6M9 12h2"/>`
    : `<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/>
       <polyline points="21,15 16,10 5,21"/>`;

  const sizeFmt = formatBytes(doc.file_size ?? 0);
  const statusLabel = doc.status ?? "uploaded";

  li.innerHTML = `
    <div class="doc-icon ${iconColor}">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">${iconPath}</svg>
    </div>
    <div class="doc-info">
      <div class="doc-name" title="${escHtml(doc.filename)}">${escHtml(doc.filename)}</div>
      <div class="doc-meta">
        ${sizeFmt}
        &nbsp;·&nbsp;
        <span class="status-badge status-${statusLabel}">${statusLabel}</span>
      </div>
    </div>
    <div class="doc-actions">
      <button class="btn btn-danger btn-sm delete-btn" data-id="${doc.id}" title="Delete document">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="3,6 5,6 21,6"/>
          <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>
          <path d="M10 11v6M14 11v6"/>
          <path d="M9 6V4h6v2"/>
        </svg>
      </button>
    </div>
  `;

  li.addEventListener("click", (e) => {
    if (e.target.closest(".delete-btn")) return;
    selectDocument(doc.id);
  });

  li.querySelector(".delete-btn").addEventListener("click", (e) => {
    e.stopPropagation();
    deleteDocument(doc.id, li);
  });

  return li;
}

function updateDocItemStatus(docId, status) {
  const li = docList.querySelector(`.doc-item[data-id="${docId}"]`);
  if (!li) return;
  const badge = li.querySelector(".status-badge");
  if (badge) {
    badge.className = `status-badge status-${status}`;
    badge.textContent = status;
  }
}

// ─── Select / open document ───────────────────────────────────────────────────
async function selectDocument(docId) {
  state.activeDocId = docId;

  // Update active state in list
  docList.querySelectorAll(".doc-item").forEach((el) => {
    el.classList.toggle("active", parseInt(el.dataset.id) === docId);
  });

  try {
    const doc = await apiJson(`/documents/${docId}`);
    viewerFilename.textContent = doc.filename;
    viewerToolbar.hidden = false;

    await renderDocumentPreview(doc);
    await refreshTextPanel(doc);
    await refreshOCRPanel(doc);
    await loadInvoicePanel(docId);
  } catch (err) {
    showToast(`Failed to open document: ${err.message}`, "error");
  }
}

// ─── Document preview ─────────────────────────────────────────────────────────
async function renderDocumentPreview(doc) {
  const isPdf = isDocPdf(doc);

  viewerEmpty.hidden = true;
  canvasWrapper.hidden = true;
  imageWrapper.hidden = true;

  if (isPdf) {
    canvasWrapper.hidden = false;
    await loadPdf(doc.id);
  } else {
    imageWrapper.hidden = false;
    docImage.src = `/api/documents/${doc.id}/file`;
  }
}

function isDocPdf(doc) {
  const fmt = (doc.format ?? "").toLowerCase();
  const name = (doc.filename ?? "").toLowerCase();
  return fmt === "pdf" || name.endsWith(".pdf");
}

async function loadPdf(docId) {
  try {
    if (state.pdfDoc) {
      state.pdfDoc.destroy();
      state.pdfDoc = null;
    }

    const url = `/api/documents/${docId}/file`;
    const loadingTask = pdfjsLib.getDocument(url);
    state.pdfDoc = await loadingTask.promise;
    state.totalPages = state.pdfDoc.numPages;
    state.currentPage = 1;

    updatePageInfo();
    await renderPage(state.currentPage);
  } catch (err) {
    showToast(`PDF render error: ${err.message}`, "error");
  }
}

async function renderPage(pageNum) {
  if (!state.pdfDoc || state.rendering) return;
  state.rendering = true;

  try {
    const page = await state.pdfDoc.getPage(pageNum);
    const viewport = page.getViewport({ scale: state.scale });

    const ctx = pdfCanvas.getContext("2d");
    pdfCanvas.width  = viewport.width;
    pdfCanvas.height = viewport.height;

    await page.render({ canvasContext: ctx, viewport }).promise;
  } catch (err) {
    showToast(`Page render error: ${err.message}`, "error");
  } finally {
    state.rendering = false;
  }
}

function updatePageInfo() {
  pageInfo.textContent = `Page ${state.currentPage} / ${state.totalPages}`;
  prevPageBtn.disabled = state.currentPage <= 1;
  nextPageBtn.disabled = state.currentPage >= state.totalPages;
  zoomLevel.textContent = `${Math.round(state.scale * 100)}%`;
}

// ─── Pagination & Zoom ────────────────────────────────────────────────────────
prevPageBtn.addEventListener("click", async () => {
  if (state.currentPage > 1) {
    state.currentPage--;
    updatePageInfo();
    await renderPage(state.currentPage);
  }
});

nextPageBtn.addEventListener("click", async () => {
  if (state.currentPage < state.totalPages) {
    state.currentPage++;
    updatePageInfo();
    await renderPage(state.currentPage);
  }
});

zoomInBtn.addEventListener("click", async () => {
  state.scale = Math.min(state.scale + 0.25, 4.0);
  updatePageInfo();
  if (state.pdfDoc) await renderPage(state.currentPage);
});

zoomOutBtn.addEventListener("click", async () => {
  state.scale = Math.max(state.scale - 0.25, 0.5);
  updatePageInfo();
  if (state.pdfDoc) await renderPage(state.currentPage);
});

// ─── Text panel ───────────────────────────────────────────────────────────────
async function refreshTextPanel(doc) {
  const status = doc.status ?? "uploaded";

  textEmpty.hidden = true;
  textProcessing.hidden = true;
  textContent.hidden = true;
  textPanelActions.hidden = true;

  if (status === "processing" || status === "uploaded") {
    textProcessing.hidden = false;
    progressBarWrap.hidden = true;
    progressLabel.textContent = status === "processing" ? "Running OCR…" : "Waiting to start…";
    startPolling(doc.id);
    return;
  }

  if (status === "failed") {
    textEmpty.hidden = false;
    textEmpty.querySelector("p").textContent = "Processing failed";
    return;
  }

  // completed
  try {
    const data = await apiJson(`/documents/${doc.id}/text`);
    const text = data.text_content ?? "";
    if (text.trim()) {
      textContent.textContent = text;
      textContent.hidden = false;
      textPanelActions.hidden = false;
    } else {
      textEmpty.hidden = false;
      textEmpty.querySelector("p").textContent = "No text extracted";
    }
  } catch (err) {
    showToast(`Failed to load text: ${err.message}`, "error");
    textEmpty.hidden = false;
  }
}

// ─── OCR panel refresh ────────────────────────────────────────────────────────
async function refreshOCRPanel(doc) {
  ocrEmpty.hidden = false;
  ocrProcessing.hidden = true;
  ocrResults.hidden = true;
  runOcrBtn.hidden = true;

  // Show "Run OCR" button for scanned docs or images without OCR results
  const isImage = !isDocPdf(doc);
  if (doc.is_scanned || isImage) {
    runOcrBtn.hidden = false;
  }

  // If we already have OCR confidence, load the results
  if (doc.ocr_confidence != null) {
    await loadOCRResults(doc.id);
  }
}

// ─── Job polling ──────────────────────────────────────────────────────────────
function startPolling(docId) {
  if (state.pollingTimers.has(docId)) return; // already polling

  const timer = setInterval(async () => {
    try {
      const data = await apiJson(`/jobs/document/${docId}`);
      const jobs = data.jobs ?? [];
      const latest = jobs[jobs.length - 1];

      if (!latest) return;

      const progress = latest.progress ?? 0;
      const jobStatus = latest.status ?? "pending";

      // Update progress bar if visible on active doc
      if (docId === state.activeDocId) {
        progressBarWrap.hidden = false;
        progressBar.style.width = `${Math.min(progress, 100)}%`;
        progressLabel.textContent = jobStatus === "processing"
          ? `${Math.round(progress)}%…`
          : jobStatus;
      }

      updateDocItemStatus(docId, jobStatus === "completed" ? "completed"
                              : jobStatus === "failed"    ? "failed"
                              : "processing");

      if (jobStatus === "completed" || jobStatus === "failed") {
        stopPolling(docId);

        if (docId === state.activeDocId) {
          const doc = await apiJson(`/documents/${docId}`);
          await refreshTextPanel(doc);
        }

        if (jobStatus === "completed") {
          showToast("Processing complete!", "success");
        } else {
          const errMsg = latest.error ?? "Unknown error";
          showToast(`Processing failed: ${errMsg}`, "error");
        }

        // Refresh list to reflect final status
        await loadDocumentList();
      }
    } catch (err) {
      // Non-fatal: keep polling
    }
  }, 2000);

  state.pollingTimers.set(docId, timer);
}

function stopPolling(docId) {
  const timer = state.pollingTimers.get(docId);
  if (timer !== undefined) {
    clearInterval(timer);
    state.pollingTimers.delete(docId);
  }
}

// ─── Tab switching ────────────────────────────────────────────────────────────
function switchTab(tab) {
  state.activeTab = tab;
  tabText.classList.toggle("active", tab === "text");
  tabOcr.classList.toggle("active", tab === "ocr");
  tabInvoice.classList.toggle("active", tab === "invoice");
  textTabContent.hidden = tab !== "text";
  ocrTabContent.hidden = tab !== "ocr";
  invoiceTabContent.hidden = tab !== "invoice";
}

tabText.addEventListener("click", () => switchTab("text"));
tabOcr.addEventListener("click", () => switchTab("ocr"));
tabInvoice.addEventListener("click", () => switchTab("invoice"));

// ─── OCR ──────────────────────────────────────────────────────────────────────
async function runOCR(docId) {
  try {
    ocrEmpty.hidden = true;
    ocrProcessing.hidden = false;
    ocrResults.hidden = true;
    ocrProgressWrap.hidden = true;
    ocrProgressLabel.textContent = "Starting…";

    await apiJson(`/ocr/${docId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lang: "spa+eng", preprocess: true }),
    });

    showToast("OCR started", "info");
    startOCRPolling(docId);
  } catch (err) {
    ocrProcessing.hidden = true;
    ocrEmpty.hidden = false;
    showToast(`OCR failed: ${err.message}`, "error");
  }
}

function startOCRPolling(docId) {
  const key = `ocr_${docId}`;
  if (state.pollingTimers.has(key)) return;

  const timer = setInterval(async () => {
    try {
      const data = await apiJson(`/jobs/document/${docId}`);
      const jobs = data.jobs ?? [];
      const ocrJob = jobs.find(j => j.job_type === "ocr" && (j.status === "running" || j.status === "pending"));
      const completedOcr = jobs.find(j => j.job_type === "ocr" && j.status === "completed");
      const failedOcr = jobs.find(j => j.job_type === "ocr" && j.status === "failed");

      if (ocrJob && docId === state.activeDocId) {
        ocrProgressWrap.hidden = false;
        const pct = Math.round((ocrJob.progress ?? 0) * 100);
        ocrProgressBar.style.width = `${pct}%`;
        ocrProgressLabel.textContent = `${pct}%`;
      }

      if (completedOcr || failedOcr) {
        stopOCRPolling(docId);

        if (docId === state.activeDocId) {
          if (completedOcr) {
            await loadOCRResults(docId);
            showToast("OCR complete!", "success");
          } else {
            ocrProcessing.hidden = true;
            ocrEmpty.hidden = false;
            showToast(`OCR failed: ${failedOcr.error ?? "Unknown error"}`, "error");
          }
        }
        await loadDocumentList();
      }
    } catch {
      // keep polling
    }
  }, 2000);

  state.pollingTimers.set(key, timer);
}

function stopOCRPolling(docId) {
  const key = `ocr_${docId}`;
  const timer = state.pollingTimers.get(key);
  if (timer !== undefined) {
    clearInterval(timer);
    state.pollingTimers.delete(key);
  }
}

async function loadOCRResults(docId) {
  try {
    const data = await apiJson(`/ocr/${docId}/result`);
    ocrProcessing.hidden = true;
    ocrEmpty.hidden = true;
    ocrResults.hidden = false;

    ocrSummary.innerHTML = `
      <div class="ocr-summary-row">
        <span>Overall confidence:</span>
        ${confidenceBadge(data.average_confidence)}
      </div>
      <div class="ocr-summary-row">
        <span>Pages: ${data.page_count}</span>
        ${data.low_confidence_pages.length > 0
          ? `<span class="low-conf-warning">Low confidence on page${data.low_confidence_pages.length > 1 ? "s" : ""} ${data.low_confidence_pages.join(", ")}</span>`
          : ""}
      </div>
    `;

    ocrPages.innerHTML = "";
    for (const page of data.pages) {
      const card = document.createElement("div");
      card.className = "ocr-page-card";
      card.innerHTML = `
        <div class="ocr-page-header">
          <span class="ocr-page-num">Page ${page.page_number}</span>
          ${confidenceBadge(page.average_confidence)}
          <span class="ocr-word-count">${page.word_count} words</span>
        </div>
        <pre class="ocr-page-text">${escHtml(page.text)}</pre>
      `;
      ocrPages.appendChild(card);
    }
  } catch (err) {
    ocrProcessing.hidden = true;
    ocrEmpty.hidden = false;
  }
}

function confidenceBadge(score) {
  let cls = "confidence-low";
  if (score >= 80) cls = "confidence-high";
  else if (score >= 70) cls = "confidence-medium";
  return `<span class="confidence-badge ${cls}">${Math.round(score)}%</span>`;
}

runOcrBtn.addEventListener("click", () => {
  if (state.activeDocId) runOCR(state.activeDocId);
});

// ─── Copy text ────────────────────────────────────────────────────────────────
copyTextBtn.addEventListener("click", async () => {
  const text = textContent.textContent;
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    showToast("Text copied to clipboard", "success", 2000);
  } catch {
    showToast("Copy failed – try selecting the text manually", "warning");
  }
});

// ─── Delete document ──────────────────────────────────────────────────────────
async function deleteDocument(docId, listItem) {
  try {
    await apiFetch(`/documents/${docId}`, { method: "DELETE" });

    stopPolling(docId);

    listItem.style.transition = "opacity 150ms ease";
    listItem.style.opacity = "0";
    setTimeout(() => listItem.remove(), 150);

    if (state.activeDocId === docId) {
      state.activeDocId = null;
      if (state.pdfDoc) { state.pdfDoc.destroy(); state.pdfDoc = null; }
      viewerToolbar.hidden = true;
      viewerEmpty.hidden = false;
      canvasWrapper.hidden = true;
      imageWrapper.hidden = true;
      textEmpty.hidden = false;
      textContent.hidden = true;
      textProcessing.hidden = true;
      textPanelActions.hidden = true;
      textEmpty.querySelector("p").textContent = "No text extracted yet";
      // Reset OCR panel
      ocrEmpty.hidden = false;
      ocrProcessing.hidden = true;
      ocrResults.hidden = true;
      runOcrBtn.hidden = true;
      // Reset Invoice panel
      document.getElementById('invoice-download-bar').style.display = 'none';
      document.getElementById('extraction-not-started').style.display = 'none';
      document.getElementById('invoice-empty').style.display = 'none';
      document.getElementById('invoice-processing').style.display = 'none';
      document.getElementById('invoice-panel').style.display = 'none';
      document.getElementById('invoice-panel').innerHTML = '';
      if (state.extractionPolling) {
        clearInterval(state.extractionPolling);
        state.extractionPolling = null;
      }
      switchTab("text");
    }

    // Update count
    const remaining = docList.querySelectorAll(".doc-item").length;
    docCount.textContent = `${remaining} document${remaining !== 1 ? "s" : ""}`;
    docListEmpty.hidden = remaining > 0;

    showToast("Document deleted", "info", 2500);
  } catch (err) {
    showToast(`Delete failed: ${err.message}`, "error");
  }
}

// ─── Upload ───────────────────────────────────────────────────────────────────
function triggerUpload() { fileInput.click(); }

uploadBtn.addEventListener("click", (e) => { e.stopPropagation(); triggerUpload(); });
uploadArea.addEventListener("click", triggerUpload);

fileInput.addEventListener("change", () => {
  const files = Array.from(fileInput.files ?? []);
  fileInput.value = "";
  files.forEach(uploadFile);
});

// Drag-and-drop
uploadArea.addEventListener("dragover", (e) => {
  e.preventDefault();
  uploadArea.classList.add("drag-over");
});

uploadArea.addEventListener("dragleave", (e) => {
  if (!uploadArea.contains(e.relatedTarget)) {
    uploadArea.classList.remove("drag-over");
  }
});

uploadArea.addEventListener("drop", (e) => {
  e.preventDefault();
  uploadArea.classList.remove("drag-over");
  const files = Array.from(e.dataTransfer.files ?? []);
  files.forEach(uploadFile);
});

async function uploadFile(file) {
  const formData = new FormData();
  formData.append("file", file);

  showToast(`Uploading ${file.name}…`, "info", 6000);

  try {
    const res = await apiFetch("/documents/upload", {
      method: "POST",
      body: formData,
    });
    const doc = await res.json();

    showToast(`${file.name} uploaded`, "success");

    // Add to list immediately with "uploaded" status
    docListEmpty.hidden = true;
    const li = buildDocItem(doc);
    docList.insertBefore(li, docList.firstChild);
    const count = docList.querySelectorAll(".doc-item").length;
    docCount.textContent = `${count} document${count !== 1 ? "s" : ""}`;

    // Start polling for job status
    startPolling(doc.id);

    // Auto-select if nothing is open
    if (state.activeDocId === null) {
      selectDocument(doc.id);
    }
  } catch (err) {
    showToast(`Upload failed: ${err.message}`, "error");
  }
}

// ─── Refresh button ───────────────────────────────────────────────────────────
refreshBtn.addEventListener("click", loadDocumentList);

// ─── Invoice download handlers ────────────────────────────────────────────────
document.getElementById('download-md-btn').addEventListener('click', async () => {
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

document.getElementById('download-csv-btn').addEventListener('click', async () => {
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

document.getElementById('run-extraction-btn').addEventListener('click', async () => {
  if (state.activeDocId) await runExtraction(state.activeDocId);
});

// ─── Utilities ────────────────────────────────────────────────────────────────
function formatBytes(bytes) {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0)} ${units[i]}`;
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ─── Invoice panel ────────────────────────────────────────────────────────────
async function loadInvoicePanel(docId) {
  // Clear any existing extraction polling
  if (state.extractionPolling) {
    clearInterval(state.extractionPolling);
    state.extractionPolling = null;
  }

  // Reset all states
  document.getElementById('invoice-download-bar').style.display = 'none';
  document.getElementById('extraction-not-started').style.display = 'none';
  document.getElementById('invoice-empty').style.display = 'none';
  document.getElementById('invoice-processing').style.display = 'none';
  document.getElementById('invoice-panel').style.display = 'none';
  document.getElementById('invoice-panel').innerHTML = '';

  try {
    const data = await apiJson(`/extract/${docId}`);
    const status = data.job_status;

    if (status === 'not_started') {
      document.getElementById('extraction-not-started').style.display = 'block';
    } else if (status === 'pending' || status === 'running') {
      document.getElementById('invoice-processing').style.display = 'block';
      state.extractionPolling = setInterval(async () => {
        if (state.activeDocId !== docId) {
          clearInterval(state.extractionPolling);
          state.extractionPolling = null;
          return;
        }
        try {
          const d = await apiJson(`/extract/${docId}`);
          if (d.job_status === 'completed' || d.job_status === 'failed') {
            clearInterval(state.extractionPolling);
            state.extractionPolling = null;
            await loadInvoicePanel(docId);
          }
        } catch {}
      }, 2000);
    } else if (status === 'failed') {
      document.getElementById('invoice-panel').innerHTML = `
        <p>Extraction failed.</p>
        <button id="retry-extraction-btn" class="btn btn-primary">Retry Extraction</button>
      `;
      document.getElementById('invoice-panel').style.display = 'block';
      document.getElementById('retry-extraction-btn').addEventListener('click', async () => {
        await runExtraction(docId);
      });
    } else if (status === 'completed' && data.invoice_json_available && data.invoice) {
      renderInvoiceData(data);
    } else {
      document.getElementById('invoice-empty').style.display = 'block';
    }
  } catch {
    document.getElementById('invoice-empty').style.display = 'block';
  }
}

async function runExtraction(docId) {
  try {
    await apiJson(`/extract/${docId}`, { method: 'POST' });
    showToast('Extraction started', 'info');
    await loadInvoicePanel(docId);
  } catch (err) {
    showToast(`Extraction failed to start: ${err.message}`, 'error');
  }
}

function renderInvoiceData(data) {
  const invoicePanel = document.getElementById('invoice-panel');
  const invoice = data.invoice;
  const anchor = invoice.anchor || {};
  const discovered = invoice.discovered || {};
  const allIssues = data.validation_issues || invoice.issues || [];

  // Show download bar
  document.getElementById('invoice-download-bar').style.display = 'block';

  // Review banner
  let html = '';
  if (invoice.requires_review) {
    html += `<div class="manual-review-banner"><strong>⚠️ This invoice requires manual review</strong></div>`;
  }

  // --- Critical Fields Card ---
  html += `<div style="margin-bottom:12px"><strong>Critical Fields</strong><table style="width:100%;border-collapse:collapse;margin-top:6px">`;
  const cur = escHtml(anchor.currency || 'EUR');
  const criticalFields = [
    ['Invoice Number', anchor.invoice_number ? escHtml(anchor.invoice_number) : null],
    ['Date', anchor.issue_date ? escHtml(anchor.issue_date) : null],
    ['Issuer', anchor.issuer_name ? escHtml(anchor.issuer_name) : null],
    ['Issuer CIF', anchor.issuer_cif ? escHtml(anchor.issuer_cif) : null],
    ['Recipient', anchor.recipient_name ? escHtml(anchor.recipient_name) : null],
    ['Recipient CIF', anchor.recipient_cif ? escHtml(anchor.recipient_cif) : null],
    ['Base Imponible', anchor.base_imponible ? `${escHtml(String(anchor.base_imponible))} ${cur}` : null],
    ['IVA Rate', anchor.iva_rate ? `${escHtml(String(anchor.iva_rate))}%` : null],
    ['IVA Amount', anchor.iva_amount ? `${escHtml(String(anchor.iva_amount))} ${cur}` : null],
    ['IRPF Rate', anchor.irpf_rate ? `${escHtml(String(anchor.irpf_rate))}%` : null],
    ['IRPF Amount', anchor.irpf_amount ? `-${escHtml(String(anchor.irpf_amount))} ${cur}` : null],
    ['Total', anchor.total_amount ? `${escHtml(String(anchor.total_amount))} ${cur}` : null],
  ];
  const totalLabel = 'Total';
  for (const [label, value] of criticalFields) {
    const display = value != null ? value : '<span style="color:var(--text-muted,#888)">—</span>';
    const isTotal = label === totalLabel;
    const tdStyle = isTotal ? 'padding:3px 0;font-weight:bold' : 'padding:3px 0';
    html += `<tr><td style="padding:3px 8px 3px 0;color:var(--text-muted,#888);width:40%">${escHtml(label)}</td><td style="${tdStyle}">${display}</td></tr>`;
  }
  html += `</table></div>`;

  // --- Additional Details ---
  if (Object.keys(discovered).length > 0) {
    html += `<details style="margin-bottom:12px"><summary><strong>Additional Details</strong></summary><div style="margin-top:6px">`;
    html += renderDict(discovered);
    html += `</div></details>`;
  }

  // --- Issues Panel ---
  if (allIssues.length > 0) {
    html += `<div style="margin-bottom:12px"><strong>Issues & Observations</strong><ul style="list-style:none;padding:0;margin:6px 0 0">`;
    for (const issue of allIssues) {
      const icon = issue.severity === 'error' ? '❌' : issue.severity === 'warning' ? '⚠️' : 'ℹ️';
      const fieldNote = issue.field ? ` <code>${escHtml(issue.field)}</code>:` : '';
      html += `<li style="padding:4px 0;border-bottom:1px solid var(--border,#eee)">${icon}${fieldNote} ${escHtml(issue.message)}</li>`;
    }
    html += `</ul></div>`;
  }

  invoicePanel.innerHTML = html;
  invoicePanel.style.display = 'block';
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

// ─── Review queue ─────────────────────────────────────────────────────────────
async function loadReviewQueue(docs) {
  const needsReview = [];
  for (const doc of docs.slice(0, 50)) {
    try {
      const data = await apiJson(`/extract/${doc.id}`);
      if (data.invoice_json_available && data.invoice && data.invoice.requires_review) {
        needsReview.push(doc);
      }
    } catch {}
  }

  if (needsReview.length === 0) {
    reviewQueueSection.hidden = true;
    return;
  }

  reviewQueueSection.hidden = false;
  reviewCount.textContent = needsReview.length;
  reviewList.innerHTML = "";
  for (const doc of needsReview) {
    const li = document.createElement("li");
    li.className = "doc-item";
    li.innerHTML = `<div class="doc-info"><div class="doc-name" title="${escHtml(doc.filename)}">${escHtml(doc.filename)}</div></div>`;
    li.addEventListener("click", () => selectDocument(doc.id));
    reviewList.appendChild(li);
  }
}

// ─── Init ─────────────────────────────────────────────────────────────────────
loadDocumentList();
