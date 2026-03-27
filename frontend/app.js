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
  /** @type {Object} field_path -> correction object */
  corrections: {},
  /** @type {Array} list of template objects */
  templates: [],
};

// ─── Chat state ───────────────────────────────────────────────────────────────
let currentChatSessionId = null;
let currentChatDocumentId = null;

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
const tabChat         = $("tab-chat");
const textTabContent  = $("text-tab-content");
const ocrTabContent   = $("ocr-tab-content");
const invoiceTabContent  = $("invoice-tab-content");
const chatTabContent  = $("chat-tab-content");
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
  tabChat.classList.toggle("active", tab === "chat");
  textTabContent.hidden = tab !== "text";
  ocrTabContent.hidden = tab !== "ocr";
  invoiceTabContent.hidden = tab !== "invoice";
  chatTabContent.hidden = tab !== "chat";
}

tabText.addEventListener("click", () => switchTab("text"));
tabOcr.addEventListener("click", () => switchTab("ocr"));
tabInvoice.addEventListener("click", () => switchTab("invoice"));
tabChat.addEventListener("click", () => {
  switchTab("chat");
  loadChatPanel(state.activeDocId);
});

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
      // Fetch corrections for this document
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
      await loadTemplates();
      renderInvoiceData(data, state.corrections);
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

  // Show download bar
  document.getElementById('invoice-download-bar').style.display = 'block';

  // Review banner
  let html = '';
  if (invoice.requires_review) {
    html += `<div class="manual-review-banner"><strong>&#x26A0;&#xFE0F; This invoice requires manual review</strong></div>`;
  }

  // --- Critical Fields (editable) ---
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
      const icon = issue.severity === 'error' ? '&#x274C;' : issue.severity === 'warning' ? '&#x26A0;&#xFE0F;' : '&#x2139;&#xFE0F;';
      const fieldNote = issue.field ? ` <code>${escHtml(issue.field)}</code>:` : '';
      html += `<li style="padding:4px 0;border-bottom:1px solid var(--border,#eee)">${icon}${fieldNote} ${escHtml(issue.message)}</li>`;
    }
    html += `</ul></div>`;
  }

  invoicePanel.innerHTML = html;
  invoicePanel.style.display = 'block';
}

// ─── Field editing helpers ────────────────────────────────────────────────────
async function saveCorrection(docId, fieldPath, newValue) {
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

async function toggleLock(docId, fieldPath, isLocked) {
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

async function reextractField(docId, fieldPath) {
  const resp = await fetch(`/api/extract/${docId}/reextract-field?field=${encodeURIComponent(fieldPath)}`, {
    method: 'POST',
  });
  return resp.ok ? await resp.json() : null;
}

// ─── Invoice panel event delegation (edit / lock / re-extract) ────────────────
document.getElementById('invoice-panel').addEventListener('click', async (e) => {
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

    // Replace span with input
    const input = document.createElement('input');
    input.className = 'field-edit-input';
    input.value = currentVal;
    valueSpan.replaceWith(input);
    input.focus();

    // Replace edit button with save/cancel
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
      const result = await saveCorrection(docId, fieldPath, newVal);
      if (result) {
        showToast('Correction saved', 'success', 2000);
        // Re-load panel to refresh state
        await loadInvoicePanel(docId);
      } else {
        showToast('Failed to save correction', 'error');
      }
    });

    cancelBtn.addEventListener('click', () => {
      loadInvoicePanel(docId);
    });

    return;
  }

  // Lock button
  if (e.target.closest('.lock-btn')) {
    const btn = e.target.closest('.lock-btn');
    const fieldPath = btn.dataset.field;
    const correction = state.corrections[fieldPath];
    // Can only lock/unlock if correction exists
    if (!correction) {
      showToast('Save a correction first to lock it', 'warning', 2500);
      return;
    }
    const newLocked = !correction.is_locked;
    const result = await toggleLock(docId, fieldPath, newLocked);
    if (result) {
      showToast(newLocked ? 'Field locked' : 'Field unlocked', 'info', 2000);
      await loadInvoicePanel(docId);
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
    const result = await reextractField(docId, fieldPath);
    btn.disabled = false;
    btn.textContent = origText;
    if (result) {
      showToast('Field re-extracted', 'success', 2000);
      await loadInvoicePanel(docId);
    } else {
      showToast('Re-extract failed', 'error');
    }
    return;
  }
});

// ─── Template manager ─────────────────────────────────────────────────────────
async function loadTemplates() {
  const resp = await fetch('/api/templates');
  if (resp.ok) {
    state.templates = await resp.json();
    renderTemplateManager(state.templates);
    // Update template-select dropdown
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
      <button class="field-action-btn" onclick="deleteTemplate('${escHtml(String(t.id))}')">&#x2715;</button>
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

async function createTemplate(name, fields) {
  const resp = await fetch('/api/templates', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ name, fields }),
  });
  return resp.ok;
}

async function deleteTemplate(id) {
  const resp = await fetch(`/api/templates/${id}`, { method: 'DELETE' });
  if (resp.ok) await loadTemplates();
}

// Wire up template form buttons
document.getElementById('new-template-btn').addEventListener('click', () => {
  renderTemplateFieldCheckboxes();
  document.getElementById('template-form').style.display = 'block';
});

document.getElementById('cancel-template-btn').addEventListener('click', () => {
  document.getElementById('template-form').style.display = 'none';
});

document.getElementById('save-template-btn').addEventListener('click', async () => {
  const name = document.getElementById('template-name-input').value.trim();
  if (!name) return;
  const checkboxes = document.querySelectorAll('#template-field-checkboxes input:checked');
  const fields = Array.from(checkboxes).map(cb => ({
    field_path: cb.value,
    display_name: cb.parentElement.textContent.trim(),
    include: true,
  }));
  if (await createTemplate(name, fields)) {
    document.getElementById('template-form').style.display = 'none';
    document.getElementById('template-name-input').value = '';
    await loadTemplates();
  }
});

// ─── xlsx / docx download handlers ───────────────────────────────────────────
document.getElementById('download-xlsx-btn').addEventListener('click', () => {
  if (!state.activeDocId) return;
  const tmplId = document.getElementById('template-select').value;
  const url = `/api/extract/${state.activeDocId}/export?format=xlsx${tmplId ? '&template_id=' + tmplId : ''}`;
  window.location.href = url;
});

document.getElementById('download-docx-btn').addEventListener('click', () => {
  if (!state.activeDocId) return;
  const tmplId = document.getElementById('template-select').value;
  const url = `/api/extract/${state.activeDocId}/export?format=docx${tmplId ? '&template_id=' + tmplId : ''}`;
  window.location.href = url;
});

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

// ─── Chat panel ───────────────────────────────────────────────────────────────
async function loadChatPanel(documentId) {
  currentChatDocumentId = documentId;
  const messagesDiv = $('chat-messages');
  const chatInput = $('chat-input');
  const chatSendBtn = $('chat-send-btn');
  const sessionInfo = $('chat-session-info');
  if (!messagesDiv) return;

  if (!documentId) {
    messagesDiv.innerHTML = '<p class="chat-empty">Select a document to start chatting.</p>';
    if (chatInput) chatInput.disabled = true;
    if (chatSendBtn) chatSendBtn.disabled = true;
    if (sessionInfo) sessionInfo.textContent = 'Select a document to start chatting.';
    return;
  }

  messagesDiv.innerHTML = '<p class="chat-empty">Loading…</p>';
  if (chatInput) chatInput.disabled = true;
  if (chatSendBtn) chatSendBtn.disabled = true;

  try {
    const sessions = await apiJson(`/chat/sessions?document_id=${documentId}`);

    if (sessions.length > 0) {
      currentChatSessionId = sessions[0].id;
      if (sessionInfo) sessionInfo.textContent = `Session ${currentChatSessionId}`;
      await loadChatMessages(currentChatSessionId);
    } else {
      const session = await apiJson('/chat/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ document_id: documentId, mode: 'single' }),
      });
      currentChatSessionId = session.id;
      if (sessionInfo) sessionInfo.textContent = `Session ${currentChatSessionId}`;
      // Trigger indexing in background (fire and forget — don't block chat)
      fetch(`/api/chat/index/${documentId}`, { method: 'POST' })
          .catch(err => console.warn('RAG indexing failed:', err));
      messagesDiv.innerHTML = '';
    }

    if (chatInput) chatInput.disabled = false;
    if (chatSendBtn) chatSendBtn.disabled = false;
  } catch (err) {
    messagesDiv.innerHTML = `<p class="chat-error">Error: ${escHtml(String(err))}</p>`;
  }
}

async function loadChatMessages(sessionId) {
  const messages = await apiJson(`/chat/sessions/${sessionId}/messages`);
  const messagesDiv = $('chat-messages');
  messagesDiv.innerHTML = '';
  messages.forEach(msg => appendChatMessage(msg));
  messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function appendChatMessage(msg) {
  const messagesDiv = $('chat-messages');
  const div = document.createElement('div');
  div.className = `chat-message ${escHtml(msg.role)}`;
  div.innerHTML = `<span class="chat-role">${escHtml(msg.role)}</span>${escHtml(msg.content)}`;

  if (msg.citations && msg.citations.length > 0) {
    const citDiv = document.createElement('div');
    citDiv.className = 'chat-citations';
    citDiv.innerHTML = '<strong>Sources:</strong>';
    msg.citations.forEach((c, i) => {
      const text = c.text || '';
      const snippet = text.slice(0, 100) + (text.length > 100 ? '\u2026' : '');
      const entry = document.createElement('div');
      entry.className = 'chat-citation';
      entry.textContent = `[${i + 1}] ${snippet}`;
      citDiv.appendChild(entry);
    });
    div.appendChild(citDiv);
  }

  messagesDiv.appendChild(div);
}

async function sendChatMessage() {
  const input = $('chat-input');
  if (!input || !currentChatSessionId) return;
  const question = input.value.trim();
  if (!question) return;
  input.value = '';
  input.disabled = true;
  const sendBtn = $('chat-send-btn');
  if (sendBtn) sendBtn.disabled = true;

  appendChatMessage({ role: 'user', content: question, citations: null });

  try {
    const assistantMsg = await apiJson(`/chat/sessions/${currentChatSessionId}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
    });
    appendChatMessage(assistantMsg);
    const messagesDiv = $('chat-messages');
    if (messagesDiv) messagesDiv.scrollTop = messagesDiv.scrollHeight;
  } catch (err) {
    appendChatMessage({ role: 'assistant', content: `Error: ${err.message || err}`, citations: null });
  } finally {
    input.disabled = false;
    if (sendBtn) sendBtn.disabled = false;
    input.focus();
  }
}

async function downloadIvaSummary() {
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

// Wire up chat input events (module scripts run after DOM is ready)
$('chat-send-btn').addEventListener('click', sendChatMessage);

$('chat-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendChatMessage();
  }
});

$('iva-summary-download-btn').addEventListener('click', downloadIvaSummary);

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
