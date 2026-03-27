// frontend/src/tabs/ocr.js
// OCR tab — start OCR button, OCR settings (language, DPI), OCR result display.

import * as api from "../api.js";
import { showToast } from "../ui.js";

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function isDocPdf(doc) {
  const fmt = (doc.format ?? "").toLowerCase();
  const name = (doc.filename ?? "").toLowerCase();
  return fmt === "pdf" || name.endsWith(".pdf");
}

function confidenceBadge(score) {
  let cls = "confidence-low";
  if (score >= 80) cls = "confidence-high";
  else if (score >= 70) cls = "confidence-medium";
  return `<span class="confidence-badge ${cls}">${Math.round(score)}%</span>`;
}

export function initOcrTab(state) {
  const $ = (id) => document.getElementById(id);

  const runOcrBtn       = $("run-ocr-btn");

  runOcrBtn.addEventListener("click", () => {
    if (state.activeDocId) runOCR(state.activeDocId, state);
  });
}

export async function refreshOCRPanel(doc, state) {
  const $ = (id) => document.getElementById(id);

  const ocrEmpty        = $("ocr-empty");
  const ocrProcessing   = $("ocr-processing");
  const ocrResults      = $("ocr-results");
  const runOcrBtn       = $("run-ocr-btn");

  ocrEmpty.hidden = false;
  ocrProcessing.hidden = true;
  ocrResults.hidden = true;
  runOcrBtn.hidden = true;

  const isImage = !isDocPdf(doc);

  if (doc.is_scanned || isImage) {
    runOcrBtn.hidden = false;
  }

  if (doc.ocr_confidence != null) {
    await loadOCRResults(doc.id);
  }
}

async function runOCR(docId, state) {
  const $ = (id) => document.getElementById(id);

  const ocrEmpty        = $("ocr-empty");
  const ocrProcessing   = $("ocr-processing");
  const ocrResults      = $("ocr-results");
  const ocrProgressWrap = $("ocr-progress-wrapper");
  const ocrProgressLabel = $("ocr-progress-label");

  try {
    ocrEmpty.hidden = true;
    ocrProcessing.hidden = false;
    ocrResults.hidden = true;
    ocrProgressWrap.hidden = true;
    ocrProgressLabel.textContent = "Starting…";

    await api.startOcr(docId, { lang: "spa+eng", preprocess: true });

    showToast("OCR started", "info");
    startOCRPolling(docId, state);
  } catch (err) {
    ocrProcessing.hidden = true;
    ocrEmpty.hidden = false;
    showToast(`OCR failed: ${err.message}`, "error");
  }
}

function startOCRPolling(docId, state) {
  const key = `ocr_${docId}`;
  if (state.pollingTimers[key]) return;

  const timer = setInterval(async () => {
    const $ = (id) => document.getElementById(id);
    try {
      const data = await api.getJobsForDocument(docId);
      const jobs = data.jobs ?? [];
      const ocrJob = jobs.find(j => j.job_type === "ocr" && (j.status === "running" || j.status === "pending"));
      const completedOcr = jobs.find(j => j.job_type === "ocr" && j.status === "completed");
      const failedOcr = jobs.find(j => j.job_type === "ocr" && j.status === "failed");

      if (ocrJob && docId === state.activeDocId) {
        const ocrProgressWrap = $("ocr-progress-wrapper");
        const ocrProgressBar = $("ocr-progress-bar");
        const ocrProgressLabel = $("ocr-progress-label");
        if (ocrProgressWrap) ocrProgressWrap.hidden = false;
        const pct = Math.round((ocrJob.progress ?? 0) * 100);
        if (ocrProgressBar) ocrProgressBar.style.width = `${pct}%`;
        if (ocrProgressLabel) ocrProgressLabel.textContent = `${pct}%`;
      }

      if (completedOcr || failedOcr) {
        stopOCRPolling(docId, state);

        if (docId === state.activeDocId) {
          if (completedOcr) {
            await loadOCRResults(docId);
            showToast("OCR complete!", "success");
          } else {
            const ocrProcessing = $("ocr-processing");
            const ocrEmpty = $("ocr-empty");
            if (ocrProcessing) ocrProcessing.hidden = true;
            if (ocrEmpty) ocrEmpty.hidden = false;
            showToast(`OCR failed: ${failedOcr.error ?? "Unknown error"}`, "error");
          }
        }
      }
    } catch {
      // keep polling
    }
  }, 2000);

  state.pollingTimers[key] = timer;
}

function stopOCRPolling(docId, state) {
  const key = `ocr_${docId}`;
  const timer = state.pollingTimers[key];
  if (timer !== undefined) {
    clearInterval(timer);
    delete state.pollingTimers[key];
  }
}

async function loadOCRResults(docId) {
  const $ = (id) => document.getElementById(id);

  try {
    const data = await api.getOcrResult(docId);
    const ocrProcessing = $("ocr-processing");
    const ocrEmpty = $("ocr-empty");
    const ocrResults = $("ocr-results");
    const ocrSummary = $("ocr-summary");
    const ocrPages = $("ocr-pages");

    if (ocrProcessing) ocrProcessing.hidden = true;
    if (ocrEmpty) ocrEmpty.hidden = true;
    if (ocrResults) ocrResults.hidden = false;

    if (ocrSummary) {
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
    }

    if (ocrPages) {
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
    }
  } catch (err) {
    const ocrProcessing = document.getElementById("ocr-processing");
    const ocrEmpty = document.getElementById("ocr-empty");
    if (ocrProcessing) ocrProcessing.hidden = true;
    if (ocrEmpty) ocrEmpty.hidden = false;
  }
}
