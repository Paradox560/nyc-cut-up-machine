"""Resolve selected vocabulary to IDs; trusted code renders the original words."""

from copy import deepcopy
from hashlib import sha256
import math
import json
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


def build_glyph_id(source_id: str, image_sha256: str, text: str, box: dict) -> str:
    evidence = [image_sha256, text, [box[key] for key in ("x", "y", "width", "height")]]
    digest = sha256(json.dumps(evidence, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()[:20]
    return f"{source_id}:g:{digest}"


def checked_box(box: dict, width: int, height: int) -> dict:
    if any(type(box.get(key)) is not int for key in ("x", "y", "width", "height")):
        raise ProvenanceError("Crop coordinates must be integer pixels.")
    x, y, w, h = (box[key] for key in ("x", "y", "width", "height"))
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
        raise ProvenanceError("Crop lies outside the source photograph.")
    confidence = box.get("confidence")
    if (type(confidence) not in (int, float) or not 0 <= confidence <= 100
            or not math.isfinite(confidence)):
        raise ProvenanceError("Crop confidence must be a finite number from 0 to 100.")
    if not isinstance(box.get("method"), str) or not 1 <= len(box["method"]) <= 80:
        raise ProvenanceError("Crop localization method is required.")
    return {key: box[key] for key in ("x", "y", "width", "height", "method", "confidence")}


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
    glyphs = source.get("letter_crops", [])
    if not isinstance(crops, list) or not isinstance(glyphs, list):
        raise ProvenanceError("Word and letter crops must be lists.")
    if crops or glyphs:
        width, height = source.get("image_width"), source.get("image_height")
        if (type(width) is not int or type(height) is not int or width <= 0 or height <= 0
                or width * height > 50_000_000):
            raise ProvenanceError("Crops require valid source image dimensions.")
        digest = source.get("image_sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
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
        location = checked_box(crop, width, height)
        word["crop"] = location
        accepted.append({"word_id": word["id"], "text": word["text"], **location})
    result["word_crops"] = accepted
    accepted_glyphs, letters, seen_glyphs = [], [], set()
    for glyph in glyphs:
        if not isinstance(glyph, dict):
            raise ProvenanceError("Each letter crop must be an object.")
        character = glyph.get("text")
        if (not isinstance(character, str) or len(character) != 1
                or not character.isprintable() or character.isspace()):
            raise ProvenanceError("A letter crop must contain one visible character.")
        location = checked_box(glyph, width, height)
        identifier = build_glyph_id(source["id"], source["image_sha256"], character, location)
        if glyph.get("id") != identifier or glyph.get("source_id") != source["id"]:
            raise ProvenanceError("Letter identity does not match its photo, character, and coordinates.")
        if identifier in seen_glyphs:
            raise ProvenanceError("Duplicate letter crop identifier.")
        seen_glyphs.add(identifier)
        parent = glyph.get("parent_word_id")
        if parent is not None:
            word = words.get(parent) if isinstance(parent, str) else None
            if word is None or "crop" not in word:
                continue
            box = word["crop"]
            if (location["x"] < box["x"] or location["y"] < box["y"]
                    or location["x"] + location["width"] > box["x"] + box["width"]
                    or location["y"] + location["height"] > box["y"] + box["height"]):
                raise ProvenanceError("Letter lies outside its parent word crop.")
        item = {"id": identifier, "text": character, "source_id": source["id"]}
        if parent is not None:
            item["parent_word_id"] = parent
        accepted_glyphs.append({**item, **location})
        letters.append({**item, "crop": location})
    result["letter_crops"] = accepted_glyphs
    result["letters"] = letters
    return result


def verify_crop_images(sources: list[dict], data_dir: Path) -> None:
    """Bind all selected coordinates to the exact local archival image bytes."""
    archive = (data_dir / "archive").resolve()
    for source in sources:
        if not source.get("word_crops") and not source.get("letter_crops"):
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


def validate_assembled_lines(lines: list[list[dict]], sources: list[dict], *,
                             require_reviewed: bool = True) -> list[list[dict]]:
    """Recheck every physical cutout against canonical source evidence.

    Whole words retain the ordinary cropped-word checks. An assembled word must
    explicitly identify itself and carry one registered photo glyph per letter;
    neither its requested spelling nor a caller-supplied crop is evidence.
    Call verify_crop_images separately to bind the sources to local image bytes.
    """
    words, letters, source_ids = {}, {}, set()
    for raw in sources:
        source = validate_source(raw)
        if source["id"] in source_ids:
            raise ProvenanceError("Duplicate source identifier.")
        source_ids.add(source["id"])
        if source.get("synthetic") or (require_reviewed and not source["reviewed"]):
            continue
        words.update((word["id"], word) for word in source["words"] if word.get("crop"))
        letters.update((letter["id"], letter) for letter in source["letters"])

    def physical_cutout(piece, vocabulary, *, letter=False):
        if not isinstance(piece, dict) or not isinstance(piece.get("id"), str):
            raise ProvenanceError("Each cutout needs a registered source identifier.")
        expected = vocabulary.get(piece["id"])
        if expected is None:
            raise ProvenanceError("A cutout is outside the retrieved photo vocabulary.")
        crop = piece.get("crop")
        if not isinstance(crop, dict) or any(type(crop.get(key)) is not int
                                             for key in ("x", "y", "width", "height")):
            raise ProvenanceError("Each cutout needs its original integer-pixel crop.")
        fields = ("id", "text", "source_id", "crop", "parent_word_id") if letter else (
            "id", "text", "source_id", "crop", "start", "end")
        if any(piece.get(field) != expected.get(field) for field in fields):
            raise ProvenanceError("A cutout does not match its source photo and crop.")
        if "pieces" in piece or "kind" in piece:
            raise ProvenanceError("Physical cutouts cannot contain assembled lettering.")
        return deepcopy(expected)

    if not isinstance(lines, list) or not lines:
        raise ProvenanceError("A composition needs an array of lines.")
    checked_lines, count = [], 0
    for row in lines:
        if not isinstance(row, list):
            raise ProvenanceError("Each composition line must be an array.")
        checked_row = []
        for token in row:
            if not isinstance(token, dict):
                raise ProvenanceError("Each output word needs source evidence.")
            if token.get("kind") == "assembled":
                text, cutouts = token.get("text"), token.get("pieces")
                if (not isinstance(text, str) or not text or any(char.isspace() for char in text)
                        or not isinstance(cutouts, list) or len(cutouts) != len(text)):
                    raise ProvenanceError("An assembled word needs one source glyph per character.")
                checked_pieces = [physical_cutout(piece, letters, letter=True) for piece in cutouts]
                if any(character.casefold() != piece["text"].casefold()
                       for character, piece in zip(text, checked_pieces)):
                    raise ProvenanceError("An assembled word does not match its photographed letters.")
                if "requested_text" in token or "crop" in token or "source_id" in token:
                    raise ProvenanceError("An assembled word must keep its evidence on each letter.")
                checked_token = {"text": text, "kind": "assembled", "pieces": checked_pieces}
            else:
                checked_token = physical_cutout(token, words)
                if "requested_text" in token:
                    requested = token["requested_text"]
                    if not isinstance(requested, str) or requested.casefold() != checked_token["text"].casefold():
                        raise ProvenanceError("Requested text cannot replace a photographed word.")
                    checked_token["requested_text"] = requested
            if "prefix" in token:
                prefix = token["prefix"]
                if not isinstance(prefix, str) or any(character not in " \t" for character in prefix):
                    raise ProvenanceError("Word prefixes may contain only spaces and tabs.")
                checked_token["prefix"] = prefix
            checked_row.append(checked_token)
            count += 1
        checked_lines.append(checked_row)
    if not count:
        raise ProvenanceError("A composition needs at least one sourced word.")
    return checked_lines


def plain_text(lines: list[list[dict]]) -> str:
    return "\n".join("".join(token.get("prefix", " " if index else "")
        + token.get("requested_text", token["text"]) for index, token in enumerate(line)) for line in lines)
