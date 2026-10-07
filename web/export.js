import { liveCropSources, loadOriginals } from './crops.js';

const escapeXML = (value) => String(value).replace(/[<>&"']/g, (character) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;', "'": '&apos;' })[character]);

export function plainText(composition) {
  return composition.lines.map((line) => line.map((token) => token.text).join(' ')).join('\n');
}

function wrapText(text, limit = 102) {
  const words = text.split(/\s+/).flatMap((word) => {
    if (word.length <= limit) return [word];
    const chunks = [];
    for (let index = 0; index < word.length; index += limit) chunks.push(word.slice(index, index + limit));
    return chunks;
  });
  const lines = [];
  let line = '';
  for (const word of words) {
    if (line && line.length + word.length + 1 > limit) {
      lines.push(line);
      line = word;
    } else line += `${line ? ' ' : ''}${word}`;
  }
  if (line) lines.push(line);
  return lines;
}

/** Synthetic demo typography is never used as a fallback for live photo crops. */
function demoPosterSVG(composition) {
  const width = 1000;
  const margin = 72;
  const maxLineWidth = width - margin * 2;
  const lines = [];
  for (const sourceLine of composition.lines) {
    let current = [];
    let measured = 0;
    for (const token of sourceLine) {
      const approximateWidth = Math.max(35, [...String(token.text)].length * 22 + 24);
      if (current.length && measured + approximateWidth > maxLineWidth) {
        lines.push(current);
        current = [];
        measured = 0;
      }
      current.push({ ...token, width: Math.min(approximateWidth, maxLineWidth) });
      measured += approximateWidth + 10;
    }
    if (current.length) lines.push(current);
  }
  const usedIds = new Set(composition.lines.flat().map((token) => token.source_id));
  const sources = composition.sources.filter((source) => usedIds.has(source.id));
  const citations = sources.flatMap((source, index) => {
    const metadata = [source.title, source.attribution, source.source_url].filter(Boolean).join(' — ');
    return wrapText(`${index + 1}. ${metadata}`);
  });
  const sourceStart = Math.max(790, 220 + lines.length * 75);
  const height = sourceStart + 105 + Math.max(1, citations.length) * 17 + 70;
  const colors = [ ['#ece5d3', '#24241f'], ['#24241f', '#fbf9ef'], ['#f5ead3', '#db4329'], ['#e0d1b1', '#24241f'] ];
  let wordIndex = 0;
  let art = '';
  for (let row = 0; row < lines.length; row += 1) {
    let x = margin;
    const y = 190 + row * 75;
    for (const token of lines[row]) {
      const style = wordIndex % colors.length;
      const [background, foreground] = colors[style];
      const angle = [-1.4, .6, -1, 1.5, -.4][wordIndex % 5];
      const label = escapeXML(token.text);
      const source = sources.find((item) => item.id === token.source_id);
      const fontSize = Math.min(style === 1 ? 36 : 43, Math.max(12, (token.width - 22) / Math.max(1, [...String(token.text)].length) * 1.65));
      art += `<g transform="rotate(${angle} ${x + token.width / 2} ${y})"><title>${label} — ${escapeXML(source?.title || token.source_id)}</title><rect x="${x}" y="${y - 43}" width="${token.width}" height="59" fill="${background}"/><text x="${x + 12}" y="${y}" textLength="${token.width - 24}" lengthAdjust="spacingAndGlyphs" font-size="${fontSize}" font-family="${style === 1 ? 'Arial,sans-serif' : 'Georgia,serif'}" ${style === 3 ? 'font-style="italic"' : ''} fill="${foreground}">${label}</text></g>`;
      x += token.width + 10;
      wordIndex += 1;
    }
  }
  const allReviewed = sources.every((source) => source.reviewed);
  const evidenceLabel = composition.mode === 'demo' ? 'SAMPLE VOCABULARY · NOT ARCHIVAL EVIDENCE' : allReviewed ? 'EVERY WORD TRACED TO A REVIEWED SOURCE' : 'WORDS TRACED TO SOURCES · TRANSCRIPTION REVIEW REQUIRED';
  const citationSVG = citations.map((line, index) => `<text x="${margin}" y="${sourceStart + 70 + index * 17}" font-family="Arial,sans-serif" font-size="11" fill="#686353">${escapeXML(line)}</text>`).join('');
  return `<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-label="A composition from StreetScript"><title>StreetScript</title><desc>${escapeXML(plainText(composition))}</desc><rect width="100%" height="100%" fill="#fbf9ef"/><text x="${margin}" y="62" font-family="monospace" font-size="11" letter-spacing="1.5" fill="#797363">NEW YORK / CUT &amp; COMPOSED</text><text x="${width - margin}" y="62" text-anchor="end" font-family="monospace" font-size="11" fill="#797363">NYC CUT-UP MACHINE</text><line x1="${margin}" x2="${width - margin}" y1="83" y2="83" stroke="#d1c9b6"/>${art}<line x1="${margin}" x2="${width - margin}" y1="${sourceStart}" y2="${sourceStart}" stroke="#d1c9b6"/><text x="${margin}" y="${sourceStart + 30}" font-family="monospace" font-size="10" letter-spacing="1" fill="#db4329">${evidenceLabel}</text>${citationSVG}<text x="${margin}" y="${height - 35}" font-family="monospace" font-size="9" fill="#797363">WORDS WITH A PAST. SOMETHING NEW TO SAY.</text></svg>`;
}

/** Each verified original is embedded once; every word is a viewport into it. */
export async function posterSVG(composition, { signal } = {}) {
  if (composition.mode === 'demo') return demoPosterSVG(composition);
  const sources = liveCropSources(composition);
  const originals = await loadOriginals(sources, signal, { dataURLs: true });
  signal?.throwIfAborted();
  const width = 1000;
  const margin = 72;
  const printableWidth = width - margin * 2;
  const ids = new Map(sources.map((source, index) => [source.id, `archive-original-${index}`]));
  const definitions = sources.map((source) => `<image id="${ids.get(source.id)}" x="0" y="0" width="${source.image_width}" height="${source.image_height}" href="${escapeXML(originals.get(source.id))}"/>`).join('');
  let x = margin;
  let y = 150;
  let rowHeight = 0;
  let wordIndex = 0;
  let art = '';
  for (const line of composition.lines) {
    for (const token of line) {
      const crop = token.crop;
      let cropHeight = 76;
      let cropWidth = crop.width / crop.height * cropHeight;
      if (cropWidth > printableWidth) {
        cropHeight *= printableWidth / cropWidth;
        cropWidth = printableWidth;
      }
      if (x > margin && x + cropWidth > width - margin) {
        x = margin;
        y += rowHeight + 25;
        rowHeight = 0;
      }
      const angle = [-1.3, .7, -.8, 1.1, -.3][wordIndex % 5];
      const sourceId = ids.get(token.source_id);
      const clipId = `word-clip-${wordIndex}`;
      art += `<g transform="rotate(${angle} ${x + cropWidth / 2} ${y + cropHeight / 2})"><title>${escapeXML(token.text)}</title><svg x="${x}" y="${y}" width="${cropWidth}" height="${cropHeight}" viewBox="${crop.x} ${crop.y} ${crop.width} ${crop.height}" preserveAspectRatio="xMidYMid meet" overflow="hidden"><defs><clipPath id="${clipId}" clipPathUnits="userSpaceOnUse"><rect x="${crop.x}" y="${crop.y}" width="${crop.width}" height="${crop.height}"/></clipPath></defs><use href="#${sourceId}" clip-path="url(#${clipId})"/></svg></g>`;
      x += cropWidth + 15;
      rowHeight = Math.max(rowHeight, cropHeight);
      wordIndex += 1;
    }
    x = margin;
    y += rowHeight + 32;
    rowHeight = 0;
  }
  const citationLines = sources.flatMap((source, index) => wrapText(`${index + 1}. ${[source.title, source.attribution, source.source_url].filter(Boolean).join(' — ')}`));
  const footerY = Math.max(830, y + 45);
  const height = footerY + 95 + citationLines.length * 17;
  const citations = citationLines.map((line, index) => `<text x="${margin}" y="${footerY + 60 + index * 17}" font-family="Arial,sans-serif" font-size="11" fill="#686353">${escapeXML(line)}</text>`).join('');
  const metadata = { format: 'nyc-cut-up-photo-poster-v1', composition_id: composition.id, text: plainText(composition), sources: sources.map((source) => ({ id: source.id, title: source.title, attribution: source.attribution, source_url: source.source_url, image_sha256: source.image_sha256, image_width: source.image_width, image_height: source.image_height })), lines: composition.lines.map((line) => line.map(({ id, text, source_id, crop }) => ({ id, text, source_id, crop }))) };
  return `<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-label="An archival photo collage from StreetScript"><title>StreetScript — original photographic cutouts</title><desc>${escapeXML(plainText(composition))}</desc><metadata id="cutup-provenance">${escapeXML(JSON.stringify(metadata))}</metadata><defs>${definitions}</defs><rect width="100%" height="100%" fill="#fbf9ef"/><text x="${margin}" y="62" font-family="monospace" font-size="11" letter-spacing="1.5" fill="#797363">NEW YORK / CUT &amp; COMPOSED</text><text x="${width - margin}" y="62" text-anchor="end" font-family="monospace" font-size="11" fill="#797363">NYC CUT-UP MACHINE</text><line x1="${margin}" x2="${width - margin}" y1="83" y2="83" stroke="#d1c9b6"/>${art}<line x1="${margin}" x2="${width - margin}" y1="${footerY}" y2="${footerY}" stroke="#d1c9b6"/><text x="${margin}" y="${footerY + 29}" font-family="monospace" font-size="10" letter-spacing="1" fill="#db4329">CUT FROM ORIGINAL PHOTOGRAPHS / SOURCE CREDITS</text>${citations}</svg>`;
}

export async function downloadPoster(composition, options = {}) {
  const svg = await posterSVG(composition, options);
  options.signal?.throwIfAborted();
  const url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `streetscript-${String(composition.id || 'print').replace(/[^a-zA-Z0-9_-]/g, '').slice(0, 60)}.svg`;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
