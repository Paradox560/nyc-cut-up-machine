#!/usr/bin/env python3
"""Prepare only reviewed archive evidence and public assets for Vercel.

Run locally before deployment to seed deployment_data. Vercel can then run the
same command using that prepared bundle, without raw data or credentials.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cutup.provenance import validate_source, verify_crop_images


SOURCE_FIELDS = {
    "id", "title", "borough", "block", "lot", "source_url", "download_url",
    "attribution", "rights_statement", "image_url", "image_width", "image_height",
    "image_sha256", "ocr_text", "reviewed", "reviewed_at", "review_method",
    "transcription_method", "transcription_model", "ocr_model", "word_crops",
    "letter_crops", "crop_review_method", "crop_reviewed_at", "letter_review_method",
    "letter_reviewed_at",
}
WEB_EXTENSIONS = {".html", ".css", ".js", ".svg", ".png", ".woff2", ".txt"}


def prepare(root: Path = ROOT, *, from_local: bool = False) -> dict:
    root = root.resolve()
    bundle = root / "deployment_data"
    source_dir = root / "data" if from_local or not (bundle / "corpus.json").is_file() else bundle
    corpus_file = source_dir / "corpus.json"
    if not corpus_file.is_file():
        raise ValueError("No reviewed corpus found. Prepare the deployment locally before uploading.")
    raw = json.loads(corpus_file.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("The corpus must be an array of source records.")
    sources, images, seen = [], {}, set()
    for item in raw:
        if not item.get("reviewed") or item.get("synthetic") or not item.get("ocr_text", "").strip():
            continue
        source = validate_source({key: value for key, value in item.items() if key in SOURCE_FIELDS})
        if source["id"] in seen:
            raise ValueError("The deployment corpus contains duplicate source IDs.")
        seen.add(source["id"])
        url = source.get("image_url", "")
        name = url.removeprefix("/archive/")
        archive = (source_dir / "archive").resolve()
        image = (archive / name).resolve()
        if not url.startswith("/archive/") or image.parent != archive or image.suffix.lower() not in {".jpg", ".jpeg", ".png"} or not image.is_file():
            raise ValueError(f"Missing or unsafe archive image for {source['id']}.")
        images[image.name] = image
        sources.append(source)
    if not sources:
        raise ValueError("No reviewed, nonempty archival sources are available.")
    verify_crop_images(sources, source_dir)
    # Source data is read-only. Only the explicitly generated bundle is written.
    target_archive = bundle / "archive"
    target_archive.mkdir(parents=True, exist_ok=True)
    for name, image in images.items():
        target = target_archive / name
        if image.resolve() != target.resolve():
            shutil.copyfile(image, target)
    for old in target_archive.iterdir():
        if old.is_file() and old.name not in images:
            old.unlink()
    (bundle / "corpus.json").write_text(json.dumps(sources, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    public = root / "public"
    public.mkdir(exist_ok=True)
    for asset in (root / "web").rglob("*"):
        if asset.is_file() and asset.suffix.lower() in WEB_EXTENSIONS:
            target = public / asset.relative_to(root / "web")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(asset, target)
    public_archive = public / "archive"
    public_archive.mkdir(exist_ok=True)
    for name in images:
        shutil.copyfile(target_archive / name, public_archive / name)
    for old in public_archive.iterdir():
        if old.is_file() and old.name not in images:
            old.unlink()
    return {"sources": len(sources), "images": len(images),
            "image_bytes": sum((target_archive / name).stat().st_size for name in images),
            "word_crops": sum(len(s["word_crops"]) for s in sources),
            "letter_crops": sum(len(s["letter_crops"]) for s in sources)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-local", action="store_true", help="Refresh deployment_data from the local reviewed corpus.")
    args = parser.parse_args()
    try:
        result = prepare(from_local=args.from_local)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Deployment preparation failed: {exc}\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
