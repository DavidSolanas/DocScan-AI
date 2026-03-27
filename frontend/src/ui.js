// frontend/src/ui.js
// Shared UI utilities: toasts, spinners, theme toggle.

// ── Toast ──────────────────────────────────────────────────────
export function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container')
    || (() => {
      const el = document.createElement('div');
      el.id = 'toast-container';
      el.style.cssText = 'position:fixed;bottom:20px;right:20px;z-index:9999;display:flex;flex-direction:column;gap:8px';
      document.body.appendChild(el);
      return el;
    })();

  const toast = document.createElement('div');
  toast.className = `toast toast--${type}`;
  toast.textContent = message;
  toast.style.cssText = `
    background: var(--bg-raised); color: var(--text-primary);
    border: 1px solid var(--border); border-radius: var(--radius);
    padding: 10px 16px; font-size: 13px; max-width: 320px;
    box-shadow: var(--shadow); opacity: 0; transition: opacity 0.2s;
    border-left: 3px solid ${type === 'error' ? 'var(--status-failed)' : type === 'success' ? 'var(--status-valid)' : 'var(--accent)'};
  `;
  container.appendChild(toast);
  requestAnimationFrame(() => { toast.style.opacity = '1'; });
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 200);
  }, 3500);
}

// ── Theme toggle ───────────────────────────────────────────────
export function toggleTheme() {
  const html = document.documentElement;
  const current = html.getAttribute('data-theme');
  const next = current === 'light' ? 'dark' : 'light';
  if (next === 'dark') {
    html.removeAttribute('data-theme');
    localStorage.removeItem('theme');
  } else {
    html.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
  }
  updateThemeButton();
}

export function updateThemeButton() {
  const btn = document.getElementById('theme-toggle');
  if (!btn) return;
  const isLight = document.documentElement.getAttribute('data-theme') === 'light';
  btn.textContent = isLight ? '🌙' : '☀️';
  btn.title = isLight ? 'Switch to dark mode' : 'Switch to light mode';
}

// ── Spinner ────────────────────────────────────────────────────
export function setLoading(element, loading) {
  if (loading) {
    element.dataset.originalText = element.textContent;
    element.textContent = '…';
    element.disabled = true;
  } else {
    element.textContent = element.dataset.originalText || element.textContent;
    element.disabled = false;
  }
}

// ── Confirm dialog ─────────────────────────────────────────────
export function confirm(message) {
  return window.confirm(message);
}
