"""Extract candidate glyph rectangles from real, approved archival word crops."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import shutil
import string
import subprocess

from .localize import image_metadata, normalized_word

CHARACTERS = string.ascii_letters + string.digits + "!?.',-:;"
TARGETS = string.ascii_uppercase + string.digits + "!?.',-"


def parse_makebox(text: str, crop: dict, image_width: int, image_height: int) -> list[dict]:
    """Map genuine Tesseract bottom-left glyph boxes to original image pixels."""
    boxes = []
    for line in text.splitlines():
        columns = line.rsplit(maxsplit=5)
        if len(columns) != 6 or len(columns[0]) != 1:
            continue
        character = columns[0].replace("’", "'")
        if character not in CHARACTERS:
            continue
        try:
            left, bottom, right, top, page = map(int, columns[1:])
        except ValueError:
            continue
        if page != 0 or left < 0 or bottom < 0 or right <= left or top <= bottom:
            continue
        if right > crop["width"] or top > crop["height"]:
            continue
        box = {"text": character, "x": crop["x"] + left, "y": crop["y"] + crop["height"] - top,
               "width": right - left, "height": top - bottom}
        if box["x"] + box["width"] <= image_width and box["y"] + box["height"] <= image_height:
            boxes.append(box)
    return boxes


def extract_source_letters(source: dict, image_path: Path, output: Path, *, tesseract=None, sips=None) -> dict:
    from .provenance import build_glyph_id

    tesseract = tesseract or shutil.which("tesseract")
    sips = sips or shutil.which("sips")
    if not tesseract or not sips:
        raise ValueError("Letter extraction requires Tesseract and the macOS sips image utility.")
    metadata = image_metadata(image_path)
    if not source.get("reviewed") or not source.get("word_crops"):
        raise ValueError("Letter extraction requires reviewed text and accepted word crops.")
    if source.get("image_sha256") != metadata["image_sha256"]:
        raise ValueError("Source image changed since word crop review.")
    output.mkdir(parents=True, exist_ok=True)
    letters, processed, matched, rejected = {}, set(), 0, []
    for word_crop in source["word_crops"]:
        coordinates = tuple(word_crop[key] for key in ("x", "y", "width", "height"))
        if coordinates in processed:
            continue
        processed.add(coordinates)
        digest = sha256((source["id"] + repr(coordinates)).encode()).hexdigest()[:16]
        cropped = output / f"word-{digest}.png"
        if not cropped.exists():
            result = subprocess.run([sips, "-s", "format", "png", "-c", str(word_crop["height"]),
                                     str(word_crop["width"]), "--cropOffset", str(word_crop["y"]),
                                     str(word_crop["x"]), str(image_path), "--out", str(cropped)],
                                    capture_output=True, text=True, timeout=30)
            if result.returncode:
                raise RuntimeError("Unable to crop an approved source word with sips.")
        output_box = output / f"word-{digest}.box"
        if output_box.exists():
            raw = output_box.read_text(encoding="utf-8")
        else:
            result = subprocess.run([tesseract, str(cropped), "stdout", "-l", "eng", "--psm", "7", "makebox"],
                                    capture_output=True, text=True, timeout=30)
            if result.returncode:
                raise RuntimeError("Tesseract makebox failed for an approved source word.")
            raw = result.stdout
            output_box.write_text(raw, encoding="utf-8")
        boxes = parse_makebox(raw, word_crop, metadata["image_width"], metadata["image_height"])
        reconstructed = "".join(box["text"] for box in boxes)
        if normalized_word(reconstructed) != normalized_word(word_crop["text"]):
            rejected.append({"word": word_crop["text"], "recognized": reconstructed})
            continue
        matched += 1
        for box in boxes:
            ident = build_glyph_id(source["id"], metadata["image_sha256"], box["text"], box)
            letters[ident] = {"id": ident, "source_id": source["id"], **box,
                              "method": "tesseract_makebox", "confidence": 0,
                              "parent_word_id": word_crop["word_id"]}
    return {"source_id": source["id"], "title": source["title"], "image_url": source["image_url"], **metadata,
            "transcription_sha256": sha256(source["ocr_text"].encode()).hexdigest(),
            "letter_crops": list(letters.values()), "status": "pending_visual_review",
            "matched_word_count": matched, "rejected_words": rejected}


def atlas_candidates(proposals: list[dict], per_character: int = 6) -> dict[str, list[tuple[dict, dict]]]:
    groups = {target: [] for target in TARGETS}
    for proposal in proposals:
        for letter in proposal["letter_crops"]:
            target = letter["text"].upper()
            if target in groups:
                groups[target].append((proposal, letter))
    for target in groups:
        groups[target].sort(key=lambda pair: (
            pair[1]["text"].isupper(), pair[1]["width"] <= 2 * pair[1]["height"], pair[1]["height"]), reverse=True)
        groups[target] = groups[target][:per_character]
    return groups


def render_letter_atlas(proposals: list[dict], destination: Path, *, per_character: int = 6) -> None:
    groups = atlas_candidates(proposals, per_character)
    missing = " ".join(target for target, entries in groups.items() if not entries)
    parts = [f'''<!doctype html><html><head><meta charset="utf-8"><title>Archive letter atlas</title>
<style>body{{font:14px system-ui;margin:28px;background:#eee7da;color:#25221d}}h1{{font:38px Georgia}}
.group{{margin:24px 0;break-inside:avoid}}.grid{{display:grid;grid-template-columns:repeat(6,minmax(120px,1fr));gap:12px}}
.tile{{border:1px solid #bbb2a3;background:#fff;padding:10px}}svg{{height:110px;width:100%;background:#ddd}}
.meta{{font:10px monospace;overflow-wrap:anywhere}}.warning{{background:#ffe0a1;padding:12px}}button{{font:inherit;padding:10px}}
</style></head><body><h1>Real archive letter candidates</h1><p class="warning">Missing: {escape(missing or 'none')}.
Check each visible letter and its framing. All pixels come from the original photograph. Character boxes came from
Tesseract segmentation of an exactly recognized, approved word, or explicitly marked manual localization.
Confidence 0 means character confidence was not supplied. Candidates remain unapproved.</p>
<button onclick="downloadAccepted()">Download checked letter IDs</button>''']
    for target, entries in groups.items():
        if not entries:
            continue
        parts.append(f"<section class='group'><h2>{escape(target)}</h2><div class='grid'>")
        for index, (proposal, letter) in enumerate(entries):
            x, y, width, height = [letter[key] for key in ("x", "y", "width", "height")]
            clip = "glyph-" + sha256(letter["id"].encode()).hexdigest()[:16]
            image_name = Path(proposal["image_url"]).name
            parts.append(f'''<div class="tile"><svg viewBox="{x} {y} {width} {height}" role="img" aria-label="Actual letter pixels">
<defs><clipPath id="{clip}"><rect x="{x}" y="{y}" width="{width}" height="{height}"/></clipPath></defs>
<g clip-path="url(#{clip})"><image href="../{escape(image_name, quote=True)}" width="{proposal['image_width']}" height="{proposal['image_height']}"/></g></svg>
<label><input type="checkbox" data-source="{escape(proposal['source_id'], quote=True)}" value="{escape(letter['id'], quote=True)}">{escape(letter['text'])}</label>
<p class="meta">{escape(proposal['title'])}<br>{x},{y} {width}×{height}<br>{escape(letter['method'])}<br>{escape(letter['id'])}</p></div>''')
        parts.append("</div></section>")
    parts.append("""<script>function downloadAccepted(){const data={};for(const el of document.querySelectorAll('input:checked')){
(data[el.dataset.source]??=[]).push(el.value);}const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
a.download='accepted-letter-ids.json';a.click();URL.revokeObjectURL(a.href);}</script></body></html>""")
    destination.write_text("\n".join(parts), encoding="utf-8")


def apply_accepted_letters(accepted: dict, proposals: list[dict], store, archive: Path) -> dict:
    from .provenance import build_glyph_id, checked_box, validate_source

    if not isinstance(accepted, dict):
        raise ValueError("Accepted letter file must map source IDs to glyph ID lists.")
    by_source = {proposal["source_id"]: proposal for proposal in proposals}
    pending, counts = [], {}
    for source_id, letter_ids in accepted.items():
        if not isinstance(letter_ids, list) or any(not isinstance(ident, str) for ident in letter_ids):
            raise ValueError("Each accepted source must contain a list of letter IDs.")
        if len(set(letter_ids)) != len(letter_ids):
            raise ValueError("Accepted letter IDs must be unique.")
        source = store.get(source_id)
        proposal = by_source.get(source_id)
        if not source or not proposal or not source.get("reviewed"):
            raise ValueError("An accepted letter's source is missing or unreviewed.")
        if sha256(source["ocr_text"].encode()).hexdigest() != proposal.get("transcription_sha256"):
            raise ValueError("Source transcription changed; regenerate letter proposals.")
        metadata = image_metadata(archive / Path(source["image_url"]).name)
        if source["image_url"] != proposal.get("image_url") or any(metadata[key] != proposal.get(key) for key in metadata):
            raise ValueError("Source image changed; regenerate letter proposals.")
        candidates = {letter["id"]: letter for letter in proposal["letter_crops"]}
        existing = source.get("letter_crops", []) if source.get("image_sha256") == metadata["image_sha256"] else []
        merged = {letter["id"]: letter for letter in existing}
        for ident in letter_ids:
            letter = candidates.get(ident)
            if not letter or letter.get("source_id") != source_id:
                raise ValueError("An accepted letter ID is not a proposed source glyph.")
            character = letter.get("text")
            if not isinstance(character, str) or len(character) != 1 or not character.isprintable() or character.isspace():
                raise ValueError("An accepted glyph must be one visible character.")
            checked_box(letter, metadata["image_width"], metadata["image_height"])
            parent = letter.get("parent_word_id")
            if parent is not None and parent not in {crop["word_id"] for crop in source.get("word_crops", [])}:
                raise ValueError("An accepted letter's parent word crop changed; regenerate proposals.")
            expected = build_glyph_id(source_id, metadata["image_sha256"], letter["text"], letter)
            if ident != expected:
                raise ValueError("Letter coordinates or text changed since extraction.")
            merged[ident] = letter
        if letter_ids:
            source.update(metadata)
            source["letter_crops"] = list(merged.values())
            source["letter_review_method"] = "visual_inspection"
            source["letter_reviewed_at"] = datetime.now(timezone.utc).isoformat()
            pending.append(validate_source(source))
            counts[source_id] = len(letter_ids)
    for source in pending:
        store.upsert(source)
    return counts
