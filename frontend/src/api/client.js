const BASE = '';

async function request(url, options = {}) {
  const res = await fetch(`${BASE}${url}`, options);
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const message = body?.detail || body?.error || `Request failed with status ${res.status}`;
    throw new Error(message);
  }
  if (res.status === 204) return null;
  return res.json();
}

export async function listDocuments() {
  return request('/documents');
}

export async function getDocument(id) {
  return request(`/documents/${id}`);
}

export async function createDocument(title, file) {
  const form = new FormData();
  form.append('title', title);
  form.append('file', file);
  return request('/documents', { method: 'POST', body: form });
}

export async function getChunks(documentId, page = 1, pageSize = 20) {
  return request(`/documents/${documentId}/chunks?page=${page}&page_size=${pageSize}`);
}

export async function applyChanges(documentId, version, changes) {
  return request(`/documents/${documentId}/changes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ version, changes }),
  });
}

export async function getChangeHistory(documentId) {
  return request(`/documents/${documentId}/changes`);
}

export async function acceptChange(documentId, changeId) {
  return request(`/documents/${documentId}/changes/${changeId}/accept`, { method: 'PATCH' });
}

export async function rejectChange(documentId, changeId) {
  return request(`/documents/${documentId}/changes/${changeId}/reject`, { method: 'PATCH' });
}

export async function search(query, documentId = null) {
  let url = `/documents/search?q=${encodeURIComponent(query)}`;
  if (documentId) url += `&document_id=${documentId}`;
  return request(url);
}

export async function getOccurrences(documentId, term) {
  return request(`/documents/${documentId}/occurrences?q=${encodeURIComponent(term)}`);
}

export async function suggestReplacement(documentId, chunkId, selectedText, instruction = undefined) {
  const body = { chunk_id: chunkId, selected_text: selectedText };
  if (instruction) body.instruction = instruction;
  return request(`/documents/${documentId}/suggest`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}
