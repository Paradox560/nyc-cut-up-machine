#!/usr/bin/env python3
"""Create exact-match pixel-crop proposals for visual review; no corpus writes."""

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
from cutup.localize import apply_accepted, localize_source, render_contact_sheet
from cutup.store import CorpusStore


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", default=[], help="Limit to a full source ID; repeatable.")
    parser.add_argument("--min-confidence", type=float, default=60)
    parser.add_argument("--psm", type=int, action="append", choices=(3, 6, 11, 12), default=None)
    parser.add_argument("--tesseract", default=None, help="Optional path to the Tesseract executable.")
    parser.add_argument("--accept", type=Path, help="Apply only visually checked IDs from the review sheet's JSON download.")
    args = parser.parse_args(argv)
    if not 0 <= args.min_confidence <= 100:
        parser.error("--min-confidence must be between 0 and 100")
    try:
        config = load_config()
        archive = Path(config.data_dir) / "archive"
        output = archive / "localization"
        output.mkdir(parents=True, exist_ok=True)
        store = CorpusStore(config.data_dir)
        if args.accept:
            accepted = json.loads(args.accept.read_text(encoding="utf-8"))
            proposals = json.loads((output / "proposals.json").read_text(encoding="utf-8"))
            counts = apply_accepted(accepted, proposals, store, archive)
            print(f"Applied {sum(counts.values())} visually accepted crops across {len(counts)} sources.")
            print("Elasticsearch was not changed; reindex reviewed sources separately.")
            return 0
        sources = [source for source in store.all() if source.get("reviewed")]
        if args.source:
            known = {source["id"] for source in sources}
            if set(args.source) - known:
                raise ValueError("A requested source does not exist or is not reviewed.")
            sources = [source for source in sources if source["id"] in args.source]
        if not sources:
            raise ValueError("No reviewed source transcriptions are available.")
        proposals = []
        for source in sources:
            image_name = Path(source["image_url"]).name
            proposal = localize_source(source, archive / image_name, output,
                                       psms=args.psm or (11, 3), min_confidence=args.min_confidence,
                                       executable=args.tesseract)
            proposals.append(proposal)
            print(f"{source['title']}: {len(proposal['word_crops'])}/{len(source['words'])} words located", flush=True)
            (output / "proposals.json").write_text(json.dumps(proposals, indent=2) + "\n", encoding="utf-8")
            render_contact_sheet(proposals, output / "review.html")
        print(f"Review sheet: {output / 'review.html'}", flush=True)
        print("Only proposals were written. Visually accept real crops before updating the corpus.", flush=True)
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"Localization failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
