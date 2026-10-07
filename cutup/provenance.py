"""The model selects IDs; trusted code renders the original words."""

from hashlib import sha256
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
    return result


def resolve_lines(payload: dict, sources: list[dict], *, require_reviewed: bool = True) -> list[list[dict]]:
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
