// frontend/src/main.js
import { updateThemeButton } from './ui.js';

// ── Global state ───────────────────────────────────────────────
export const state = {
  view: 'viewer',          // 'viewer' | 'library'
  activeDocId: null,
  pdfDoc: null,
  currentPage: 1,
  totalPages: 0,
  scale: 1.5,
  pollingTimers: {},
  corrections: {},
  templates: [],
  // Library state
  libraryFilters: {},
  librarySelection: new Set(),
  libraryPage: 1,
  // Viewer runtime state
  rendering: false,
  activeTab: 'text',
  extractionPolling: null,
};

// ── View routing ───────────────────────────────────────────────
export function setView(view) {
  state.view = view;
  document.getElementById('viewer-container').style.display =
    view === 'viewer' ? '' : 'none';
  document.getElementById('library-container').style.display =
    view === 'library' ? '' : 'none';
  document.querySelector('.nav-btn--library')?.classList.toggle('active', view === 'library');
  // Show/hide the back-to-viewer button
  const backBtn = document.querySelector('.nav-btn--viewer');
  if (backBtn) backBtn.style.display = view === 'library' ? '' : 'none';
}

// ── Nav bar ─────────────────────────────────────────────────────
function initNav() {
  // Theme toggle
  const themeBtn = document.getElementById('theme-toggle');
  if (themeBtn) {
    themeBtn.addEventListener('click', () => {
      import('./ui.js').then(({ toggleTheme }) => toggleTheme());
    });
  }
  updateThemeButton();

  // Library button
  const libBtn = document.querySelector('.nav-btn--library');
  if (libBtn) {
    libBtn.addEventListener('click', () => {
      import('./library.js').then(({ initLibrary }) => {
        setView('library');
        initLibrary();
      });
    });
  }

  // Back to viewer button
  const backBtn = document.querySelector('.nav-btn--viewer');
  if (backBtn) {
    backBtn.addEventListener('click', () => setView('viewer'));
  }
}

// ── Boot ───────────────────────────────────────────────────────
async function boot() {
  initNav();

  // Lazy-load the viewer module (handles the existing 3-panel logic)
  const { initViewer } = await import('./viewer.js');
  initViewer(state);
}

document.addEventListener('DOMContentLoaded', boot);
