// frontend/src/viewer.js
// PDF.js rendering, page navigation, zoom, document list sidebar, document upload, document selection.

import * as pdfjsLib from "../lib/pdf.mjs";
import * as api from "./api.js";
import { showToast, escHtml } from "./ui.js";

// ── PDF.js worker ─────────────────────────────────────────────────────────────
pdfjsLib.GlobalWorkerOptions.workerSrc = "../lib/pdf.worker.mjs";

// ── Exported mutable binding (library.js can call this) ───────────────────────
export let selectDocument = null; // reassigned inside initViewer

// ── Utility functions ─────────────────────────────────────────────────────────
function formatBytes(bytes) {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0)} ${units[i]}`;
}

function isDocPdf(doc) {
  const fmt = (doc.format ?? "").toLowerCase();
  const name = (doc.filename ?? "").toLowerCase();
  return fmt === "pdf" || name.endsWith(".pdf");
}

// ── Main init ─────────────────────────────────────────────────────────────────
export async function initViewer(state) {
  // ── DOM refs ─────────────────────────────────────────────────────────────────
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

  // ── Load sub-modules ─────────────────────────────────────────────────────────
  const [{ initOcrTab }, { initInvoiceTab }, { initChatTab }, { initJobs }] = await Promise.all([
    import("./tabs/ocr.js"),
    import("./tabs/invoice.js"),
    import("./tabs/chat.js"),
    import("./jobs.js"),
  ]);

  initOcrTab(state);
  initInvoiceTab(state);
  initChatTab(state);
  initJobs(state);

  // ── Document list ─────────────────────────────────────────────────────────────
  async function loadDocumentList() {
    try {
      const data = await api.listDocuments({ skip: 0, limit: 50 });
      const docs = data.documents ?? [];
      renderDocumentList(docs);
      loadReviewQueue(docs);
    } catch (err) {
      showToast(`Failed to load documents: ${err.message}`, "error");
    }
  }

  function renderDocumentList(docs) {
    Array.from(docList.querySelectorAll(".doc-item")).forEach((el) => el.remove());

    const count = docs.length;
    docCount.textContent = `${count} document${count !== 1 ? "s" : ""}`;
    docListEmpty.hidden = count > 0;

    docs.forEach((doc) => {
      docList.appendChild(buildDocItem(doc));
    });
  }

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

  // ── Select / open document ────────────────────────────────────────────────────
  selectDocument = async function(docId) {
    state.activeDocId = docId;

    docList.querySelectorAll(".doc-item").forEach((el) => {
      el.classList.toggle("active", parseInt(el.dataset.id) === docId);
    });

    try {
      const doc = await api.getDocument(docId);
      viewerFilename.textContent = doc.filename;
      viewerToolbar.hidden = false;

      await renderDocumentPreview(doc);
      await refreshTextPanel(doc);

      // Notify OCR and Invoice tabs
      const { refreshOCRPanel } = await import("./tabs/ocr.js");
      const { loadInvoicePanel } = await import("./tabs/invoice.js");
      await refreshOCRPanel(doc, state);
      await loadInvoicePanel(docId, state);
    } catch (err) {
      showToast(`Failed to open document: ${err.message}`, "error");
    }
  };

  // ── Document preview ──────────────────────────────────────────────────────────
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

  // ── Pagination & Zoom ──────────────────────────────────────────────────────────
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

  // ── Text panel ─────────────────────────────────────────────────────────────────
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
      const data = await api.getDocumentText(doc.id);
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

  // ── Job polling ────────────────────────────────────────────────────────────────
  function startPolling(docId) {
    if (state.pollingTimers[docId]) return; // already polling

    const timer = setInterval(async () => {
      try {
        const data = await api.getJobsForDocument(docId);
        const jobs = data.jobs ?? [];
        const latest = jobs[jobs.length - 1];

        if (!latest) return;

        const progress = latest.progress ?? 0;
        const jobStatus = latest.status ?? "pending";

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
            const doc = await api.getDocument(docId);
            await refreshTextPanel(doc);
          }

          if (jobStatus === "completed") {
            showToast("Processing complete!", "success");
          } else {
            const errMsg = latest.error ?? "Unknown error";
            showToast(`Processing failed: ${errMsg}`, "error");
          }

          await loadDocumentList();
        }
      } catch (err) {
        // Non-fatal: keep polling
      }
    }, 2000);

    state.pollingTimers[docId] = timer;
  }

  function stopPolling(docId) {
    const timer = state.pollingTimers[docId];
    if (timer !== undefined) {
      clearInterval(timer);
      delete state.pollingTimers[docId];
    }
  }

  // ── Tab switching ──────────────────────────────────────────────────────────────
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
  tabChat.addEventListener("click", async () => {
    switchTab("chat");
    const { loadChatPanel } = await import("./tabs/chat.js");
    loadChatPanel(state.activeDocId, state);
  });

  // ── Copy text ──────────────────────────────────────────────────────────────────
  copyTextBtn.addEventListener("click", async () => {
    const text = textContent.textContent;
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      showToast("Text copied to clipboard", "success");
    } catch {
      showToast("Copy failed – try selecting the text manually", "warning");
    }
  });

  // ── Delete document ────────────────────────────────────────────────────────────
  async function deleteDocument(docId, listItem) {
    try {
      await api.deleteDocument(docId);

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
        const ocrEmpty = $("ocr-empty");
        const ocrProcessing = $("ocr-processing");
        const ocrResults = $("ocr-results");
        const runOcrBtn = $("run-ocr-btn");
        if (ocrEmpty) ocrEmpty.hidden = false;
        if (ocrProcessing) ocrProcessing.hidden = true;
        if (ocrResults) ocrResults.hidden = true;
        if (runOcrBtn) runOcrBtn.hidden = true;
        // Reset Invoice panel
        const invoiceDownloadBar = $('invoice-download-bar');
        const extractionNotStarted = $('extraction-not-started');
        const invoiceEmptyEl = $('invoice-empty');
        const invoiceProcessing = $('invoice-processing');
        const invoicePanel = $('invoice-panel');
        if (invoiceDownloadBar) invoiceDownloadBar.style.display = 'none';
        if (extractionNotStarted) extractionNotStarted.style.display = 'none';
        if (invoiceEmptyEl) invoiceEmptyEl.style.display = 'none';
        if (invoiceProcessing) invoiceProcessing.style.display = 'none';
        if (invoicePanel) { invoicePanel.style.display = 'none'; invoicePanel.innerHTML = ''; }
        if (state.extractionPolling) {
          clearInterval(state.extractionPolling);
          state.extractionPolling = null;
        }
        switchTab("text");
      }

      const remaining = docList.querySelectorAll(".doc-item").length;
      docCount.textContent = `${remaining} document${remaining !== 1 ? "s" : ""}`;
      docListEmpty.hidden = remaining > 0;

      showToast("Document deleted", "info");
    } catch (err) {
      showToast(`Delete failed: ${err.message}`, "error");
    }
  }

  // ── Upload ─────────────────────────────────────────────────────────────────────
  function triggerUpload() { fileInput.click(); }

  uploadBtn.addEventListener("click", (e) => { e.stopPropagation(); triggerUpload(); });
  uploadArea.addEventListener("click", triggerUpload);

  fileInput.addEventListener("change", () => {
    const files = Array.from(fileInput.files ?? []);
    fileInput.value = "";
    files.forEach(uploadFile);
  });

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

    showToast(`Uploading ${file.name}…`, "info");

    try {
      const res = await fetch("/api/documents/upload", {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || "Upload failed");
      }
      const doc = await res.json();

      showToast(`${file.name} uploaded`, "success");

      docListEmpty.hidden = true;
      const li = buildDocItem(doc);
      docList.insertBefore(li, docList.firstChild);
      const count = docList.querySelectorAll(".doc-item").length;
      docCount.textContent = `${count} document${count !== 1 ? "s" : ""}`;

      startPolling(doc.id);

      if (state.activeDocId === null) {
        selectDocument(doc.id);
      }
    } catch (err) {
      showToast(`Upload failed: ${err.message}`, "error");
    }
  }

  // ── Refresh button ─────────────────────────────────────────────────────────────
  refreshBtn.addEventListener("click", loadDocumentList);

  // ── Review queue ───────────────────────────────────────────────────────────────
  async function loadReviewQueue(docs) {
    const needsReview = [];
    for (const doc of docs.slice(0, 50)) {
      try {
        const data = await api.apiJson(`/extract/${doc.id}`);
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

  // ── Initial load ───────────────────────────────────────────────────────────────
  loadDocumentList();
}
