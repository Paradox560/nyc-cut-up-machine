from http.client import HTTPConnection
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch

from cutup.config import Config
from cutup.http_client import ProviderError
from cutup.server import AppServer
from cutup.store import CorpusStore


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.config = Config(
            project_root=self.root, data_dir=self.root / "data",
            mistral_api_key="test-mistral-private-sentinel",
            elasticsearch_url="https://cluster.example",
            elasticsearch_api_key="test-elastic-private-sentinel",
        )
        (self.root / "web").mkdir()
        (self.root / "web" / "index.html").write_text("<!doctype html><p>Test app</p>")
        (self.root / "web" / "app.js").write_text("const ready = true;")
        (self.root / ".env.local").write_text("SECRET=test-file-secret-sentinel\n")
        (self.root / "private.js").write_text("test-file-secret-sentinel")
        (self.root / "web" / "escape.js").symlink_to(self.root / "private.js")
        (self.config.data_dir / "archive").mkdir(parents=True)
        (self.config.data_dir / "archive" / "photo.jpg").write_bytes(b"test-photo")
        (self.config.data_dir / "secret.jpg").write_bytes(b"test-file-secret-sentinel")
        self.store = CorpusStore(self.config.data_dir)
        self.record = self.store.upsert({
            "id": "archive-one", "ocr_text": "OPEN ALL NIGHT", "reviewed": False,
            "source_url": "https://archive.example/one", "synthetic": False,
        })
        self.config_patch = patch("cutup.server.load_config", return_value=self.config)
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)
        self.server = AppServer(("127.0.0.1", 0), project_root=self.root)
        self.addCleanup(self.server.server_close)
        self.thread = Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.thread.join(timeout=2)

    def request(self, path, *, method="GET", payload=None, headers=None, raw=None):
        body = raw if raw is not None else json.dumps(payload).encode() if payload is not None else None
        request_headers = {"Content-Type": "application/json", **(headers or {})}
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            data = response.read()
            content_type = response.getheader("Content-Type", "")
            result = json.loads(data) if content_type.startswith("application/json") else data
            return response.status, result, dict(response.getheaders())
        finally:
            connection.close()

    def test_static_files_and_archive_images_are_served_with_security_headers(self):
        for path, expected in [("/", b"<!doctype html><p>Test app</p>"), ("/archive/photo.jpg", b"test-photo")]:
            with self.subTest(path=path):
                status, data, headers = self.request(path)
                self.assertEqual(status, 200)
                self.assertEqual(data, expected)
                self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
                self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])

    def test_static_traversal_symlinks_and_env_files_are_unservable(self):
        for path in [
            "/.env.local", "/../.env.local", "/%2e%2e/.env.local",
            "/%2e%2e/private.js", "/escape.js", "/archive/../secret.jpg",
            "/archive/%2e%2e%2fsecret.jpg", "/archive/%2e%2e/%2e%2e/.env.local",
        ]:
            with self.subTest(path=path):
                status, result, _ = self.request(path)
                self.assertEqual(status, 404)
                self.assertNotIn("test-file-secret-sentinel", str(result))

    def test_cross_origin_and_untrusted_host_requests_are_blocked(self):
        for headers in [
            {"Origin": "https://attacker.example"}, {"Sec-Fetch-Site": "cross-site"},
            {"Host": "attacker.example"}, {"Origin": "null"},
        ]:
            with self.subTest(headers=headers), patch("cutup.server.compose") as compose:
                status, result, _ = self.request(
                    "/api/compose", method="POST", payload={"prompt": "A poem"}, headers=headers,
                )
                self.assertEqual(status, 403)
                self.assertIn(result["code"], {"invalid_origin", "invalid_host"})
                compose.assert_not_called()

    def test_same_origin_is_accepted_and_status_contains_no_credentials(self):
        origin = f"http://127.0.0.1:{self.server.server_port}"
        status, result, _ = self.request("/api/status", headers={"Origin": origin})
        self.assertEqual(status, 200)
        self.assertEqual(result["configured"], {"mistral": True, "elasticsearch": True})
        self.assertEqual(result["corpus_count"], 1)
        self.assertNotIn(self.config.mistral_api_key, json.dumps(result))
        self.assertNotIn(self.config.elasticsearch_api_key, json.dumps(result))

    def test_compose_enforces_json_types_before_any_provider_call(self):
        invalid = [
            {"prompt": None}, {"prompt": []}, {"prompt": "hi"},
            {"prompt": "A poem", "form": []}, {"prompt": "A poem", "form": {}},
            {"prompt": "A poem", "include_unreviewed": "false"},
            {"prompt": "A poem", "include_unreviewed": 1},
        ]
        with patch("cutup.composer.ElasticClient") as elastic, patch("cutup.composer.MistralClient") as mistral:
            for payload in invalid:
                with self.subTest(payload=payload):
                    status, result, _ = self.request("/api/compose", method="POST", payload=payload)
                    self.assertEqual(status, 400)
                    self.assertEqual(result["code"], "invalid_request")
            elastic.assert_not_called()
            mistral.assert_not_called()

    def test_reuse_id_must_be_a_composition_id(self):
        with patch("cutup.composer.ElasticClient") as elastic, patch("cutup.composer.MistralClient") as mistral:
            for bad in ["", "abc", "../../etc/passwd", "G" * 32, 12, True, ["a" * 32]]:
                with self.subTest(reuse_id=bad):
                    status, result, _ = self.request(
                        "/api/compose", method="POST",
                        payload={"prompt": "A poem", "form": "poem", "reuse_id": bad})
                    self.assertEqual(status, 400)
                    self.assertEqual(result["code"], "invalid_request")
            elastic.assert_not_called()
            mistral.assert_not_called()

    def test_words_route_returns_ranked_photographs_from_elasticsearch(self):
        hits = [{"rank": 1, "source_id": "archive-one", "title": "Whitehall Street", "words": ["LOST", "OPEN"]}]
        with patch("cutup.server.ElasticClient") as elastic:
            elastic.return_value.find_words.return_value = hits
            status, result, _ = self.request("/api/words?q=loss")
        self.assertEqual(status, 200)
        self.assertEqual(result, {"mode": "live", "results": hits})
        elastic.return_value.find_words.assert_called_once_with("loss")

    def test_words_route_rejects_too_short_or_too_long_queries(self):
        with patch("cutup.server.ElasticClient") as elastic:
            for path in ["/api/words", "/api/words?q=", "/api/words?q=a", "/api/words?q=" + "x" * 201]:
                with self.subTest(path=path[:30]):
                    status, result, _ = self.request(path)
                    self.assertEqual(status, 400)
                    self.assertEqual(result["code"], "invalid_request")
            elastic.assert_not_called()

    def test_malformed_json_and_non_object_bodies_are_rejected(self):
        for body in [b"{bad json", b"[]", b"null", b'"a string"']:
            with self.subTest(body=body):
                status, _, _ = self.request("/api/compose", method="POST", raw=body)
                self.assertEqual(status, 400)
        status, _, _ = self.request(
            "/api/compose", method="POST", raw=b"{}", headers={"Content-Type": "text/plain"},
        )
        self.assertEqual(status, 415)

    def test_request_body_limit_rejects_before_composition(self):
        with patch("cutup.server.compose") as compose:
            status, _, _ = self.request("/api/compose", method="POST", raw=b"x" * 65537)
            self.assertEqual(status, 413)
            compose.assert_not_called()

    def test_review_reindexes_corrected_tokens_before_persisting_approval(self):
        events = []

        def index_source(source):
            events.append(source)
            self.assertFalse(self.store.get("archive-one")["reviewed"])
            self.assertEqual(self.store.get("archive-one")["ocr_text"], "OPEN ALL NIGHT")

        with patch("cutup.server.ElasticClient") as elastic:
            elastic.return_value.index_source.side_effect = index_source
            status, result, _ = self.request("/api/sources/review", method="POST", payload={
                "id": "archive-one", "reviewed": True, "ocr_text": "OPEN EVERY NIGHT",
            })
            elastic.return_value.index_source.assert_called_once()
        self.assertEqual(status, 200)
        saved = self.store.get("archive-one")
        self.assertTrue(saved["reviewed"])
        self.assertEqual(saved["ocr_original"], "OPEN ALL NIGHT")
        self.assertEqual(saved["ocr_text"], "OPEN EVERY NIGHT")
        self.assertEqual([word["text"] for word in saved["words"]], ["OPEN", "EVERY", "NIGHT"])
        self.assertNotEqual(saved["words"][0]["id"], self.record["words"][0]["id"])
        self.assertEqual(result["source"], saved)
        self.assertEqual(events, [saved])

    def test_failed_reindex_does_not_persist_optimistic_review_or_ocr_edit(self):
        before = self.store.path.read_bytes()
        with patch("cutup.server.ElasticClient") as elastic:
            elastic.return_value.index_source.side_effect = ProviderError("Test index unavailable")
            status, result, _ = self.request("/api/sources/review", method="POST", payload={
                "id": "archive-one", "reviewed": True, "ocr_text": "OPEN EVERY NIGHT",
            })
        self.assertEqual(status, 502)
        self.assertEqual(result["code"], "provider_error")
        self.assertEqual(self.store.path.read_bytes(), before)
        # The request semaphore must be released after a provider exception.
        self.assertTrue(self.server.work_slot.acquire(blocking=False))
        self.server.work_slot.release()

    def test_unreviewing_a_source_is_reindexed_and_clears_review_timestamp(self):
        self.store.upsert({**self.record, "reviewed": True, "reviewed_at": "old-timestamp"})
        with patch("cutup.server.ElasticClient") as elastic:
            status, result, _ = self.request("/api/sources/review", method="POST", payload={
                "id": "archive-one", "reviewed": False,
            })
            indexed = elastic.return_value.index_source.call_args.args[0]
        self.assertEqual(status, 200)
        self.assertFalse(indexed["reviewed"])
        self.assertIsNone(indexed["reviewed_at"])
        self.assertFalse(result["source"]["reviewed"])
        self.assertFalse(self.store.get("archive-one")["reviewed"])

    def test_transcription_edit_clears_old_crops_before_reindex_and_save(self):
        self.add_source_crop()
        with patch("cutup.server.ElasticClient") as elastic:
            status, result, _ = self.request("/api/sources/review", method="POST", payload={
                "id": "archive-one", "reviewed": True, "ocr_text": "OPEN EVERY NIGHT",
            })
            indexed = elastic.return_value.index_source.call_args.args[0]
        self.assertEqual(status, 200)
        self.assertEqual(indexed["word_crops"], [])
        self.assertTrue(all("crop" not in word for word in indexed["words"]))
        self.assertNotIn("crop_reviewed_at", indexed)
        self.assertEqual(result["source"]["word_crops"], [])
        self.assertEqual(self.store.get("archive-one")["word_crops"], [])

    def test_review_with_unchanged_text_preserves_pixel_locations(self):
        cropped = self.add_source_crop()
        with patch("cutup.server.ElasticClient"):
            status, result, _ = self.request("/api/sources/review", method="POST", payload={
                "id": "archive-one", "reviewed": True, "ocr_text": cropped["ocr_text"],
            })
        self.assertEqual(status, 200)
        self.assertEqual(result["source"]["word_crops"], cropped["word_crops"])
        self.assertEqual(self.store.get("archive-one")["words"][0]["crop"], cropped["words"][0]["crop"])

    def add_source_crop(self):
        word = self.record["words"][0]
        return self.store.upsert({
            **self.record, "image_url": "/archive/photo.jpg", "image_width": 100,
            "image_height": 50, "image_sha256": sha256(b"test-photo").hexdigest(),
            "crop_reviewed_at": "test-timestamp", "crop_review_method": "test-review",
            "word_crops": [{
                "word_id": word["id"], "text": word["text"], "x": 0, "y": 0,
                "width": 30, "height": 20, "method": "test-localization", "confidence": 99,
            }],
        })

    def test_review_rejects_invalid_types_without_reindexing_or_saving(self):
        invalid = [
            {"id": [], "reviewed": True}, {"id": None, "reviewed": True},
            {"id": "archive-one", "reviewed": "true"},
            {"id": "archive-one", "reviewed": 1},
            {"id": "archive-one", "reviewed": True, "ocr_text": []},
        ]
        before = self.store.path.read_bytes()
        with patch("cutup.server.ElasticClient") as elastic:
            for payload in invalid:
                with self.subTest(payload=payload):
                    status, _, _ = self.request("/api/sources/review", method="POST", payload=payload)
                    self.assertEqual(status, 400)
            elastic.assert_not_called()
        self.assertEqual(self.store.path.read_bytes(), before)

    def test_parallel_expensive_work_is_rejected_without_calling_provider(self):
        self.assertTrue(self.server.work_slot.acquire(blocking=False))
        try:
            with patch("cutup.server.compose") as compose:
                status, result, _ = self.request("/api/compose", method="POST", payload={"prompt": "A poem"})
                self.assertEqual(status, 409)
                self.assertEqual(result["code"], "busy")
                compose.assert_not_called()
        finally:
            self.server.work_slot.release()

    def test_speech_refuses_synthetic_compositions(self):
        identifier = "b" * 32
        self.store.save_composition({"id": identifier, "mode": "demo", "lines": []})
        with patch("cutup.server.MistralClient") as mistral:
            status, _, _ = self.request("/api/speech", method="POST", payload={"composition_id": identifier})
            self.assertEqual(status, 409)
            mistral.assert_not_called()


if __name__ == "__main__":
    unittest.main()
