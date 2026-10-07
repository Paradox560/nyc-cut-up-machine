"""Spell exact messages using reviewed word and character photograph cutouts."""

from copy import deepcopy
import re

from .provenance import ProvenanceError, validate_assembled_lines, validate_source

SEGMENTS = re.compile(r"\s+|[^\W_]+(?:['’\-][^\W_]+)*|[^\w\s]|_", re.UNICODE)
MAX_MESSAGE = 300


def pieces(token: dict) -> list[dict]:
    return token["pieces"] if token.get("kind") == "assembled" else [token]


def source_bank(sources: list[dict], *, require_reviewed=True) -> tuple[dict, dict]:
    words, letters, source_ids = {}, {}, set()
    for raw in sources:
        source = validate_source(raw)
        if source["id"] in source_ids:
            raise ProvenanceError("Duplicate source identifier.")
        source_ids.add(source["id"])
        if source.get("synthetic") or (require_reviewed and not source["reviewed"]):
            continue
        for word in source["words"]:
            if word.get("crop"):
                words.setdefault(word["text"].casefold(), []).append(word)
        for glyph in source["letters"]:
            letters.setdefault(glyph["text"].casefold(), []).append(glyph)
    return words, letters


def choose(candidates: list[dict], text: str) -> dict:
    exact = [item for item in candidates if item["text"] == text]
    # Larger original glyphs survive enlargement better; stable ties retain search rank.
    return deepcopy(max(exact or candidates, key=lambda item: item["crop"]["height"]))


def assemble_text(text: str, sources: list[dict], *, require_reviewed=True) -> list[list[dict]]:
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_MESSAGE:
        raise ProvenanceError(f"Enter a custom message of 1–{MAX_MESSAGE} characters.")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if any(not char.isprintable() and char not in "\n\t" for char in normalized):
        raise ProvenanceError("Messages may contain visible characters, spaces, tabs, and line breaks.")
    raw_lines = normalized.split("\n")
    if len(raw_lines) > 20:
        raise ProvenanceError("Use at most 20 lines in a custom message.")
    words, letters = source_bank(sources, require_reviewed=require_reviewed)
    missing, output = set(), []
    for line in raw_lines:
        row, prefix = [], ""
        for match in SEGMENTS.finditer(line):
            segment = match.group()
            if segment.isspace():
                prefix += segment
                continue
            matches = words.get(segment.casefold())
            if matches:
                token = choose(matches, segment)
                token["requested_text"] = segment
            else:
                cutouts = []
                for character in segment:
                    choices = letters.get(character.casefold())
                    if not choices:
                        missing.add(character)
                    else:
                        cutouts.append(choose(choices, character))
                token = {"text": segment, "kind": "assembled", "pieces": cutouts}
            token["prefix"] = prefix
            row.append(token)
            prefix = ""
        output.append(row)
    if missing:
        characters = ", ".join(repr(character) for character in sorted(missing))
        raise ProvenanceError(f"No reviewed photo cutout is available for: {characters}. Change those characters or add and review more letter crops.")
    return validate_assembled_lines(output, sources, require_reviewed=require_reviewed)


def assemble_model_lines(payload: dict, sources: list[dict], *, require_reviewed=True) -> list[list[dict]]:
    if not isinstance(payload, dict) or set(payload) != {"lines"}:
        raise ProvenanceError("Composition must contain only a lines field.")
    lines = payload["lines"]
    if not isinstance(lines, list) or not 1 <= len(lines) <= 12:
        raise ProvenanceError("A composition must contain 1–12 lines.")
    for row in lines:
        if not isinstance(row, list) or not 1 <= len(row) <= 20:
            raise ProvenanceError("Each generated line must contain 1–20 words.")
        if any(not isinstance(word, str) or not word or any(char.isspace() for char in word) for word in row):
            raise ProvenanceError("Each generated selection must be a single word or punctuation mark.")
    return assemble_text("\n".join(" ".join(row) for row in lines), sources,
                         require_reviewed=require_reviewed)
