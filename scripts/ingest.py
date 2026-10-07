#!/usr/bin/env python3
"""Import an explicit Municipal Archives manifest, with OCR review required."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import struct
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import zlib

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

ARCHIVE_HOST = "nycrecords.access.preservica.com"
USER_AGENT = "nyc-cut-up-machine/0.1 (non-commercial hackathon research; curated archive import)"
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 50_000_000
IO_PATTERN = re.compile(r"IO_[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")


def validate_url(url: str) -> str:
    """Keep manifest fetches and redirects on the approved HTTPS archive host."""
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme == "https" and parsed.hostname == ARCHIVE_HOST
            and parsed.port in (None, 443) and not parsed.username
            and not parsed.password and not parsed.query and not parsed.fragment
        )
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError("Archive URLs must use the approved Municipal Archives HTTPS host.")
    return url


class ArchiveRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def load_manifest(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("Manifest must be an object with version 1 and a sources array.")
    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("Manifest sources must be a nonempty array.")
    seen = set()
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("Each manifest source must be an object.")
        ident = source.get("id", "")
        if not isinstance(ident, str) or not IO_PATTERN.fullmatch(ident) or ident in seen:
            raise ValueError("Manifest source IDs must be unique Municipal Archives IO identifiers.")
        seen.add(ident)
        for field in ("title", "borough", "block", "lot", "attribution", "source_url", "download_url"):
            if not isinstance(source.get(field), str) or not source[field].strip():
                raise ValueError(f"Source {ident} needs a nonempty {field} string.")
        validate_url(source["source_url"])
        validate_url(source["download_url"])
        if urlsplit(source["source_url"]).path != f"/uncategorized/{ident}/":
            raise ValueError(f"Source {ident} must link to its archive item page.")
        if urlsplit(source["download_url"]).path != f"/download/file/{ident}":
            raise ValueError(f"Source {ident} must download its own archive image.")
    return sources


def _validate_dimensions(width: int, height: int) -> None:
    if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
        raise ValueError("Image dimensions are empty or exceed the pixel limit.")


def _jpeg_dimensions(data: bytes) -> tuple[int, int]:
    """Check JPEG marker boundaries and find a supported start-of-frame header."""
    if not data.endswith(b"\xff\xd9"):
        raise ValueError("JPEG is truncated (missing end marker).")
    pos = 2
    dimensions = None
    sof_markers = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    while pos < len(data) - 2:
        if data[pos] != 0xFF:
            raise ValueError("Malformed JPEG marker sequence.")
        while pos < len(data) and data[pos] == 0xFF:
            pos += 1
        if pos >= len(data):
            break
        marker = data[pos]
        pos += 1
        if marker == 0xDA:  # Entropy-coded scan; decoding is left to image consumers.
            if dimensions is None or pos + 2 > len(data) - 2:
                raise ValueError("JPEG scan has no frame dimensions.")
            length = int.from_bytes(data[pos:pos + 2], "big")
            if length < 2 or pos + length >= len(data) - 2:
                raise ValueError("JPEG scan is truncated.")
            return dimensions
        if marker in {0xD8, 0xD9, 0x00} or 0xD0 <= marker <= 0xD7:
            raise ValueError("Unexpected JPEG marker.")
        if marker == 0x01:
            continue
        if pos + 2 > len(data):
            break
        length = int.from_bytes(data[pos:pos + 2], "big")
        if length < 2 or pos + length > len(data) - 2:
            raise ValueError("JPEG header is truncated.")
        if marker in sof_markers:
            if length < 8:
                raise ValueError("JPEG frame header is too short.")
            height, width = struct.unpack(">HH", data[pos + 3:pos + 7])
            dimensions = (width, height)
        pos += length
    raise ValueError("JPEG has no complete image scan.")


def _png_dimensions(data: bytes) -> tuple[int, int]:
    pos, dimensions, has_data = 8, None, False
    while pos + 12 <= len(data):
        size = int.from_bytes(data[pos:pos + 4], "big")
        kind = data[pos + 4:pos + 8]
        end = pos + 12 + size
        if end > len(data):
            raise ValueError("PNG chunk is truncated.")
        chunk = data[pos + 8:pos + 8 + size]
        checksum = int.from_bytes(data[pos + 8 + size:end], "big")
        if zlib.crc32(kind + chunk) & 0xFFFFFFFF != checksum:
            raise ValueError("PNG chunk checksum is invalid.")
        if dimensions is None:
            if kind != b"IHDR" or size != 13:
                raise ValueError("PNG must begin with a complete IHDR chunk.")
            dimensions = struct.unpack(">II", chunk[:8])
        elif kind == b"IHDR":
            raise ValueError("PNG has duplicate header chunks.")
        has_data = has_data or (kind == b"IDAT" and size > 0)
        if kind == b"IEND":
            if size != 0 or end != len(data) or not has_data:
                raise ValueError("PNG has no complete image payload.")
            return dimensions
        pos = end
    raise ValueError("PNG is truncated (missing end chunk).")


def validate_image(data: bytes, content_type: str = "") -> str:
    """Validate bounded JPEG/PNG structure and return the file extension.

    Preservica serves JPEGs as application/octet-stream; that generic type is
    accepted only when image signatures and structure also pass validation.
    This is structural validation, not a replacement for a complete decoder.
    """
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Image is empty or exceeds the 20 MiB size limit.")
    if data.startswith(b"\xff\xd8\xff"):
        extension, mime = ".jpg", "image/jpeg"
        dimensions = _jpeg_dimensions(data)
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        extension, mime = ".png", "image/png"
        dimensions = _png_dimensions(data)
    else:
        raise ValueError("Archive response is not a JPEG or PNG image.")
    declared = content_type.split(";", 1)[0].strip().lower()
    if declared not in ("", "application/octet-stream", mime):
        raise ValueError("Image bytes do not match the response MIME type.")
    _validate_dimensions(*dimensions)
    return extension


class ArchiveDownloader:
    def __init__(self, directory: Path, interval: float = 1.0):
        self.directory = directory
        self.interval = max(1.0, interval)
        self.opener = build_opener(ArchiveRedirectHandler())
        self.last_request = None

    def download(self, source: dict) -> Path:
        ident = source["id"]
        if not IO_PATTERN.fullmatch(ident):
            raise ValueError("Invalid archive image ID.")
        url = validate_url(source["download_url"])
        for extension in (".jpg", ".png"):
            cached = self.directory / f"{ident}{extension}"
            if cached.exists():
                if cached.stat().st_size > MAX_IMAGE_BYTES:
                    raise ValueError(f"Cached image {cached.name} exceeds the size limit.")
                if validate_image(cached.read_bytes()) != extension:
                    raise ValueError(f"Cached image {cached.name} has the wrong extension.")
                return cached
        if self.last_request is not None:
            time.sleep(max(0.0, self.interval - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "image/jpeg, image/png"})
        with self.opener.open(request, timeout=45) as response:
            validate_url(response.geturl())
            declared_size = response.headers.get("Content-Length")
            if declared_size and int(declared_size) > MAX_IMAGE_BYTES:
                raise ValueError("Archive image exceeds the 20 MiB size limit.")
            data = response.read(MAX_IMAGE_BYTES + 1)
            extension = validate_image(data, response.headers.get("Content-Type", ""))
        self.directory.mkdir(parents=True, exist_ok=True)
        destination = self.directory / f"{ident}{extension}"
        temporary = destination.with_suffix(destination.suffix + ".part")
        temporary.write_bytes(data)
        temporary.replace(destination)
        return destination


def positive_integer(value: str) -> int:
    try:
        result = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if result <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=PROJECT_ROOT / "data" / "seeds.json")
    parser.add_argument("--limit", type=positive_integer, default=3, help="Maximum number of manifest images (default: 3).")
    parser.add_argument("--download-only", action="store_true", help="Download images without OCR, credentials, or index writes.")
    parser.add_argument("--index", action="store_true", help="Also write sources to the configured Elasticsearch index.")
    parser.add_argument("--refresh-ocr", action="store_true", help="Replace existing OCR; resets human review and incurs OCR usage.")
    parser.add_argument("--transcription-method", choices=("ocr", "vision"), default="ocr",
                        help="Use Mistral OCR (default) or explicitly select vision chat transcription.")
    args = parser.parse_args(argv)
    if args.download_only and (args.index or args.refresh_ocr):
        parser.error("--download-only cannot be combined with --index or --refresh-ocr")
    return args


def make_source(seed: dict, image_path: Path, ocr_text: str) -> dict:
    from cutup.provenance import build_words

    source = {key: seed[key] for key in ("id", "title", "borough", "block", "lot", "source_url", "attribution")}
    source.update({"image_url": f"/archive/{image_path.name}", "ocr_text": ocr_text,
                   "reviewed": False, "words": build_words(seed["id"], ocr_text)})
    return source


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    from cutup.config import load_config

    try:
        config = load_config()
        seeds = load_manifest(args.manifest)[:args.limit]
        downloader = ArchiveDownloader(Path(config.data_dir) / "archive")
        if not args.download_only:
            from cutup.providers import ElasticClient, MistralClient
            from cutup.store import CorpusStore

            if not config.mistral_api_key:
                raise ValueError("Set MISTRAL_API_KEY in .env.local, or use --download-only.")
            if args.index and (not config.elasticsearch_url or not config.elasticsearch_api_key):
                raise ValueError("--index requires ELASTICSEARCH_URL and ELASTICSEARCH_API_KEY in .env.local.")
            mistral = MistralClient(config)
            store = CorpusStore(config.data_dir)
            elastic = ElasticClient(config) if args.index else None
        for seed in seeds:
            image_path = downloader.download(seed)
            if args.download_only:
                print(f"Downloaded/cached: {seed['title']} → {image_path.name}")
                continue
            existing = store.get(seed["id"])
            if existing and not args.refresh_ocr:
                source = existing
                source["image_url"] = f"/archive/{image_path.name}"
                print(f"Reusing stored OCR/review: {seed['title']}")
            else:
                transcribe = mistral.ocr if args.transcription_method == "ocr" else mistral.transcribe_image
                source = make_source(seed, image_path, transcribe(image_path))
                source["transcription_method"] = args.transcription_method
                source["transcription_model"] = config.ocr_model if args.transcription_method == "ocr" else config.chat_model
                if args.transcription_method == "ocr":
                    source["ocr_model"] = config.ocr_model
            store.upsert(source)
            if elastic is not None:
                elastic.index_source(source)
            print(f"Stored: {seed['title']} ({len(source['words'])} words; reviewed={source['reviewed']})")
        if not args.download_only:
            print("Open the app's source review to verify OCR before composing.")
        return 0
    except HTTPError as exc:
        print(f"Import failed: archive/provider returned HTTP {exc.code}.", file=sys.stderr)
    except URLError:
        print("Import failed: unable to connect to archive/provider. Check network access.", file=sys.stderr)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
