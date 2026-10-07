/** A small same-origin client. Never send service credentials to the browser. */
export class ApiError extends Error {
  constructor(message, code = 'REQUEST_FAILED') {
    super(message);
    this.name = 'ApiError';
    this.code = code;
  }
}

async function request(path, { method = 'GET', body, signal, audio = false } = {}) {
  const response = await fetch(path, {
    method,
    signal,
    credentials: 'same-origin',
    headers: { Accept: audio ? 'audio/mpeg, application/json' : 'application/json', ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const isJSON = response.headers.get('content-type')?.includes('application/json');
  if (!response.ok || isJSON && audio) {
    const payload = isJSON ? await response.json() : {};
    throw new ApiError(typeof payload.error === 'string' ? payload.error : `The workshop returned an error (${response.status}). Please try again.`, payload.code);
  }
  if (audio) return response.blob();
  if (!isJSON) throw new ApiError('The workshop did not return a readable response. Check that the local server is running.', 'INVALID_RESPONSE');
  return response.json();
}

export const api = {
  status: (signal) => request('/api/status', { signal }),
  sources: (signal) => request('/api/sources', { signal }),
  words: (query, signal) => request('/api/words?q=' + encodeURIComponent(query), { signal }),
  compose: (body, signal) => request('/api/compose', { method: 'POST', body, signal }),
  review: (body, signal) => request('/api/sources/review', { method: 'POST', body, signal }),
  speech: (compositionId, signal) => request('/api/speech', { method: 'POST', body: { composition_id: compositionId }, signal, audio: true }),
};

export function timeoutSignal(milliseconds = 90000) {
  return AbortSignal.timeout(milliseconds);
}

export function explainError(error) {
  if (error.name === 'TimeoutError') return 'This took longer than expected. Please try again with a shorter brief.';
  if (error.name === 'AbortError') return 'Composition canceled. Your last print is still here.';
  if (error instanceof TypeError) return 'The workshop could not be reached. Check that the local server is running and try again.';
  return error.message || 'Something went wrong. Please try again.';
}
