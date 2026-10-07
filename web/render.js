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
    if (local && url.origin === location.origin && url.pathname.startsWith('/archive/')) return url.href;
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

export function renderComposition(container, composition, onSelectSource) {
  container.replaceChildren();
  const sourceMap = new Map(composition.sources.map((source) => [source.id, source]));
  let index = 0;
  for (const line of composition.lines) {
    const row = element('div', 'composition-line');
    for (const token of line) {
      const source = sourceMap.get(token.source_id);
      const button = element('button', 'word-token', token.text);
      button.type = 'button';
      button.dataset.style = String(index % 4);
      button.style.setProperty('--tilt', `${[-1.7, .6, -1.1, 1.6, -.4][index % 5]}deg`);
      button.setAttribute('aria-label', `${token.text}. View source: ${source?.title || token.source_id}`);
      button.title = `Found in ${source?.title || token.source_id}`;
      button.addEventListener('click', () => onSelectSource(source, token.text));
      row.append(button);
      index += 1;
    }
    container.append(row);
  }
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

export function renderSourceDialog(container, source, { onSave, snapshot = false }) {
  container.replaceChildren();
  const title = element('h2', '', source.title || 'Untitled source');
  title.id = 'source-dialog-title';
  container.append(title, element('p', 'source-card-detail', sourceDetails(source)));
  if (isSample(source)) container.append(element('p', 'sample-label', 'Sample vocabulary · not archival evidence'));
  container.append(sourceImage(source, 'source-dialog-image'));
  container.append(element('p', 'source-dialog-label', 'Words from this source'));
  container.append(element('p', 'source-transcription', source.ocr_text));
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
