import { api, explainError, timeoutSignal } from './api.js';
import { downloadPoster, plainText } from './export.js';
import { element, renderComposition, renderSourceDialog, renderSourceGrid } from './render.js';
import { liveCropSources, loadOriginals } from './crops.js';

const $ = (id) => document.getElementById(id);
const state = { status: null, sources: [], composition: null, originals: new Map(), controller: null, exportController: null, speechController: null, audioURL: null, toastTimer: null, formKind: $('form-kind').value, generatedDraft: $('prompt').value, customDraft: '' };

function toast(message) {
  clearTimeout(state.toastTimer);
  $('toast').textContent = message;
  $('toast').hidden = false;
  state.toastTimer = setTimeout(() => { $('toast').hidden = true; }, 4000);
}

function showError(message) {
  $('global-error').textContent = message;
  $('global-error').hidden = !message;
}

function setStatus(status) {
  state.status = status;
  const live = status.mode === 'live';
  $('service-status').dataset.mode = status.mode;
  $('status-text').textContent = live ? 'Live workshop' : 'Sample workshop';
  $('service-status').title = `Mistral: ${status.configured.mistral ? 'configured' : 'not configured'}; Elasticsearch: ${status.configured.elasticsearch ? 'configured' : 'not configured'}. ${status.reviewed_count} reviewed sources. Configuration does not guarantee service connectivity.`;
  $('mode-notice').hidden = live;
  $('source-count').textContent = `${status.corpus_count ?? state.sources.length} ${live ? 'photos' : 'samples'}`;
  $('speech-button').hidden = !status.voice_enabled;
  renderInventory();
}

function renderInventory() {
  const inventory = state.status?.inventory;
  const visible = Boolean(inventory && state.status.mode === 'live');
  for (const id of ['press-inventory', 'library-inventory', 'inventory-coverage']) $(id).hidden = !visible;
  if (!visible) return;
  const render = (id, fields) => {
    const container = $(id);
    container.replaceChildren();
    for (const [key, label] of fields) {
      const entry = element('div', 'inventory-item');
      const count = Number.isFinite(inventory[key]) ? inventory[key].toLocaleString() : '—';
      entry.append(element('strong', '', count), element('span', '', label));
      container.append(entry);
    }
  };
  render('press-inventory', [['reviewed_images', 'reviewed photographs'], ['word_crops', 'word cuts'], ['letter_crops', 'letter cuts']]);
  render('library-inventory', [['downloaded_images', 'downloaded photographs'], ['processed_images', 'processed photographs'], ['reviewed_images', 'reviewed photographs'], ['word_crops', 'word cuts'], ['letter_crops', 'letter cuts']]);
  const missing = Array.isArray(inventory.missing_letters) ? inventory.missing_letters.join(' ') : String(inventory.missing_letters || '');
  $('inventory-coverage').textContent = missing ? `Letters still missing from the drawer: ${missing}. A custom message must use letters already photographed.` : 'The photographed letter drawer covers the alphabet. Punctuation also needs its own photographed cut.';
}

function syncFormMode() {
  const next = $('form-kind').value;
  const custom = next === 'custom';
  if (next !== state.formKind && (custom || state.formKind === 'custom')) {
    if (custom) {
      state.generatedDraft = $('prompt').value;
      $('prompt').value = state.customDraft;
    } else {
      state.customDraft = $('prompt').value;
      $('prompt').value = state.generatedDraft;
    }
  }
  state.formKind = next;
  $('prompt').maxLength = custom ? 300 : 1200;
  $('prompt').placeholder = custom ? 'Stay weird New York!\nMake room for impossible things' : 'Write a love letter to a city that never writes back.';
  if (custom) $('prompt-label').textContent = 'Your words. Exactly.';
  else $('prompt-label').replaceChildren(document.createTextNode('What would you like'), document.createElement('br'), document.createTextNode('the city to say?'));
  $('prompt-hint').textContent = custom ? 'Keep your spaces and line breaks.' : 'Be specific. Be a little strange.';
  $('custom-note').hidden = !custom;
  if (!state.controller) $('compose-label').textContent = custom ? 'Cut my message' : 'Cut it together';
  $('rearrange-button').disabled = Boolean(state.controller) || !state.composition || state.composition.mode === 'demo' || custom;
  updatePromptCount();
}

function selectPanel(panel) {
  const compose = panel === 'compose';
  $('compose-panel').hidden = !compose;
  $('library-panel').hidden = compose;
  for (const [id, selected] of [['compose-tab', compose], ['library-tab', !compose]]) {
    $(id).classList.toggle('is-active', selected);
    $(id).setAttribute('aria-pressed', String(selected));
  }
  if (!compose) renderLibrary();
}

function openSource(source, token = null, snapshot = false) {
  if (!source) return toast('This print has no source record for that word.');
  $('source-selected-word').textContent = token?.text || '';
  renderSourceDialog($('source-dialog-content'), source, { onSave: saveSource, snapshot, token, originalURL: state.originals.get(source.id) });
  $('source-dialog').scrollTop = 0;
  $('source-dialog').showModal();
}

async function saveSource(source, reviewed, ocrText) {
  try {
    const payload = { id: source.id, reviewed };
    if (ocrText !== undefined) payload.ocr_text = ocrText;
    const { source: updated } = await api.review(payload, timeoutSignal(30000));
    state.sources = state.sources.map((item) => item.id === updated.id ? updated : item);
    renderLibrary();
    try { setStatus(await api.status(timeoutSignal(10000))); } catch { /* The successful save still stands if the status refresh fails. */ }
    toast(reviewed ? 'Source saved and marked reviewed.' : 'Source saved. It needs review before live composition.');
    return updated;
  } catch (error) {
    toast(explainError(error));
    throw new Error(explainError(error));
  }
}

function renderLibrary() {
  const query = $('source-search').value.trim().toLocaleLowerCase();
  const unreviewedOnly = $('unreviewed-filter').checked;
  const sources = state.sources.filter((source) => {
    const haystack = [source.title, source.borough, source.block, source.lot, source.ocr_text].join(' ').toLocaleLowerCase();
    return (!query || haystack.includes(query)) && (!unreviewedOnly || !source.reviewed);
  });
  renderSourceGrid($('source-grid'), sources, { onOpen: (source) => openSource(source), onReview: saveSource });
  $('library-empty').hidden = sources.length > 0;
  if (!state.sources.length) $('library-empty').textContent = 'Your source drawer is empty. Import archive photographs to begin.';
  else $('library-empty').textContent = 'No sources match. Try another word or clear the review filter.';
  const reviewed = state.sources.filter((source) => source.reviewed).length;
  $('library-summary').textContent = state.status?.mode === 'demo' ? `${sources.length} sample vocabularies` : `${sources.length} of ${state.sources.length} photographs · ${reviewed} reviewed`;
  $('source-count').textContent = `${state.sources.length} ${state.status?.mode === 'demo' ? 'samples' : 'photos'}`;
}

function updatePromptCount() {
  const custom = $('form-kind').value === 'custom';
  $('prompt-count').textContent = `${[...$('prompt').value].length.toLocaleString()} / ${custom ? '300 characters' : '1,200'}`;
}

function setComposing(active) {
  $('compose-button').disabled = active;
  $('rearrange-button').disabled = active || !state.composition || state.composition.mode === 'demo' || $('form-kind').value === 'custom';
  $('compose-button').classList.toggle('is-loading', active);
  $('compose-label').textContent = active ? 'At work on the press…' : $('form-kind').value === 'custom' ? 'Cut my message' : 'Cut it together';
  $('compose-icon').textContent = active ? '✳' : '↗';
  $('cancel-button').hidden = !active;
  $('paper').setAttribute('aria-busy', String(active));
  $('request-status').classList.remove('is-error');
}

function clearAudio() {
  state.speechController?.abort();
  state.speechController = null;
  $('speech-audio').pause();
  $('speech-audio').hidden = true;
  $('speech-audio').removeAttribute('src');
  if (state.audioURL) URL.revokeObjectURL(state.audioURL);
  state.audioURL = null;
}

async function displayComposition(composition, signal) {
  if (composition.verified !== true || !Array.isArray(composition.lines) || !Array.isArray(composition.sources)) {
    throw new Error('The machine returned a print without verified word provenance. No new print was displayed.');
  }
  let originals = new Map();
  if (composition.mode !== 'demo') {
    const sources = liveCropSources(composition);
    $('request-status').textContent = 'Checking the original photographs and preparing their cutouts…';
    originals = await loadOriginals(sources, signal);
    signal?.throwIfAborted();
  }
  renderComposition($('composition'), composition, (source, token) => openSource(source, token, true), originals);
  clearAudio();
  state.composition = composition;
  state.originals = originals;
  $('composition').hidden = false;
  $('empty-composition').hidden = true;
  $('edition').textContent = composition.mode === 'demo' ? 'SAMPLE EDITION' : 'ORIGINAL PHOTO CUTS';
  const allReviewed = composition.sources.every((source) => source.reviewed);
  $('paper-footnote').textContent = composition.mode === 'demo' ? 'SAMPLE VOCABULARY · NOT ARCHIVAL EVIDENCE' : allReviewed ? 'CUT FROM ORIGINAL PHOTOGRAPHS. EVERY WORD TRACED.' : 'SOURCE TRANSCRIPTIONS NEED REVIEW.';
  $('composition-instruction').textContent = composition.mode === 'demo' ? '↖ Tap any word to see where it came from.' : '↖ Tap a word or letter to find it in the original photograph.';
  const assembled = composition.lines.flat().filter((token) => token.kind === 'assembled');
  const letters = assembled.reduce((sum, token) => sum + token.pieces.length, 0);
  $('composition-stats').textContent = `${composition.stats.words} words / ${composition.stats.source_count} photographs${letters ? `\n${letters} letter cuts used` : ''}`;
  $('composition-warnings').replaceChildren();
  for (const warning of composition.warnings || []) $('composition-warnings').append(element('p', '', warning));
  $('composition-warnings').hidden = !(composition.warnings || []).length;
  $('trace-list').replaceChildren();
  for (const item of composition.trace || []) {
    const li = element('li');
    li.append(element('strong', '', item.step), document.createTextNode(item.detail));
    $('trace-list').append(li);
  }
  $('trace').hidden = !(composition.trace || []).length;
  $('copy-button').disabled = false;
  $('rearrange-button').disabled = composition.mode === 'demo' || $('form-kind').value === 'custom';
  $('export-button').disabled = false;
  $('speech-button').disabled = false;
  $('speech-button').textContent = 'Listen ▷';
}

async function compose(event, reuseId = null) {
  event?.preventDefault();
  if (state.controller) return;
  const custom = $('form-kind').value === 'custom';
  if (reuseId && custom) return toast('Use Cut my message to preserve your exact custom wording.');
  const prompt = reuseId ? state.composition.prompt : custom ? $('prompt').value : $('prompt').value.trim();
  if (!prompt.trim()) return $('prompt').focus();
  if (custom && [...prompt].length > 300) {
    $('request-status').textContent = 'Keep your custom message to 300 characters, including spaces and line breaks.';
    $('request-status').classList.add('is-error');
    return;
  }
  const controller = new AbortController();
  state.controller = controller;
  let timedOut = false;
  const timeout = setTimeout(() => { timedOut = true; controller.abort(); }, 120000);
  setComposing(true);
  $('request-status').textContent = reuseId ? 'Rearranging the same words from the same photographs, with no new search…' : state.status?.mode === 'demo' ? 'Arranging the sample vocabulary. No model or search services are called in sample mode.' : custom ? 'Finding photographed words and letters for your exact message…' : 'Searching the source vocabulary, composing, and checking every selected word…';
  try {
    const composition = await api.compose({ prompt, form: $('form-kind').value, include_unreviewed: false, ...(reuseId ? { reuse_id: reuseId } : {}) }, controller.signal);
    await displayComposition(composition, controller.signal);
    $('request-status').textContent = composition.mode === 'demo' ? 'Sample print ready. This is a preset composition for the selected form; your brief is used in live mode.' : typeof composition.exact_text === 'string' ? 'Your exact wording, cut from verified original photographs.' : 'Fresh off the press. Every cutout comes from a verified original photograph.';
    if (matchMedia('(max-width: 620px)').matches) $('press-title').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (error) {
    $('request-status').classList.add('is-error');
    $('request-status').textContent = timedOut ? 'This composition took longer than two minutes. Try a shorter brief, or check the server logs for service errors.' : explainError(error);
  } finally {
    clearTimeout(timeout);
    state.controller = null;
    const wasError = $('request-status').classList.contains('is-error');
    setComposing(false);
    $('request-status').classList.toggle('is-error', wasError);
  }
}

async function speakComposition() {
  if (!state.composition || state.speechController) return;
  const compositionId = state.composition.id;
  const controller = new AbortController();
  state.speechController = controller;
  const timeout = setTimeout(() => controller.abort(), 90000);
  $('speech-button').disabled = true;
  $('speech-button').textContent = 'Preparing audio…';
  try {
    const blob = await api.speech(compositionId, controller.signal);
    if (state.composition.id !== compositionId) return;
    if (state.audioURL) URL.revokeObjectURL(state.audioURL);
    state.audioURL = URL.createObjectURL(blob);
    $('speech-audio').src = state.audioURL;
    $('speech-audio').hidden = false;
    try { await $('speech-audio').play(); } catch { toast('Audio is ready. Press play below the print.'); }
  } catch (error) {
    if (error.name !== 'AbortError') toast(explainError(error));
    else if (state.composition.id === compositionId) toast('Audio generation was canceled or timed out.');
  } finally {
    clearTimeout(timeout);
    if (state.speechController === controller) state.speechController = null;
    $('speech-button').disabled = false;
    $('speech-button').textContent = 'Listen ▷';
  }
}

$('compose-tab').addEventListener('click', () => selectPanel('compose'));
$('library-tab').addEventListener('click', () => selectPanel('library'));
$('compose-form').addEventListener('submit', compose);
$('rearrange-button').addEventListener('click', () => state.composition && compose(null, state.composition.id));
$('cancel-button').addEventListener('click', () => state.controller?.abort());
$('prompt').addEventListener('input', updatePromptCount);
$('form-kind').addEventListener('change', syncFormMode);
$('source-search').addEventListener('input', renderLibrary);
$('unreviewed-filter').addEventListener('change', renderLibrary);
$('close-drawer').addEventListener('click', () => $('source-dialog').close());
$('source-dialog').addEventListener('click', (event) => {
  if (event.target === $('source-dialog')) {
    const bounds = $('source-dialog').getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) $('source-dialog').close();
  }
});
for (const button of document.querySelectorAll('.sample-prompt')) button.addEventListener('click', () => {
  $('form-kind').value = button.dataset.form;
  syncFormMode();
  $('prompt').value = button.dataset.prompt;
  updatePromptCount();
  $('prompt').focus();
});
$('copy-button').addEventListener('click', async () => {
  if (!state.composition) return;
  try { await navigator.clipboard.writeText(plainText(state.composition)); toast('The words are yours. Copied to clipboard.'); }
  catch { toast('Clipboard access is unavailable. Allow clipboard access in your browser and try again.'); }
});
$('export-button').addEventListener('click', async () => {
  if (!state.composition || state.exportController) return;
  const controller = new AbortController();
  state.exportController = controller;
  const composition = state.composition;
  const timeout = setTimeout(() => controller.abort(), 90000);
  $('export-button').disabled = true;
  $('export-button').textContent = 'Preparing poster…';
  try {
    await downloadPoster(composition, { signal: controller.signal });
    toast(composition.mode === 'demo' ? 'Sample poster saved, with its synthetic vocabulary label.' : 'Poster saved with original photo cutouts and source credits.');
  } catch (error) {
    toast(error.name === 'AbortError' ? 'Poster export timed out. Try again with fewer source photographs.' : explainError(error));
  } finally {
    clearTimeout(timeout);
    state.exportController = null;
    $('export-button').disabled = false;
    $('export-button').textContent = 'Save poster ↓';
  }
});
$('speech-button').addEventListener('click', speakComposition);
window.addEventListener('pagehide', () => { state.controller?.abort(); state.exportController?.abort(); clearAudio(); });

syncFormMode();
const initial = await Promise.allSettled([api.status(timeoutSignal(15000)), api.sources(timeoutSignal(15000))]);
if (initial[0].status === 'fulfilled') setStatus(initial[0].value);
else {
  $('service-status').dataset.mode = 'error';
  $('status-text').textContent = 'Workshop unavailable';
  showError(explainError(initial[0].reason));
}
if (initial[1].status === 'fulfilled') {
  state.sources = initial[1].value.sources;
  renderLibrary();
} else showError(`The source drawer could not load. ${explainError(initial[1].reason)}`);
