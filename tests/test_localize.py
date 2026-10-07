from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from hashlib import sha256
import io
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from cutup.config import Config
from cutup.localize import apply_accepted, image_metadata, localize_source, match_words, parse_tsv
from cutup.provenance import build_words, validate_source
from cutup.store import CorpusStore
from scripts import localize


TSV_HEADER = "level\tleft\ttop\twidth\theight\tconf\ttext\n"


def tsv(*rows):
    return TSV_HEADER + "\n".join("\t".join(str(value) for value in row) for row in rows) + "\n"


def image_bytes(width=200, height=100):
    # Structurally valid synthetic JPEG; no Tesseract process sees this fixture.
    return (b"\xff\xd8\xff\xc0\x00\x0b\x08" + struct.pack(">HH", height, width)
            + b"\x01\x01\x11\x00\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00\x12\xff\xd9")


def candidate(text, x=0, confidence=90):
    return {"text": text, "x": x, "y": 10, "width": 20, "height": 10,
            "confidence": confidence, "method": "tesseract", "psm": 11}


class LocalizationMatchingTests(unittest.TestCase):
    def test_parsed_word_boxes_preserve_actual_coordinates_and_threshold(self):
        content = tsv((5, 80, 40, 20, 10, 60, "LOVE"), (5, 0, 0, 20, 10, 59.99, "LOST"))
        result = parse_tsv(content, 100, 50, min_confidence=60, psm=3)
        self.assertEqual(result, [{
            "text": "LOVE", "x": 80, "y": 40, "width": 20, "height": 10,
            "confidence": 60, "method": "tesseract", "psm": 3,
        }])

    def test_incomplete_tsv_header_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_tsv("text\tleft\nLOVE\t0\n", 100, 50)

    def test_malformed_nonword_and_out_of_bounds_rows_are_skipped(self):
        invalid = [
            (4, 0, 0, 20, 10, 99, "PARAGRAPH"),
            ("word", 0, 0, 20, 10, 99, "LOVE"),
            (5, "1.2", 0, 20, 10, 99, "LOVE"),
            (5, 0, 0, 20, 10, "bad", "LOVE"),
            (5, -1, 0, 20, 10, 99, "LOVE"),
            (5, 0, -1, 20, 10, 99, "LOVE"),
            (5, 0, 0, 0, 10, 99, "LOVE"),
            (5, 0, 0, 20, 0, 99, "LOVE"),
            (5, 81, 0, 20, 10, 99, "LOVE"),
            (5, 0, 41, 20, 10, 99, "LOVE"),
            (5, 0, 0, 20, 10, 101, "LOVE"),
            (5, 0, 0, 20, 10, -1, "LOVE"),
            (5, 0, 0, 20, 10, "nan", "LOVE"),
            (5, 0, 0, 20, 10, "inf", "LOVE"),
            (5, 0, 0, 20, 10, 99, "!!!"),
            (5, 0, 0, 20, 10, 99),  # Missing text field, not an empty word.
        ]
        for row in invalid:
            with self.subTest(row=row):
                self.assertEqual(parse_tsv(tsv(row), 100, 50), [])

    def test_only_exact_normalized_words_match_without_fuzzy_or_substring_guesses(self):
        source = {"id": "archive-one", "ocr_text": "LOVE SAVINGS O’NEILL’S TWENTY-FOUR CAFÉ"}
        proposed = [
            candidate("NOTLOVE"), candidate("LOVES"), candidate("SAVING"),
            candidate("o'neill's", x=30), candidate("TWENTY FOUR", x=60),
            candidate("CAFE", x=90), candidate("Cafe\u0301", x=120),
        ]
        boxes = match_words(source, proposed)
        self.assertEqual([box["text"] for box in boxes], ["O’NEILL’S", "CAFÉ"])
        self.assertEqual([box["x"] for box in boxes], [30, 120])
        words = build_words(source["id"], source["ocr_text"])
        self.assertEqual([box["word_id"] for box in boxes], [words[2]["id"], words[4]["id"]])
        punctuation = match_words({"id": "archive-one", "ocr_text": "LOVE"}, [candidate("(LOVE!)")])
        self.assertEqual(punctuation[0]["text"], "LOVE")

    def test_repeated_words_use_distinct_real_boxes_then_reuse_a_real_box(self):
        source = {"id": "archive-one", "ocr_text": "LOVE LOVE LOVE"}
        boxes = match_words(source, [candidate("LOVE", x=40, confidence=85), candidate("love", x=5, confidence=99)])
        self.assertEqual([box["x"] for box in boxes], [5, 40, 5])
        self.assertEqual(len({box["word_id"] for box in boxes}), 3)
        self.assertEqual({(box["x"], box["y"], box["width"], box["height"]) for box in boxes},
                         {(5, 10, 20, 10), (40, 10, 20, 10)})

    def test_one_box_cannot_be_split_into_invented_word_locations(self):
        source = {"id": "archive-one", "ocr_text": "NEW YORK"}
        self.assertEqual(match_words(source, [candidate("NEW YORK")]), [])


class LocalizationFixture(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.config = Config(project_root=self.root, data_dir=self.root / "data")
        self.archive = self.config.data_dir / "archive"
        self.archive.mkdir(parents=True)
        self.image = self.archive / "archive-one.jpg"
        self.image.write_bytes(image_bytes())
        self.source = validate_source({
            "id": "archive-one", "title": "Synthetic test archive", "reviewed": True,
            "ocr_text": "LOVE LOST", "image_url": "/archive/archive-one.jpg",
        })
        self.store = CorpusStore(self.config.data_dir)
        self.store.upsert(self.source)


class LocalizationProposalTests(LocalizationFixture):
    def test_image_metadata_is_bound_to_actual_dimensions_and_bytes(self):
        metadata = image_metadata(self.image)
        self.assertEqual(metadata, {
            "image_width": 200, "image_height": 100,
            "image_sha256": sha256(self.image.read_bytes()).hexdigest(),
        })

    def test_proposals_preserve_image_and_transcription_hashes_without_approving_them(self):
        completed = Mock(returncode=0, stdout=tsv((5, 10, 20, 30, 10, 95, "LOVE")))
        with patch("cutup.localize.subprocess.run", return_value=completed) as run:
            proposal = localize_source(self.source, self.image, self.archive / "localization", psms=(11,), executable="test-tesseract")
        self.assertEqual(run.call_count, 1)
        self.assertEqual(proposal["status"], "pending_visual_review")
        self.assertEqual(proposal["transcription_sha256"], sha256(b"LOVE LOST").hexdigest())
        self.assertEqual(proposal["image_sha256"], sha256(self.image.read_bytes()).hexdigest())
        self.assertEqual(proposal["unmatched_words"], ["LOST"])
        self.assertEqual(proposal["word_crops"][0]["x"], 10)
        self.assertEqual(self.store.get("archive-one")["word_crops"], [])

    def test_unreviewed_transcription_never_reaches_tesseract(self):
        with patch("cutup.localize.subprocess.run") as run:
            with self.assertRaises(ValueError):
                localize_source({**self.source, "reviewed": False}, self.image, self.archive / "localization", executable="test-tesseract")
            run.assert_not_called()

    def test_tesseract_failure_is_not_treated_as_an_empty_success(self):
        with patch("cutup.localize.subprocess.run", return_value=Mock(returncode=1)):
            with self.assertRaises(RuntimeError):
                localize_source(self.source, self.image, self.archive / "localization", executable="test-tesseract")
        self.assertEqual(self.store.get("archive-one")["word_crops"], [])

    def test_cli_proposes_crops_without_mutating_corpus(self):
        before = self.store.path.read_bytes()
        completed = Mock(returncode=0, stdout=tsv((5, 10, 20, 30, 10, 95, "LOVE")))
        with patch("scripts.localize.load_config", return_value=self.config), \
                patch("cutup.localize.subprocess.run", return_value=completed), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = localize.main(["--source", "archive-one", "--psm", "11", "--tesseract", "test-tesseract"])
        self.assertEqual(code, 0)
        self.assertEqual(self.store.path.read_bytes(), before)
        proposal = json.loads((self.archive / "localization" / "proposals.json").read_text())[0]
        self.assertEqual(proposal["status"], "pending_visual_review")
        self.assertTrue((self.archive / "localization" / "review.html").exists())

    def test_cli_timeout_leaves_corpus_unchanged(self):
        before = self.store.path.read_bytes()
        with patch("scripts.localize.load_config", return_value=self.config), \
                patch("cutup.localize.subprocess.run", side_effect=subprocess.TimeoutExpired("test-tesseract", 60)), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = localize.main(["--source", "archive-one", "--tesseract", "test-tesseract"])
        self.assertEqual(code, 1)
        self.assertEqual(self.store.path.read_bytes(), before)


class LocalizationAcceptanceTests(LocalizationFixture):
    def setUp(self):
        super().setUp()
        self.proposal = {
            "source_id": self.source["id"], "title": self.source["title"],
            "image_url": self.source["image_url"], **image_metadata(self.image),
            "transcription_sha256": sha256(self.source["ocr_text"].encode()).hexdigest(),
            "status": "pending_visual_review", "unmatched_words": [],
            "word_crops": [{**candidate(word["text"], x=index * 30), "word_id": word["id"]}
                           for index, word in enumerate(self.source["words"])],
        }
        self.accepted_id = self.source["words"][0]["id"]

    def test_only_explicitly_accepted_crops_are_saved_with_review_metadata(self):
        counts = apply_accepted({"archive-one": [self.accepted_id]}, [self.proposal], self.store, self.archive)
        self.assertEqual(counts, {"archive-one": 1})
        saved = self.store.get("archive-one")
        self.assertEqual([crop["word_id"] for crop in saved["word_crops"]], [self.accepted_id])
        self.assertEqual(saved["image_sha256"], self.proposal["image_sha256"])
        self.assertEqual(saved["crop_review_method"], "visual_inspection")
        self.assertTrue(saved["crop_reviewed_at"])
        self.assertIn("crop", saved["words"][0])
        self.assertNotIn("crop", saved["words"][1])

    def test_additional_acceptance_preserves_prior_crops_from_same_image(self):
        apply_accepted({"archive-one": [self.accepted_id]}, [self.proposal], self.store, self.archive)
        second_id = self.source["words"][1]["id"]
        apply_accepted({"archive-one": [second_id]}, [self.proposal], self.store, self.archive)
        saved = self.store.get("archive-one")
        self.assertEqual({crop["word_id"] for crop in saved["word_crops"]}, {self.accepted_id, second_id})

    def test_changed_transcription_or_photo_rejects_old_proposals_without_writes(self):
        self.store.upsert({**self.source, "ocr_text": "LOVE FOUND"})
        before = self.store.path.read_bytes()
        with self.assertRaises(ValueError):
            apply_accepted({"archive-one": [self.accepted_id]}, [self.proposal], self.store, self.archive)
        self.assertEqual(self.store.path.read_bytes(), before)
        self.store.upsert(self.source)
        before = self.store.path.read_bytes()
        self.image.write_bytes(image_bytes().replace(b"\x12\xff\xd9", b"\x13\xff\xd9"))
        self.assertEqual(image_metadata(self.image)["image_width"], self.proposal["image_width"])
        with self.assertRaises(ValueError):
            apply_accepted({"archive-one": [self.accepted_id]}, [self.proposal], self.store, self.archive)
        self.assertEqual(self.store.path.read_bytes(), before)

    def test_all_accepted_sources_are_validated_before_any_corpus_write(self):
        second = validate_source({**self.source, "id": "archive-two", "image_url": "/archive/archive-two.jpg"})
        self.store.upsert(second)
        (self.archive / "archive-two.jpg").write_bytes(image_bytes())
        second_proposal = {
            **self.proposal, "source_id": "archive-two", "image_url": second["image_url"],
            "image_sha256": "0" * 64,
        }
        before = self.store.path.read_bytes()
        with self.assertRaises(ValueError):
            apply_accepted({"archive-one": [self.accepted_id], "archive-two": [second["words"][0]["id"]]},
                           [self.proposal, second_proposal], self.store, self.archive)
        self.assertEqual(self.store.path.read_bytes(), before)

    def test_invalid_acceptance_types_duplicates_and_unknown_ids_are_rejected(self):
        before = self.store.path.read_bytes()
        for accepted in [
            [], {"archive-one": "all"}, {"archive-one": [None]},
            {"archive-one": [self.accepted_id, self.accepted_id]},
            {"missing-source": [self.accepted_id]}, {"archive-one": ["unknown-word-id"]},
        ]:
            with self.subTest(accepted=accepted):
                with self.assertRaises(ValueError):
                    apply_accepted(accepted, [self.proposal], self.store, self.archive)
                self.assertEqual(self.store.path.read_bytes(), before)

    def test_tampered_accepted_crop_metadata_is_rejected_without_writes(self):
        before = self.store.path.read_bytes()
        for edit in [
            {"text": "FORGED"}, {"x": -1}, {"width": 201}, {"height": 0}, {"x": True},
            {"confidence": float("nan")}, {"confidence": float("inf")},
            {"confidence": 10 ** 400}, {"method": "invented-position"},
        ]:
            with self.subTest(edit=edit):
                proposal = deepcopy(self.proposal)
                proposal["word_crops"][0].update(edit)
                with self.assertRaises(ValueError):
                    apply_accepted({"archive-one": [self.accepted_id]}, [proposal], self.store, self.archive)
                self.assertEqual(self.store.path.read_bytes(), before)

    def test_cli_accepts_review_file_without_rerunning_localization_or_indexing(self):
        output = self.archive / "localization"
        output.mkdir()
        (output / "proposals.json").write_text(json.dumps([self.proposal]))
        accepted = self.root / "accepted-crop-ids.json"
        accepted.write_text(json.dumps({"archive-one": [self.accepted_id]}))
        with patch("scripts.localize.load_config", return_value=self.config), \
                patch("cutup.localize.subprocess.run") as run, \
                patch("cutup.providers.ElasticClient") as elastic, \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = localize.main(["--accept", str(accepted)])
        self.assertEqual(code, 0)
        self.assertEqual(len(self.store.get("archive-one")["word_crops"]), 1)
        run.assert_not_called()
        elastic.assert_not_called()


if __name__ == "__main__":
    unittest.main()
