// frontend/src/api.js
// All API calls in one place. Import this module wherever you need to talk to the backend.

const BASE = '/api';

export async function apiFetch(path, options = {}) {
  const resp = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw Object.assign(new Error(err.detail || 'Request failed'), { status: resp.status });
  }
  return resp;
}

export async function apiJson(path, options = {}) {
  const resp = await apiFetch(path, options);
  return resp.json();
}

// Documents
export const listDocuments = (params = {}) =>
  apiJson('/documents/?' + new URLSearchParams(params));
export const getDocument = (id) => apiJson(`/documents/${id}`);
export const deleteDocument = (id) => apiFetch(`/documents/${id}`, { method: 'DELETE' });
export const getDocumentText = (id) => apiJson(`/documents/${id}/text`);

// Jobs
export const getJob = (id) => apiJson(`/jobs/${id}`);
export const getJobsForDocument = (docId) => apiJson(`/jobs/document/${docId}`);
export const cancelJob = (id) => apiJson(`/jobs/${id}/cancel`, { method: 'POST' });

// OCR
export const startOcr = (docId, body) =>
  apiJson(`/ocr/${docId}`, { method: 'POST', body: JSON.stringify(body) });
export const getOcrResult = (docId) => apiJson(`/ocr/${docId}/result`);

// Extraction
export const startExtraction = (docId) =>
  apiJson(`/extract/${docId}`, { method: 'POST' });
export const exportExtraction = (docId, params) =>
  apiFetch(`/extract/${docId}/export?` + new URLSearchParams(params));
export const reextractField = (docId, field) =>
  apiJson(`/extract/${docId}/reextract-field?field=${encodeURIComponent(field)}`, { method: 'POST' });

// Batch
export const batchExport = (body) =>
  apiFetch('/batch/export', { method: 'POST', body: JSON.stringify(body) });

// Chat
export const createChatSession = (body) =>
  apiJson('/chat/sessions', { method: 'POST', body: JSON.stringify(body) });
export const listChatSessions = (docId) =>
  apiJson(`/chat/sessions?document_id=${docId}`);
export const getChatSession = (id) => apiJson(`/chat/sessions/${id}`);
export const sendMessage = (sessionId, body) =>
  apiJson(`/chat/sessions/${sessionId}/messages`, { method: 'POST', body: JSON.stringify(body) });
export const deleteChatSession = (id) =>
  apiFetch(`/chat/sessions/${id}`, { method: 'DELETE' });

// Corrections  (all routes use document_id, matching backend /api/corrections/{document_id})
export const getCorrections = (docId) =>
  apiJson(`/corrections/${docId}`);
export const saveCorrection = (docId, body) =>
  apiJson(`/corrections/${docId}`,
           { method: 'POST', body: JSON.stringify(body) });
export const lockCorrection = (docId, body) =>
  apiJson(`/corrections/${docId}/lock`,
           { method: 'POST', body: JSON.stringify(body) });

// Templates
export const listTemplates = () => apiJson('/templates/');
export const createTemplate = (body) =>
  apiJson('/templates/', { method: 'POST', body: JSON.stringify(body) });
export const updateTemplate = (id, body) =>
  apiJson(`/templates/${id}`, { method: 'PUT', body: JSON.stringify(body) });
export const deleteTemplate = (id) =>
  apiFetch(`/templates/${id}`, { method: 'DELETE' });
