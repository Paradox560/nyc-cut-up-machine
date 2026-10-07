import { api, explainError } from './api.js';

// Vocabulary Explorer: shows Elasticsearch hybrid search (BM25 + Mistral vectors, RRF) on its own.
const input = document.getElementById('words-input');
const status = document.getElementById('words-status');
const list = document.getElementById('words-results');
let timer = null;
let controller = null;

function render(data) {
  list.replaceChildren();
  for (const hit of data.results) {
    const li = document.createElement('li');
    const title = document.createElement('strong');
    title.textContent = hit.title || hit.source_id;
    const words = document.createElement('span');
    words.textContent = hit.words.join(' · ');
    li.append(title, words);
    list.append(li);
  }
  status.textContent = data.results.length
    ? `Photographs ranked by meaning and by words${data.mode === 'demo' ? ' (sample vocabulary)' : ''}.`
    : 'No reviewed photographs match. Try another feeling.';
}

async function search() {
  const query = input.value.trim();
  controller?.abort();
  if (query.length < 2) { list.replaceChildren(); status.textContent = ''; return; }
  controller = new AbortController();
  status.textContent = 'Searching…';
  try {
    render(await api.words(query, controller.signal));
  } catch (error) {
    if (error.name !== 'AbortError') status.textContent = explainError(error);
  }
}

input?.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(search, 300); });
