#!/usr/bin/env python3
"""Append a bounded set of verified Municipal Archives catalog items to a manifest.

This downloads catalog metadata only. The ingestion and visual-review steps stay
separate, so discovery never turns a photograph into trusted lettering.
"""

from datetime import datetime, timezone
import argparse
from html import unescape
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cutup.store import atomic_json
from scripts.ingest import ARCHIVE_HOST, IO_PATTERN, load_manifest

BASE = "https://" + ARCHIVE_HOST


def catalog_url(value: str) -> str:
    parsed = urlsplit(value)
    query = parse_qs(parsed.query)
    if (parsed.scheme != "https" or parsed.netloc != ARCHIVE_HOST or parsed.fragment
            or not re.fullmatch(r"/uncategorized/SO_[0-9a-f-]{36}/", parsed.path)
            or set(query) - {"pg"}
            or any(len(values) != 1 or not values[0].isdigit() for values in query.values())):
        raise argparse.ArgumentTypeError("Use a Municipal Archives collection URL, optionally with ?pg=N.")
    return value


def fetch(url: str) -> str:
    # curl handles the catalog's public HTTPS endpoint consistently on macOS.
    result = subprocess.run(
        ["curl", "--fail", "--silent", "--show-error", "--max-time", "30",
         "--max-filesize", "2500000", "--user-agent", "Mozilla/5.0 (NYC-Cut-Up-Machine; catalog research)", url],
        capture_output=True, text=True, timeout=35, check=True,
    )
    return result.stdout


def item_metadata(identifier: str, page: str) -> dict:
    fields = {}
    for key, value in re.findall(
        r'<span class="metadata-title">(.*?)</span>.*?<span class="metadata-content">(.*?)</span>', page, re.S,
    ):
        clean = lambda text: unescape(re.sub(r"<[^>]+>", "", text)).strip()
        fields.setdefault(clean(key), clean(value))
    if not IO_PATTERN.fullmatch(identifier) or not fields.get("Identifier", "").startswith("nynyma_rec0040_"):
        raise ValueError("Item is not a verified 1940s tax photograph.")
    if any(not fields.get(key) for key in ("Title", "Borough", "Block", "Lot")):
        raise ValueError("Item has incomplete location metadata.")
    if fields["Title"].casefold() == "outtake":
        raise ValueError("Skipping photographic outtake.")
    return {
        "id": identifier, "identifier": fields["Identifier"], "title": fields["Title"],
        "borough": fields["Borough"], "block": fields["Block"], "lot": fields["Lot"],
        "start_date": fields.get("Start Date", ""), "end_date": fields.get("End Date", ""),
        "source_url": f"{BASE}/uncategorized/{identifier}/",
        "download_url": f"{BASE}/download/file/{identifier}",
        "attribution": f"{fields['Title']}, 1940s Tax Department photographs, Courtesy of the Municipal Archives, City of New York.",
        "rights_statement": fields.get("Rights", ""),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-url", type=catalog_url, required=True)
    parser.add_argument("--manifest", type=Path, default=ROOT / "data" / "seeds.json")
    parser.add_argument("--limit", type=int, default=12, help="At most 24 new items from one catalog page.")
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 24:
        parser.error("--limit must be between 1 and 24")
    existing = load_manifest(args.manifest)
    payload = json.loads(args.manifest.read_text())
    seen = {source["id"] for source in existing}
    page = fetch(args.catalog_url)
    identifiers = list(dict.fromkeys(re.findall(r"/uncategorized/(IO_[0-9a-f-]{36})/", page)))
    added = 0
    for identifier in identifiers:
        if identifier in seen or added >= args.limit:
            continue
        time.sleep(1)
        try:
            source = item_metadata(identifier, fetch(f"{BASE}/uncategorized/{identifier}/"))
        except (ValueError, subprocess.SubprocessError) as error:
            print(f"Skipped {identifier}: {type(error).__name__}", file=sys.stderr)
            continue
        source["discovered_from"] = args.catalog_url
        payload["sources"].append(source)
        seen.add(identifier)
        added += 1
        print(f"Added catalog metadata: {source['title']}", flush=True)
    payload["metadata_verified_at"] = datetime.now(timezone.utc).date().isoformat()
    atomic_json(args.manifest, payload)
    load_manifest(args.manifest)
    print(f"Added {added} catalog records; no photographs downloaded or approved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
