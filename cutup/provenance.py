"""Resolve selected vocabulary to IDs; trusted code renders the original words."""

from hashlib import sha256
import math
from pathlib import Path
import re

WORD = re.compile(r"[^\W_]+(?:['’\-][^\W_]+)*", re.UNICODE)


class ProvenanceError(ValueError):
    pass


def build_words(source_id: str, ocr_text: str) -> list[dict]:
    version = sha256(ocr_text.encode("utf-8")).hexdigest()[:10]
    return [
        {"id": f"{source_id}:{version}:{i}", "text": match.group(), "source_id": source_id,
         "start": match.start(), "end": match.end()}
        for i, match in enumerate(WORD.finditer(ocr_text))
    ]


def validate_source(source: dict) -> dict:
    """Rebuild tokens so callers cannot invent words in a stored words array."""
    if not isinstance(source, dict) or not isinstance(source.get("id"), str):
        raise ProvenanceError("A source needs an identifier.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", source["id"]):
        raise ProvenanceError("Invalid source identifier.")
    if not isinstance(source.get("ocr_text"), str) or len(source["ocr_text"]) > 50000:
        raise ProvenanceError("A source needs OCR text of at most 50,000 characters.")
    if not isinstance(source.get("reviewed", False), bool):
        raise ProvenanceError("Reviewed must be a boolean.")
    result = dict(source)
    result["words"] = build_words(source["id"], source["ocr_text"])
    result["reviewed"] = source.get("reviewed", False)
    crops = source.get("word_crops", [])
    if not isinstance(crops, list):
        raise ProvenanceError("Word crops must be a list.")
    if crops:
        width, height = source.get("image_width"), source.get("image_height")
        if (type(width) is not int or type(height) is not int or width <= 0 or height <= 0
                or width * height > 50_000_000):
            raise ProvenanceError("Crops require valid source image dimensions.")
        if not re.fullmatch(r"[a-f0-9]{64}", str(source.get("image_sha256", ""))):
            raise ProvenanceError("Crops require a source image SHA-256 digest.")
    words = {word["id"]: word for word in result["words"]}
    accepted = []
    seen = set()
    for crop in crops:
        if not isinstance(crop, dict) or not isinstance(crop.get("word_id"), str):
            raise ProvenanceError("Each crop needs a word identifier.")
        word = words.get(crop["word_id"])
        # Editing transcription changes every token ID; old locations cannot survive.
        if word is None:
            continue
        if word["id"] in seen or crop.get("text") != word["text"]:
            raise ProvenanceError("Duplicate or mismatched crop word.")
        seen.add(word["id"])
        if any(type(crop.get(key)) is not int for key in ("x", "y", "width", "height")):
            raise ProvenanceError("Crop coordinates must be integer pixels.")
        x, y, w, h = (crop[key] for key in ("x", "y", "width", "height"))
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
            raise ProvenanceError("Crop lies outside the source photograph.")
        confidence = crop.get("confidence")
        if (type(confidence) not in (int, float) or not math.isfinite(confidence)
                or not 0 <= confidence <= 100):
            raise ProvenanceError("Crop confidence must be a finite number from 0 to 100.")
        if not isinstance(crop.get("method"), str) or not 1 <= len(crop["method"]) <= 80:
            raise ProvenanceError("Crop localization method is required.")
        location = {key: crop[key] for key in ("x", "y", "width", "height", "method", "confidence")}
        word["crop"] = location
        accepted.append({"word_id": word["id"], "text": word["text"], **location})
    result["word_crops"] = accepted
    return result


def verify_crop_images(sources: list[dict], data_dir: Path) -> None:
    """Bind all selected coordinates to the exact local archival image bytes."""
    archive = (data_dir / "archive").resolve()
    for source in sources:
        if not source.get("word_crops"):
            continue
        url = source.get("image_url", "")
        if not isinstance(url, str) or not url.startswith("/archive/"):
            raise ProvenanceError("Cropped words require a local archive photograph.")
        file = (archive / url.removeprefix("/archive/")).resolve()
        if (file.parent != archive or file.suffix.lower() not in {".jpg", ".jpeg", ".png"}
                or not file.is_file()):
            raise ProvenanceError("The source photograph is missing. Download it before composing.")
        if sha256(file.read_bytes()).hexdigest() != source.get("image_sha256"):
            raise ProvenanceError("The source photograph changed. Localize its words again before composing.")


def resolve_lines(payload: dict, sources: list[dict], *, require_reviewed: bool = True,
                  require_crops: bool = False) -> list[list[dict]]:
    if not isinstance(payload, dict) or set(payload) != {"lines"}:
        raise ProvenanceError("Composition must contain only a lines field.")
    lines = payload["lines"]
    if not isinstance(lines, list) or not 1 <= len(lines) <= 12:
        raise ProvenanceError("A composition must contain 1–12 lines.")
    vocabulary = {}
    for source in sources:
        checked = validate_source(source)
        if require_reviewed and not checked["reviewed"]:
            continue
        for word in checked["words"]:
            if require_crops and "crop" not in word:
                continue
            if word["id"] in vocabulary:
                raise ProvenanceError("Duplicate source word identifier.")
            vocabulary[word["id"]] = word
    output = []
    count = 0
    for line in lines:
        if not isinstance(line, list) or not 1 <= len(line) <= 20:
            raise ProvenanceError("Each line must contain 1–20 word IDs.")
        resolved = []
        for word_id in line:
            if not isinstance(word_id, str) or word_id not in vocabulary:
                raise ProvenanceError("The model selected a word outside the retrieved vocabulary.")
            resolved.append(dict(vocabulary[word_id]))
            count += 1
        output.append(resolved)
    if count > 100:
        raise ProvenanceError("A composition may contain at most 100 words.")
    return output


def plain_text(lines: list[list[dict]]) -> str:
    return "\n".join(" ".join(token["text"] for token in line) for line in lines)
