import { archiveImageURL, cropViewport, highlightedPhoto, liveCropSources, pieceHeight, tokenPieces, tokenPrefixUnits } from './crops.js';

export function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function safeURL(value, { local = false } = {}) {
  if (!value || typeof value !== 'string') return null;
  try {
    const url = new URL(value, location.origin);
    if (url.protocol !== 'https:' && url.protocol !== 'http:') return null;
    if (local) return archiveImageURL(value);
    if (value.startsWith('https://') || value.startsWith('http://')) return url.href;
  } catch { /* Missing or malformed archive links have no navigation affordance. */ }
  return null;
}

export function isSample(source) {
  return source.synthetic === true || String(source.id).startsWith('sample-');
}

function sourceImage(source, className) {
  const url = safeURL(source.image_url, { local: true });
  if (!url) return element('div', 'source-no-image', isSample(source) ? 'Sample words.\nNo archive photograph.' : 'Image unavailable');
  const image = element('img', className);
  image.src = url;
  image.alt = source.title || 'Archive source photograph';
  image.loading = 'lazy';
  image.referrerPolicy = 'no-referrer';
  image.addEventListener('error', () => image.replaceWith(element('div', 'source-no-image', 'The source image could not load. Use the archive link below.')), { once: true });
  return image;
}

export function sourceDetails(source) {
  return [source.borough, source.block ? `Block ${source.block}` : '', source.lot ? `Lot ${source.lot}` : ''].filter(Boolean).join(' / ');
}

export function renderComposition(container, composition, onSelectSource, originals = new Map()) {
  if (composition.mode !== 'demo') liveCropSources(composition);
  const fragment = document.createDocumentFragment();
  const sourceMap = new Map(composition.sources.map((source) => [source.id, source]));
  let index = 0;
  for (const line of composition.lines) {
    const row = element('div', 'composition-line');
    if (!line.length) row.classList.add('is-blank');
    const makeButton = (piece, assembledWord = '') => {
      const source = sourceMap.get(piece.source_id);
      const demo = composition.mode === 'demo';
      const button = element('button', `word-token${demo ? '' : ' is-crop'}${assembledWord ? ' glyph-token' : ''}`, demo ? piece.text : undefined);
      button.type = 'button';
      if (demo) button.dataset.style = String(index % 4);
      else {
        const height = pieceHeight(piece, assembledWord ? 54 : 64);
        button.style.width = `${Math.min(520, Math.max(4, piece.crop.width / piece.crop.height * height))}px`;
        if (/^['"‘’“”]$/.test(piece.text)) button.classList.add('raised-glyph');
        if (/^[-–—_]$/.test(piece.text)) button.classList.add('middle-glyph');
        button.append(cropViewport(piece, source, { originalURL: originals.get(source.id) }));
      }
      button.style.setProperty('--tilt', `${[-1.7, .6, -1.1, 1.6, -.4][index % 5]}deg`);
      button.setAttribute('aria-label', `${assembledWord ? `Letter ${piece.text}, in ${assembledWord}` : piece.text}. View source: ${source?.title || piece.source_id}`);
      button.title = `${assembledWord ? `${piece.text} in ${assembledWord} · ` : ''}Found in ${source?.title || piece.source_id}`;
      button.addEventListener('click', () => onSelectSource(source, assembledWord ? { ...piece, assembled_word: assembledWord } : piece));
      index += 1;
      return button;
    };
    for (let position = 0; position < line.length; position += 1) {
      const token = line[position];
      const unit = element('span', 'composition-unit');
      const whitespace = tokenPrefixUnits(token, position);
      unit.style.paddingInlineStart = `min(${whitespace * 14}px, 65%)`;
      unit.dataset.prefix = typeof token.prefix === 'string' ? token.prefix : position ? ' ' : '';
      if (token.kind === 'assembled' && composition.mode !== 'demo') {
        const group = element('span', 'assembled-word');
        group.style.setProperty('--letter-gap', `${Math.min(3, 60 / token.pieces.length)}px`);
        group.setAttribute('role', 'group');
        group.setAttribute('aria-label', `${token.text}, assembled from photographed letters`);
        for (const piece of tokenPieces(token)) group.append(makeButton(piece, token.text));
        unit.append(group);
      } else unit.append(makeButton(token));
      row.append(unit);
    }
    fragment.append(row);
  }
  container.replaceChildren(fragment);
}

export function renderSourceGrid(container, sources, { onOpen, onReview }) {
  container.replaceChildren();
  for (const source of sources) {
    const card = element('article', 'source-card');
    const visual = element('button', 'source-card-visual');
    visual.type = 'button';
    visual.setAttribute('aria-label', `Inspect ${source.title}`);
    visual.append(sourceImage(source, ''));
    visual.addEventListener('click', () => onOpen(source));
    card.append(visual, element('h3', '', source.title || 'Untitled source'), element('p', 'source-card-detail', sourceDetails(source)));
    if (isSample(source)) card.append(element('span', 'sample-label', 'Sample vocabulary · not archival evidence'));
    card.append(element('p', 'source-card-text', source.ocr_text));
    const bottom = element('div', 'source-card-bottom');
    const inspect = element('button', '', 'Inspect source ↗');
    inspect.type = 'button';
    inspect.addEventListener('click', () => onOpen(source));
    const reviewLabel = element('label', 'source-reviewed');
    const checkbox = element('input');
    checkbox.type = 'checkbox';
    checkbox.checked = Boolean(source.reviewed);
    checkbox.disabled = isSample(source);
    checkbox.setAttribute('aria-label', `Mark ${source.title} reviewed`);
    checkbox.addEventListener('change', async () => {
      checkbox.disabled = true;
      try { await onReview(source, checkbox.checked); }
      catch { checkbox.checked = Boolean(source.reviewed); }
      finally { checkbox.disabled = isSample(source); }
    });
    reviewLabel.append(checkbox, document.createTextNode(isSample(source) ? 'Sample' : 'Reviewed'));
    bottom.append(inspect, reviewLabel);
    card.append(bottom);
    container.append(card);
  }
}

export function renderSourceDialog(container, source, { onSave, snapshot = false, token = null, originalURL }) {
  container.replaceChildren();
  const title = element('h2', '', source.title || 'Untitled source');
  title.id = 'source-dialog-title';
  container.append(title, element('p', 'source-card-detail', sourceDetails(source)));
  if (isSample(source)) container.append(element('p', 'sample-label', 'Sample vocabulary · not archival evidence'));
  if (token?.assembled_word) container.append(element('p', 'source-letter-context', `This photographed letter is part of “${token.assembled_word}”. Each letter keeps its own source.`));
  if (token?.crop && !isSample(source)) {
    container.append(element('p', 'source-dialog-label', 'The original pixels, enlarged'));
    const enlargement = element('div', 'selected-crop-view');
    enlargement.append(cropViewport(token, source, { originalURL, className: 'selected-crop-svg' }));
    container.append(enlargement);
    container.append(element('p', 'source-dialog-label', 'Where this cut comes from'));
    container.append(highlightedPhoto(token, source, originalURL));
    const crop = token.crop;
    container.append(element('p', 'source-crop-coordinates', `${crop.width} × ${crop.height} px at (${crop.x}, ${crop.y})${crop.method ? ` · ${crop.method}` : ''}`));
  } else container.append(sourceImage(source, 'source-dialog-image'));
  container.append(element('p', 'source-dialog-label', 'Words from this source'));
  container.append(element('p', 'source-transcription', source.ocr_text));
  if (source.transcription_method) {
    const method = source.transcription_method === 'vision' ? 'Vision transcription' : source.transcription_method === 'manual' ? 'Visual transcription' : 'OCR transcription';
    container.append(element('p', 'source-attribution', `${method}${source.transcription_model ? ` · ${source.transcription_model}` : ''}${source.reviewed ? ' · visually reviewed' : ' · awaiting review'}`));
  }
  container.append(element('p', 'source-attribution', source.attribution || 'No attribution was provided. Verify the source before use.'));
  const url = safeURL(source.source_url);
  if (url) {
    const link = element('a', 'archive-link', 'View original archive record ↗');
    link.href = url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    container.append(link);
  }
  if (snapshot) container.append(element('p', 'source-attribution', 'This is the source snapshot used for this print. Open the source drawer tab to review or update the current transcription.'));
  if (isSample(source) || snapshot) return;
  const form = element('form', 'source-review-form');
  const textLabel = element('label', 'source-dialog-label', 'Check and correct the transcription');
  textLabel.htmlFor = 'review-transcription';
  const textarea = element('textarea');
  textarea.id = 'review-transcription';
  textarea.value = source.ocr_text || '';
  textarea.maxLength = 50000;
  textarea.rows = 5;
  textarea.required = true;
  const reviewLabel = element('label', 'source-reviewed');
  const checkbox = element('input');
  checkbox.type = 'checkbox';
  checkbox.checked = Boolean(source.reviewed);
  reviewLabel.append(checkbox, document.createTextNode('I checked these words against the source image.'));
  const save = element('button', 'save-source', 'Save transcription & review');
  save.type = 'submit';
  const message = element('p', 'source-review-message');
  message.setAttribute('role', 'status');
  form.append(textLabel, textarea, reviewLabel, save, message);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    save.disabled = true;
    message.textContent = 'Saving…';
    try {
      await onSave(source, checkbox.checked, textarea.value);
      message.textContent = 'Saved. New compositions will use this transcription.';
      container.querySelector('.source-transcription').textContent = textarea.value;
    } catch (error) { message.textContent = error.message || 'Unable to save. Please try again.'; }
    finally { save.disabled = false; }
  });
  container.append(form);
}
