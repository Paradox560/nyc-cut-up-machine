from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cutup.provenance import ProvenanceError
from cutup.store import CorpusStore, atomic_json


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.store = CorpusStore(self.root)

    def test_upsert_replaces_a_source_and_rebuilds_its_evidence(self):
        self.store.upsert({"id": "one", "ocr_text": "OPEN", "reviewed": True})
        self.store.upsert({"id": "two", "ocr_text": "CLOSED", "reviewed": False})
        old_id = self.store.get("one")["words"][0]["id"]
        self.store.upsert({"id": "one", "ocr_text": "OPEN LATE", "reviewed": False})
        self.assertEqual(len(self.store.all()), 2)
        updated = self.store.get("one")
        self.assertEqual([word["text"] for word in updated["words"]], ["OPEN", "LATE"])
        self.assertNotEqual(updated["words"][0]["id"], old_id)
        self.assertFalse(updated["reviewed"])
        self.assertEqual(self.store.get("two")["ocr_text"], "CLOSED")

    def test_invalid_update_does_not_destroy_existing_corpus(self):
        self.store.upsert({"id": "one", "ocr_text": "OPEN", "reviewed": True})
        before = self.store.path.read_bytes()
        with self.assertRaises(ProvenanceError):
            self.store.upsert({"id": "one", "ocr_text": None})
        self.assertEqual(self.store.path.read_bytes(), before)

    def test_failed_serialization_preserves_last_snapshot_and_cleans_temp_file(self):
        path = self.root / "snapshot.json"
        atomic_json(path, {"status": "complete"})
        with self.assertRaises(TypeError):
            atomic_json(path, {"status": "partial", "invalid": object()})
        self.assertEqual(json.loads(path.read_text()), {"status": "complete"})
        self.assertEqual(set(self.root.iterdir()), {path})

    def test_failed_replacement_preserves_last_snapshot_and_cleans_temp_file(self):
        path = self.root / "snapshot.json"
        atomic_json(path, {"version": 1})
        with patch("cutup.store.Path.replace", side_effect=OSError("simulated filesystem failure")):
            with self.assertRaises(OSError):
                atomic_json(path, {"version": 2})
        self.assertEqual(json.loads(path.read_text()), {"version": 1})
        self.assertEqual(set(self.root.iterdir()), {path})

    def test_readers_observe_only_complete_snapshots_during_replacement(self):
        path = self.root / "snapshot.json"

        def snapshot(version):
            return {"version": version, "text": str(version) * 16000}

        atomic_json(path, snapshot(0))

        def write_snapshots():
            for version in range(1, 25):
                atomic_json(path, snapshot(version))

        def read_snapshots():
            for _ in range(90):
                value = json.loads(path.read_text())
                self.assertEqual(value, snapshot(value["version"]))

        with ThreadPoolExecutor(max_workers=3) as pool:
            tasks = [pool.submit(write_snapshots), pool.submit(read_snapshots), pool.submit(read_snapshots)]
            for task in tasks:
                task.result()

    def test_saved_composition_keeps_its_original_evidence_snapshot(self):
        record = self.store.upsert({"id": "one", "ocr_text": "OPEN", "reviewed": True})
        identifier = "a" * 32
        composition = {"id": identifier, "lines": [[record["words"][0]]], "sources": [record]}
        self.store.save_composition(composition)
        self.store.upsert({"id": "one", "ocr_text": "CLOSED", "reviewed": False})
        # Mutating the caller's objects must not rewrite a saved result either.
        composition["lines"][0][0]["text"] = "CHANGED"
        saved = self.store.get_composition(identifier)
        self.assertEqual(saved["lines"][0][0]["text"], "OPEN")
        self.assertEqual(saved["sources"][0]["ocr_text"], "OPEN")
        self.assertEqual(self.store.get("one")["ocr_text"], "CLOSED")

    def test_composition_ids_cannot_escape_the_data_directory(self):
        for identifier in ["../outside", "../../outside.json", "a" * 31, "G" * 32, "/tmp/result"]:
            with self.subTest(identifier=identifier):
                with self.assertRaises(ValueError):
                    self.store.save_composition({"id": identifier})
                self.assertIsNone(self.store.get_composition(identifier))
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
