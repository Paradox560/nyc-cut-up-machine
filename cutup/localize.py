"""Propose image-space word boxes from local Tesseract output.

These candidates require visual inspection before being put into the corpus.
Matching is exact after case and outside-punctuation normalization; geometric
guesses and fuzzy spelling matches are intentionally not used.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from hashlib import sha256
from html import escape
import io
import math
from pathlib import Path
import shutil
import subprocess
import unicodedata

from .provenance import build_words, validate_source


def normalized_word(text: str) -> str:
    text = unicodedata.normalize("NFC", text).replace("’", "'").casefold().strip()
    # Tesseract may include adjacent punctuation, but never strip word-internal
    # punctuation or split one OCR box into several invented word boxes.
    while text and not text[0].isalnum():
        text = text[1:]
    while text and not text[-1].isalnum():
        text = text[:-1]
    return text


def image_metadata(path: Path) -> dict:
    from scripts.ingest import _jpeg_dimensions, _png_dimensions, validate_image

    data = path.read_bytes()
    extension = validate_image(data)
    width, height = _jpeg_dimensions(data) if extension == ".jpg" else _png_dimensions(data)
    return {"image_width": width, "image_height": height, "image_sha256": sha256(data).hexdigest()}


def parse_tsv(text: str, width: int, height: int, *, min_confidence: float = 60, psm: int = 11) -> list[dict]:
    candidates = []
    reader = csv.DictReader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE)
    required = {"level", "left", "top", "width", "height", "conf", "text"}
    if not required.issubset(reader.fieldnames or []):
        raise ValueError("Tesseract returned an incomplete TSV header.")
    for row in reader:
        try:
            if int(row["level"]) != 5:
                continue
            confidence = float(row["conf"])
            x, y = int(row["left"]), int(row["top"])
            box_width, box_height = int(row["width"]), int(row["height"])
            token = (row["text"] or "").strip()
        except (ValueError, TypeError, KeyError):
            continue
        if not min_confidence <= confidence <= 100 or not normalized_word(token):
            continue
        if x < 0 or y < 0 or box_width <= 0 or box_height <= 0 or x + box_width > width or y + box_height > height:
            continue
        candidates.append({"text": token, "x": x, "y": y, "width": box_width, "height": box_height,
                           "confidence": round(confidence, 2), "method": "tesseract", "psm": psm})
    return candidates


def match_words(source: dict, candidates: list[dict]) -> list[dict]:
    """Use a real candidate box for each exactly matching transcribed token."""
    vocabulary = {}
    for candidate in sorted(candidates, key=lambda candidate: candidate["confidence"], reverse=True):
        key = normalized_word(candidate["text"])
        vocabulary.setdefault(key, []).append(candidate)
    boxes, used = [], set()
    for word in build_words(source["id"], source["ocr_text"]):
        matches = vocabulary.get(normalized_word(word["text"]), [])
        if not matches:
            continue
        # Repeated words can use repeated signs when available. Reusing the same
        # real crop is allowed when the transcription repeats identical text.
        chosen = next((candidate for candidate in matches if (
            candidate["x"], candidate["y"], candidate["width"], candidate["height"]
        ) not in used), matches[0])
        used.add((chosen["x"], chosen["y"], chosen["width"], chosen["height"]))
        boxes.append({**chosen, "word_id": word["id"], "text": word["text"]})
    return boxes


def localize_source(source: dict, image_path: Path, output_dir: Path, *, psms=(11, 3),
                    min_confidence: float = 60, executable: str | None = None) -> dict:
    executable = executable or shutil.which("tesseract")
    if not executable:
        raise ValueError("Install Tesseract to propose word locations.")
    if not source.get("reviewed"):
        raise ValueError("Review the source transcription before localizing its words.")
    metadata = image_metadata(image_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    candidates = []
    for psm in psms:
        completed = subprocess.run(
            [executable, str(image_path), "stdout", "-l", "eng", "--psm", str(psm), "tsv"],
            capture_output=True, text=True, timeout=60, check=False,
        )
        if completed.returncode:
            raise RuntimeError(f"Tesseract failed for {source['id']} with exit code {completed.returncode}.")
        (output_dir / f"{source['id']}-psm{psm}.tsv").write_text(completed.stdout, encoding="utf-8")
        candidates.extend(parse_tsv(completed.stdout, metadata["image_width"], metadata["image_height"],
                                    min_confidence=min_confidence, psm=psm))
    crops = match_words(source, candidates)
    matched_ids = {crop["word_id"] for crop in crops}
    missing = [word["text"] for word in build_words(source["id"], source["ocr_text"]) if word["id"] not in matched_ids]
    return {"source_id": source["id"], "title": source["title"], "image_url": source["image_url"],
            **metadata, "word_crops": crops, "unmatched_words": missing,
            "status": "pending_visual_review", "min_confidence": min_confidence,
            "transcription_sha256": sha256(source["ocr_text"].encode()).hexdigest()}


def render_contact_sheet(proposals: list[dict], destination: Path) -> None:
    """Render real source pixels inside SVG viewBoxes, never substitute text."""
    parts = ["""<!doctype html><html><head><meta charset="utf-8"><title>Archive crop review</title>
<style>body{font:15px system-ui;margin:32px;background:#f1eadd;color:#20201e}h1{font:40px Georgia}
section{margin:40px 0;break-before:page}.grid{display:grid;grid-template-columns:repeat(5,minmax(150px,1fr));gap:12px}
.card{background:white;border:1px solid #bdb6aa;padding:10px;min-width:0}.card svg{width:100%;height:90px;background:#eee}
.caption{font-weight:700;overflow-wrap:anywhere;margin-top:6px}.meta{font:11px monospace;color:#605b51;overflow-wrap:anywhere}
.warning{background:#ffe5ad;padding:16px}.missing{color:#685e4e}input{margin-right:8px}button{padding:10px;font:inherit}
</style></head><body><h1>Archive crop review</h1><p class="warning">Proposals only. Every tile below is a crop
of the actual source photograph. Check the letters, framing, and source before accepting. No proposals have been
written to the corpus. Uncertain or wrong tiles must remain unchecked.</p>
<button onclick="downloadAccepted()">Download checked crop IDs</button>"""]
    for proposal in proposals:
        ident = escape(proposal["source_id"])
        image_name = Path(proposal["image_url"]).name
        parts.append(f"<section><h2>{escape(proposal['title'])}</h2><p class='meta'>{ident}</p>")
        parts.append(f"<p>{len(proposal['word_crops'])} proposals. Unmatched: <span class='missing'>{escape(', '.join(proposal['unmatched_words']))}</span></p><div class='grid'>")
        for index, crop in enumerate(proposal["word_crops"]):
            x, y = crop["x"], crop["y"]
            width, height = crop["width"], crop["height"]
            clip_id = f"clip-{ident}-{index}"
            word_id = escape(crop["word_id"], quote=True)
            parts.append(f'''<div class="card"><svg viewBox="{x} {y} {width} {height}" role="img" aria-label="Actual archive crop">
<defs><clipPath id="{clip_id}"><rect x="{x}" y="{y}" width="{width}" height="{height}"/></clipPath></defs>
<g clip-path="url(#{clip_id})"><image href="../{escape(image_name, quote=True)}" x="0" y="0" width="{proposal['image_width']}" height="{proposal['image_height']}"/></g></svg>
<div class="caption"><label><input type="checkbox" data-source="{ident}" value="{word_id}">{escape(crop['text'])}</label></div>
<div class="meta">#{index + 1} · {escape(crop['method'])} · confidence {crop['confidence']} · PSM {crop.get('psm', '—')}<br>
{crop['x']},{crop['y']} {crop['width']}×{crop['height']}<br>{word_id}</div></div>''')
        parts.append("</div></section>")
    parts.append("""<script>function downloadAccepted(){const accepted={};for(const box of document.querySelectorAll('input:checked')){
(accepted[box.dataset.source]??=[]).push(box.value);}const blob=new Blob([JSON.stringify(accepted,null,2)],{type:'application/json'});
const link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download='accepted-crop-ids.json';link.click();URL.revokeObjectURL(link.href);}</script></body></html>""")
    destination.write_text("\n".join(parts), encoding="utf-8")


def apply_accepted(accepted: dict, proposals: list[dict], store, archive: Path) -> dict:
    """Apply explicitly accepted candidate IDs after checking current evidence.

    All accepted sources are checked before any write. Existing accepted crops
    are preserved when their image hash still matches. An acceptance file is a
    record of the operator's visual review, not an automated accuracy guarantee.
    """
    if not isinstance(accepted, dict):
        raise ValueError("Accepted crops must map source IDs to lists of word IDs.")
    by_source = {proposal["source_id"]: proposal for proposal in proposals}
    pending, counts = [], {}
    for source_id, word_ids in accepted.items():
        if not isinstance(word_ids, list) or any(not isinstance(word_id, str) for word_id in word_ids):
            raise ValueError("Each accepted source must contain a list of word IDs.")
        if len(set(word_ids)) != len(word_ids):
            raise ValueError("Accepted crop IDs must be unique within a source.")
        if source_id not in by_source:
            raise ValueError("An accepted source has no localization proposal.")
        source = store.get(source_id)
        proposal = by_source[source_id]
        if not source or not source.get("reviewed"):
            raise ValueError("An accepted source is missing or no longer reviewed.")
        current_text_hash = sha256(source["ocr_text"].encode()).hexdigest()
        if current_text_hash != proposal.get("transcription_sha256"):
            raise ValueError("Source transcription changed since localization; regenerate proposals.")
        if source["image_url"] != proposal.get("image_url"):
            raise ValueError("Source image URL changed since localization; regenerate proposals.")
        metadata = image_metadata(archive / Path(source["image_url"]).name)
        if any(metadata[key] != proposal.get(key) for key in ("image_width", "image_height", "image_sha256")):
            raise ValueError("Source image changed since localization; regenerate proposals.")
        words = {word["id"]: word for word in build_words(source_id, source["ocr_text"])}
        candidates = {crop["word_id"]: crop for crop in proposal["word_crops"]}
        existing = source.get("word_crops", []) if source.get("image_sha256") == metadata["image_sha256"] else []
        merged = {crop["word_id"]: crop for crop in existing if crop["word_id"] in words}
        for word_id in word_ids:
            crop = candidates.get(word_id)
            if not crop or word_id not in words or crop.get("text") != words[word_id]["text"]:
                raise ValueError("An accepted crop is missing or does not match the current source word.")
            if any(type(crop.get(key)) is not int for key in ("x", "y", "width", "height")):
                raise ValueError("Crop coordinates must be integer image pixels.")
            if (crop["x"] < 0 or crop["y"] < 0 or crop["width"] <= 0 or crop["height"] <= 0
                    or crop["x"] + crop["width"] > metadata["image_width"]
                    or crop["y"] + crop["height"] > metadata["image_height"]):
                raise ValueError("An accepted crop lies outside its source image.")
            confidence = crop.get("confidence")
            if (not isinstance(confidence, (int, float)) or isinstance(confidence, bool)
                    or not 0 <= confidence <= 100 or not math.isfinite(confidence)):
                raise ValueError("Crop confidence must be a finite number between 0 and 100.")
            if crop.get("method") not in ("tesseract", "manual"):
                raise ValueError("Unknown crop localization method.")
            merged[word_id] = {key: crop[key] for key in (
                "word_id", "text", "x", "y", "width", "height", "method", "confidence")}
        if word_ids:
            source.update(metadata)
            source["word_crops"] = list(merged.values())
            source["crop_review_method"] = "visual_inspection"
            source["crop_reviewed_at"] = datetime.now(timezone.utc).isoformat()
            pending.append(validate_source(source))
            counts[source_id] = len(word_ids)
    for source in pending:
        store.upsert(source)
    return counts
