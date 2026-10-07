const SVG_NS = 'http://www.w3.org/2000/svg';
const imageCache = new Map();
const MAX_IMAGE_BYTES = 25 * 1024 * 1024;
let clipSequence = 0;

export function svgElement(tag, attributes = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, String(value));
  return node;
}

export function archiveImageURL(value) {
  if (!value || typeof value !== 'string') return null;
  try {
    const url = new URL(value, location.origin);
    if (url.origin !== location.origin || !/^\/archive\/[A-Za-z0-9_.-]+\.(?:jpg|jpeg|png)$/i.test(url.pathname) || url.search || url.hash) return null;
    return url.href;
  } catch { return null; }
}

export function validateCrop(token, source) {
  const crop = token?.crop;
  const invalid = !source || !Number.isInteger(source.image_width) || !Number.isInteger(source.image_height)
    || source.image_width <= 0 || source.image_height <= 0
    || !archiveImageURL(source.image_url) || !/^[a-f0-9]{64}$/i.test(source.image_sha256 || '')
    || !crop || !['x', 'y', 'width', 'height'].every((key) => Number.isFinite(crop[key]))
    || crop.x < 0 || crop.y < 0 || crop.width <= 0 || crop.height <= 0
    || crop.x + crop.width > source.image_width || crop.y + crop.height > source.image_height;
  if (invalid) throw new Error(`“${token?.text || 'This word'}” has no valid photo crop. Add or correct its word bounding box in the source data, then reindex and compose again.`);
  return crop;
}

export function liveCropSources(composition) {
  const sources = new Map(composition.sources.map((source) => [source.id, source]));
  const used = new Map();
  for (const token of composition.lines.flat()) {
    const source = sources.get(token.source_id);
    validateCrop(token, source);
    if (source.synthetic) throw new Error('A live composition contains a synthetic source. Reindex the archive corpus and compose again.');
    used.set(source.id, source);
  }
  return [...used.values()];
}

function blobDataURL(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error('The archive photograph could not be prepared for the poster.'));
    reader.readAsDataURL(blob);
  });
}

async function verifyOriginal(source, signal) {
  const response = await fetch(archiveImageURL(source.image_url), { credentials: 'same-origin', signal, redirect: 'error', cache: 'force-cache' });
  if (!response.ok) throw new Error(`The photograph for “${source.title}” could not load. Restore its local archive image and try again.`);
  const announced = Number(response.headers.get('content-length'));
  if (announced > MAX_IMAGE_BYTES) throw new Error('An archive photograph is too large to prepare in the browser (25 MB maximum).');
  const buffer = await response.arrayBuffer();
  if (buffer.byteLength > MAX_IMAGE_BYTES) throw new Error('An archive photograph exceeds the 25 MB browser limit.');
  const bytes = new Uint8Array(buffer);
  const jpeg = bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff;
  const png = bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e && bytes[3] === 0x47;
  if (!jpeg && !png) throw new Error('The archive image is not a supported original JPEG or PNG. Restore the original photograph.');
  if (!globalThis.crypto?.subtle) throw new Error('Photo verification requires localhost or HTTPS. Open the workshop on localhost and try again.');
  const digest = await crypto.subtle.digest('SHA-256', buffer);
  const hash = [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
  if (hash !== source.image_sha256.toLowerCase()) throw new Error(`The original photograph for “${source.title}” has changed. Rebuild its word crops and reindex before composing.`);
  const blob = new Blob([buffer], { type: jpeg ? 'image/jpeg' : 'image/png' });
  const decoded = await createImageBitmap(blob);
  const matches = decoded.width === source.image_width && decoded.height === source.image_height;
  decoded.close();
  if (!matches) throw new Error(`The stored photo dimensions for “${source.title}” do not match its original image. Rebuild its word crops and reindex.`);
  signal?.throwIfAborted();
  return { blob, displayURL: URL.createObjectURL(blob), bytes: buffer.byteLength };
}

/** Share verified original bytes between the press and standalone SVG export. */
export async function loadOriginals(sources, signal, { dataURLs = false } = {}) {
  const originals = new Map();
  let totalBytes = 0;
  for (const source of sources) {
    signal?.throwIfAborted();
    const key = `${archiveImageURL(source.image_url)}:${source.image_sha256}:${source.image_width}:${source.image_height}`;
    let original = imageCache.get(key);
    if (!original) {
      original = await verifyOriginal(source, signal);
      imageCache.set(key, original);
      // Cache at most 24 originals. Blob URLs are released when the page exits;
      // a print already on screen may still reference an evicted entry.
      if (imageCache.size > 24) imageCache.delete(imageCache.keys().next().value);
    }
    totalBytes += original.bytes;
    if (totalBytes > 100 * 1024 * 1024) throw new Error('This print needs more than 100 MB of source photographs. Compose a shorter print using fewer sources.');
    originals.set(source.id, dataURLs ? await blobDataURL(original.blob) : original.displayURL);
  }
  return originals;
}

export function cropViewport(token, source, { originalURL, className = 'word-crop-svg' } = {}) {
  const crop = validateCrop(token, source);
  const svg = svgElement('svg', { viewBox: `${crop.x} ${crop.y} ${crop.width} ${crop.height}`, width: crop.width, height: crop.height, preserveAspectRatio: 'xMidYMid meet', class: className, 'aria-hidden': 'true', focusable: 'false' });
  const clipId = `photo-word-clip-${++clipSequence}`;
  const definitions = svgElement('defs');
  const clip = svgElement('clipPath', { id: clipId, clipPathUnits: 'userSpaceOnUse' });
  clip.append(svgElement('rect', { x: crop.x, y: crop.y, width: crop.width, height: crop.height }));
  definitions.append(clip);
  svg.append(definitions, svgElement('image', { href: originalURL || archiveImageURL(source.image_url), x: 0, y: 0, width: source.image_width, height: source.image_height, 'clip-path': `url(#${clipId})` }));
  return svg;
}

export function highlightedPhoto(token, source, originalURL) {
  const crop = validateCrop(token, source);
  const svg = svgElement('svg', { viewBox: `0 0 ${source.image_width} ${source.image_height}`, width: source.image_width, height: source.image_height, class: 'source-photo-highlight', role: 'img', 'aria-label': `${source.title}. The selected word, ${token.text}, is outlined.`, focusable: 'false' });
  svg.append(svgElement('image', { href: originalURL || archiveImageURL(source.image_url), x: 0, y: 0, width: source.image_width, height: source.image_height }));
  svg.append(svgElement('rect', { x: crop.x, y: crop.y, width: crop.width, height: crop.height, fill: 'none', stroke: '#ed492c', 'stroke-width': 2, 'vector-effect': 'non-scaling-stroke', class: 'source-crop-outline' }));
  return svg;
}
