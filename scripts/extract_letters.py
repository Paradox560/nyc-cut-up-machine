#!/usr/bin/env python3
"""Extract actual glyph boxes and generate an atlas for explicit visual review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cutup.config import load_config
from cutup.glyphs import TARGETS, apply_accepted_letters, extract_source_letters, render_letter_atlas
from cutup.store import CorpusStore


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--accept", type=Path, help="Apply only visually checked glyph IDs downloaded from the atlas.")
    parser.add_argument("--tesseract", default=None)
    parser.add_argument("--sips", default=None)
    args = parser.parse_args(argv)
    try:
        config = load_config()
        archive = Path(config.data_dir) / "archive"
        output = archive / "letters"
        output.mkdir(parents=True, exist_ok=True)
        store = CorpusStore(config.data_dir)
        if args.accept:
            counts = apply_accepted_letters(json.loads(args.accept.read_text()),
                                            json.loads((output / "proposals.json").read_text()), store, archive)
            print(f"Applied {sum(counts.values())} visually accepted letters across {len(counts)} sources.")
            print("Elasticsearch was not changed; reindex sources separately.")
            return 0
        sources = [source for source in store.all() if source.get("reviewed") and source.get("word_crops")]
        if args.source:
            if set(args.source) - {source["id"] for source in sources}:
                raise ValueError("A requested source lacks reviewed word crops.")
            sources = [source for source in sources if source["id"] in args.source]
        if not sources:
            raise ValueError("Approve source word crops before extracting their letters.")
        existing_path = output / "proposals.json"
        previous = {proposal["source_id"]: proposal for proposal in json.loads(existing_path.read_text())} if existing_path.exists() else {}
        proposals = []
        for source in sources:
            proposal = extract_source_letters(source, archive / Path(source["image_url"]).name, output,
                                              tesseract=args.tesseract, sips=args.sips)
            earlier = previous.get(source["id"])
            if earlier and all(earlier.get(key) == proposal.get(key) for key in ("image_sha256", "transcription_sha256")):
                combined = {letter["id"]: letter for letter in proposal["letter_crops"]}
                combined.update({letter["id"]: letter for letter in earlier.get("letter_crops", []) if letter.get("method") == "manual"})
                proposal["letter_crops"] = list(combined.values())
            proposals.append(proposal)
            (output / "proposals.json").write_text(json.dumps(proposals, indent=2) + "\n", encoding="utf-8")
            render_letter_atlas(proposals, output / "atlas.html")
            print(f"{source['title']}: {len(proposal['letter_crops'])} glyphs from {proposal['matched_word_count']} exactly recognized words.", flush=True)
        present = {letter["text"].upper() for proposal in proposals for letter in proposal["letter_crops"]}
        print("Available: " + " ".join(character for character in TARGETS if character in present))
        print("Missing: " + " ".join(character for character in TARGETS if character not in present))
        print(f"Review atlas: {output / 'atlas.html'}")
        print("Only proposals were written. Review and accept real letters before composition.")
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"Letter extraction failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
