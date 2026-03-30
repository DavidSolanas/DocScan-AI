// frontend/src/tabs/chat.js
// Chat tab — session management, message sending, response display.

import * as api from "../api.js";
import { showToast, escHtml } from "../ui.js";

// Module-level chat state
let currentChatSessionId = null;
let currentChatDocumentId = null;

export function initChatTab(state) {
  const $ = (id) => document.getElementById(id);

  $('chat-send-btn').addEventListener('click', () => sendChatMessage(state));

  $('chat-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendChatMessage(state);
    }
  });
}

export async function loadChatPanel(documentId, state) {
  const $ = (id) => document.getElementById(id);

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
    const sessions = await api.listChatSessions(documentId);

    if (sessions.length > 0) {
      currentChatSessionId = sessions[0].id;
      if (sessionInfo) sessionInfo.textContent = `Session ${currentChatSessionId}`;
      await loadChatMessages(currentChatSessionId);
    } else {
      const session = await api.createChatSession({ document_id: documentId, mode: 'single' });
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
  const $ = (id) => document.getElementById(id);
  const messages = await api.apiJson(`/chat/sessions/${sessionId}/messages`);
  const messagesDiv = $('chat-messages');
  messagesDiv.innerHTML = '';
  messages.forEach(msg => appendChatMessage(msg));
  messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function appendChatMessage(msg) {
  const messagesDiv = document.getElementById('chat-messages');
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

async function sendChatMessage(state) {
  const $ = (id) => document.getElementById(id);
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
    const assistantMsg = await api.sendMessage(currentChatSessionId, { question });
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
