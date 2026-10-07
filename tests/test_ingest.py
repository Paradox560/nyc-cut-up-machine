"""Tests use synthetic image headers, never fabricated archive transcriptions."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import struct
import tempfile
from types import ModuleType
import unittest
from unittest.mock import Mock, patch
import zlib

from cutup.config import Config
from cutup.store import CorpusStore
from scripts import ingest


def png(width=1, height=1):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\0\0\0\0"))
        + chunk(b"IEND", b"")
    )


def jpeg():
    # Synthetic baseline frame and scan for structural-validation tests only.
    return (b"\xff\xd8\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
            b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00\x12\xff\xd9")


class ImageValidationTests(unittest.TestCase):
    def test_png_and_jpeg_including_archive_octet_stream(self):
        self.assertEqual(ingest.validate_image(png(), "image/png"), ".png")
        self.assertEqual(ingest.validate_image(jpeg(), "application/octet-stream"), ".jpg")

    def test_html_empty_truncated_and_mime_mismatch_rejected(self):
        examples = [(b"", ""), (b"<html>Error</html>", "text/html"),
                    (jpeg()[:-2], "image/jpeg"), (png()[:-12], "image/png"),
                    (png(), "image/jpeg"), (jpeg(), "text/html"),
                    (b"\xff\xd8\xff\xd9", "image/jpeg")]
        for data, mime in examples:
            with self.subTest(mime=mime, length=len(data)), self.assertRaises(ValueError):
                ingest.validate_image(data, mime)

    def test_corrupt_png_checksum_rejected(self):
        bad = bytearray(png())
        bad[20] ^= 1
        with self.assertRaisesRegex(ValueError, "checksum"):
            ingest.validate_image(bytes(bad))

    def test_image_size_and_dimensions_are_bounded(self):
        for width, height in ((0, 1), (1, 0), (100_000, 100_000)):
            with self.subTest(width=width, height=height), self.assertRaises(ValueError):
                ingest.validate_image(png(width, height))
        with patch.object(ingest, "MAX_IMAGE_BYTES", 10), self.assertRaises(ValueError):
            ingest.validate_image(png())


class ManifestAndDownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.seeds = ingest.load_manifest(ingest.PROJECT_ROOT / "data" / "seeds.json")
        self.seed = self.seeds[0]

    def test_disallow_other_hosts_protocols_credentials_ports_and_query(self):
        urls = ["http://nycrecords.access.preservica.com/x", "https://localhost/x",
                "https://nycrecords.access.preservica.com.evil.test/x", "file:///etc/passwd",
                "https://user@nycrecords.access.preservica.com/x",
                "https://nycrecords.access.preservica.com:9443/x",
                "https://nycrecords.access.preservica.com/x?url=http://localhost",
                "https://nycrecords.access.preservica.com/x#fragment"]
        for url in urls:
            with self.subTest(url=url), self.assertRaises(ValueError):
                ingest.validate_url(url)

    def test_redirect_to_unapproved_host_is_blocked(self):
        with self.assertRaises(ValueError):
            ingest.ArchiveRedirectHandler().redirect_request(None, None, 302, "", {}, "https://example.com/image.jpg")

    def test_invalid_manifest_rejected_before_download(self):
        variants = [
            {"version": 1, "sources": [self.seed, self.seed]},
            {"version": 1, "sources": [{**self.seed, "title": ""}]},
            {"version": 1, "sources": [{**self.seed, "id": "../../outside"}]},
            {"version": 1, "sources": [{**self.seed, "download_url": self.seeds[1]["download_url"]}]},
            {"version": 1, "sources": []},
            {"version": 2, "sources": [self.seed]},
        ]
        for index, payload in enumerate(variants):
            path = self.directory / f"manifest-{index}.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.subTest(index=index), self.assertRaises(ValueError):
                ingest.load_manifest(path)

    def test_cached_valid_image_never_uses_network(self):
        cached = self.directory / f"{self.seed['id']}.jpg"
        cached.write_bytes(jpeg())
        downloader = ingest.ArchiveDownloader(self.directory)
        downloader.opener = Mock()
        self.assertEqual(downloader.download(self.seed), cached)
        downloader.opener.open.assert_not_called()

    def test_invalid_cached_image_is_not_used_or_silently_replaced(self):
        cached = self.directory / f"{self.seed['id']}.jpg"
        cached.write_text("not an image", encoding="utf-8")
        downloader = ingest.ArchiveDownloader(self.directory)
        downloader.opener = Mock()
        with self.assertRaises(ValueError):
            downloader.download(self.seed)
        downloader.opener.open.assert_not_called()
        self.assertEqual(cached.read_text(), "not an image")

    def test_download_validates_response_and_writes_real_extension(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.headers = {"Content-Type": "image/png", "Content-Length": str(len(png()))}
        response.geturl.return_value = self.seed["download_url"]
        response.read.return_value = png()
        downloader = ingest.ArchiveDownloader(self.directory / "images")
        downloader.opener = Mock()
        downloader.opener.open.return_value = response
        result = downloader.download(self.seed)
        self.assertEqual(result.suffix, ".png")
        self.assertEqual(result.read_bytes(), png())
        response.read.assert_called_once_with(ingest.MAX_IMAGE_BYTES + 1)
        self.assertFalse(result.with_suffix(".png.part").exists())


class ImportSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.config = Config(project_root=self.directory, data_dir=self.directory / "data", mistral_api_key="test-only")
        self.seed = ingest.load_manifest(ingest.PROJECT_ROOT / "data" / "seeds.json")[0]
        self.manifest = self.directory / "manifest.json"
        self.manifest.write_text(json.dumps({"version": 1, "sources": [self.seed]}), encoding="utf-8")
        self.image = self.config.data_dir / "archive" / f"{self.seed['id']}.png"
        self.image.parent.mkdir(parents=True)
        self.image.write_bytes(png())
        self.providers = ModuleType("cutup.providers")
        self.providers.MistralClient = Mock()
        self.providers.MistralClient.return_value.ocr.return_value = "SYNTHETIC TEST TEXT"
        self.providers.ElasticClient = Mock()

    def run_import(self, *arguments, config=None):
        with patch("cutup.config.load_config", return_value=config or self.config), \
             patch.dict("sys.modules", {"cutup.providers": self.providers}), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return ingest.main(["--manifest", str(self.manifest), *arguments])

    def test_download_only_needs_no_credentials_and_calls_no_providers(self):
        config = Config(project_root=self.directory, data_dir=self.config.data_dir)
        self.assertEqual(self.run_import("--download-only", config=config), 0)
        self.providers.MistralClient.assert_not_called()
        self.providers.ElasticClient.assert_not_called()
        self.assertFalse((config.data_dir / "corpus.json").exists())

    def test_default_import_never_indexes_and_requires_review(self):
        self.assertEqual(self.run_import(), 0)
        source = CorpusStore(self.config.data_dir).get(self.seed["id"])
        self.assertFalse(source["reviewed"])
        self.assertEqual([word["text"] for word in source["words"]], ["SYNTHETIC", "TEST", "TEXT"])
        self.assertNotIn("Victory", [word["text"] for word in source["words"]])
        self.providers.ElasticClient.assert_not_called()

    def test_rerun_preserves_reviewed_transcription_without_repeat_ocr(self):
        source = ingest.make_source(self.seed, self.image, "HUMAN VERIFIED TEST")
        source["reviewed"] = True
        CorpusStore(self.config.data_dir).upsert(source)
        self.assertEqual(self.run_import(), 0)
        self.providers.MistralClient.return_value.ocr.assert_not_called()
        saved = CorpusStore(self.config.data_dir).get(self.seed["id"])
        self.assertTrue(saved["reviewed"])
        self.assertEqual(saved["ocr_text"], "HUMAN VERIFIED TEST")

    def test_refresh_ocr_resets_review(self):
        source = ingest.make_source(self.seed, self.image, "HUMAN VERIFIED TEST")
        source["reviewed"] = True
        CorpusStore(self.config.data_dir).upsert(source)
        self.assertEqual(self.run_import("--refresh-ocr"), 0)
        self.providers.MistralClient.return_value.ocr.assert_called_once_with(self.image)
        self.assertFalse(CorpusStore(self.config.data_dir).get(self.seed["id"])["reviewed"])

    def test_index_requires_credentials_then_calls_index_only_on_flag(self):
        self.assertEqual(self.run_import("--index"), 1)
        self.providers.ElasticClient.assert_not_called()
        config = Config(project_root=self.directory, data_dir=self.config.data_dir,
                        mistral_api_key="test-only", elasticsearch_url="https://example.invalid",
                        elasticsearch_api_key="test-only")
        self.assertEqual(self.run_import("--index", config=config), 0)
        self.providers.ElasticClient.return_value.index_source.assert_called_once()

    def test_cli_rejects_ambiguous_or_unbounded_arguments(self):
        for args in (["--download-only", "--index"], ["--download-only", "--refresh-ocr"],
                     ["--limit", "0"], ["--limit", "-2"], ["--limit", "two"]):
            with self.subTest(args=args), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                ingest.parse_args(args)
        self.assertEqual(ingest.parse_args([]).limit, 3)
        self.assertFalse(ingest.parse_args([]).index)


if __name__ == "__main__":
    unittest.main()
