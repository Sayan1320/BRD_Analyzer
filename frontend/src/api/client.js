const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

/**
 * Send a multipart POST to /analyze with the given File object.
 * Returns the parsed AnalysisResult JSON.
 * Throws an Error with { status, message } on HTTP errors.
 */
export async function analyzeDocument(file) {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`${API_BASE}/analyze`, { method: 'POST', body: form });
  if (!res.ok) throw await _httpError(res);
  return res.json();
}

/**
 * Construct a Blob from the text string and POST to /analyze.
 * Equivalent to analyzeDocument() but for plain-text content.
 */
export async function analyzeText(text, filename) {
  const form = new FormData();
  form.append('file', new Blob([text], { type: 'text/plain' }), filename);
  const res = await fetch(`${API_BASE}/analyze`, { method: 'POST', body: form });
  if (!res.ok) throw await _httpError(res);
  return res.json();
}

/**
 * GET /demo/sample-text — returns { text, filename, file_type }.
 */
export async function fetchSampleText() {
  const res = await fetch(`${API_BASE}/demo/sample-text`);
  if (!res.ok) throw await _httpError(res);
  return res.json();
}

/**
 * POST to /voice-summary with the full analysisResult as JSON body.
 * Returns the parsed AudioResponse JSON.
 */
export async function fetchVoiceSummary(analysisResult) {
  const res = await fetch(`${API_BASE}/voice-summary`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(analysisResult),
  });
  if (!res.ok) throw await _httpError(res);
  return res.json();
}

/**
 * POST to /voice-story with the userStory and voiceName.
 * Returns the parsed AudioResponse JSON.
 */
export async function fetchVoiceStory(userStory, voiceName) {
  const res = await fetch(`${API_BASE}/voice-story`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...userStory, voice: voiceName }),
  });
  if (!res.ok) throw await _httpError(res);
  return res.json();
}

/**
 * POST /demo/analyze — returns the pre-computed demo result instantly.
 * Used when Ctrl+Shift+D demo mode is active.
 */
export async function analyzeDemoMode() {
  const res = await fetch(`${API_BASE}/demo/analyze`, { method: 'POST' });
  if (!res.ok) throw await _httpError(res);
  return res.json();
}

async function _httpError(res) {
  let message = res.statusText;
  let data = null;
  try { data = await res.json(); message = data.detail ?? message; } catch (_) {}
  const err = new Error(message);
  err.status = res.status;
  if (res.status === 429) {
    err.retry_after_seconds = data?.retry_after_seconds ?? 60;
  }
  return err;
}
