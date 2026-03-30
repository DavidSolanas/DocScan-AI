// frontend/src/jobs.js
// Job status polling, progress bar, cancel button wiring.

import * as api from "./api.js";
import { showToast } from "./ui.js";

export function initJobs(state) {
  // Delegated click handler for cancel buttons on job list items
  document.addEventListener('click', async (e) => {
    if (!e.target.matches('[data-cancel-job]')) return;
    const jobId = e.target.dataset.cancelJob;
    try {
      await api.cancelJob(jobId);
      showToast('Cancellation requested', 'info');
      e.target.textContent = 'Cancelling…';
      e.target.disabled = true;
    } catch (err) {
      showToast(err.message, 'error');
    }
  });
}

/**
 * Render a job list item with a cancel button.
 * @param {object} job
 * @returns {string} HTML string
 */
export function renderJobItem(job) {
  const statusClass = `status-${job.status}`;
  return `
    <div class="job-item" data-job-id="${job.id}">
      <span class="job-type">${job.job_type ?? 'job'}</span>
      <span class="status-badge ${statusClass}">${job.status}</span>
      <span class="job-progress">${job.progress != null ? Math.round(job.progress) + '%' : ''}</span>
      <button data-cancel-job="${job.id}" class="job-cancel-btn"
              ${['pending','running'].includes(job.status) ? '' : 'style="display:none"'}>
        Cancel
      </button>
    </div>
  `;
}
