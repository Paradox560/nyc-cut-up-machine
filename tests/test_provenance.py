from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

from cutup.provenance import (
    ProvenanceError,
    build_words,
    plain_text,
    resolve_lines,
    validate_source,
    verify_crop_images,
)


def source(text="OPEN ALL NIGHT", **overrides):
    return {"id": "archive-1", "ocr_text": text, "reviewed": True, **overrides}


class ProvenanceTests(unittest.TestCase):
    def test_composition_renders_only_original_words_and_allows_reuse(self):
        record = source("LOVE, LOST & FOUND")
        words = build_words(record["id"], record["ocr_text"])
        output = resolve_lines(
            {"lines": [[words[2]["id"], words[0]["id"], words[0]["id"]]]}, [record]
        )
        self.assertEqual(plain_text(output), "FOUND LOVE LOVE")
        for token in output[0]:
            self.assertEqual(record["ocr_text"][token["start"]:token["end"]], token["text"])
            self.assertEqual(token["source_id"], record["id"])
        # Repeated words are separate output objects, so UI annotations cannot
        # accidentally mutate another occurrence or the retrieved vocabulary.
        output[0][1]["text"] = "CHANGED"
        self.assertEqual(output[0][2]["text"], "LOVE")

    def test_hallucinated_word_id_is_rejected(self):
        with self.assertRaises(ProvenanceError):
            resolve_lines({"lines": [["archive-1:invented:0"]]}, [source()])

    def test_editing_ocr_invalidates_previously_selected_ids(self):
        original = source("OPEN ALL NIGHT")
        selected = build_words(original["id"], original["ocr_text"])[0]["id"]
        corrected = {**original, "ocr_text": "OPEN AT NIGHT"}
        with self.assertRaises(ProvenanceError):
            resolve_lines({"lines": [[selected]]}, [corrected])

    def test_forged_stored_words_never_enter_the_vocabulary(self):
        record = source(words=[{
            "id": "forged-id", "text": "MILLIONAIRE", "source_id": "archive-1",
            "start": 0, "end": 11,
        }])
        checked = validate_source(record)
        self.assertEqual([word["text"] for word in checked["words"]], ["OPEN", "ALL", "NIGHT"])
        with self.assertRaises(ProvenanceError):
            resolve_lines({"lines": [["forged-id"]]}, [record])

    def test_duplicate_source_word_ids_are_rejected(self):
        record = source()
        selected = build_words(record["id"], record["ocr_text"])[0]["id"]
        with self.assertRaises(ProvenanceError):
            resolve_lines({"lines": [[selected]]}, [record, dict(record)])

    def test_unreviewed_source_is_excluded_even_with_a_valid_id(self):
        record = source(reviewed=False)
        selected = build_words(record["id"], record["ocr_text"])[0]["id"]
        with self.assertRaises(ProvenanceError):
            resolve_lines({"lines": [[selected]]}, [record])
        # The explicit fixture-mode override must still resolve genuine tokens.
        self.assertEqual(
            plain_text(resolve_lines({"lines": [[selected]]}, [record], require_reviewed=False)),
            "OPEN",
        )

    def test_omitted_review_flag_does_not_imply_approval(self):
        record = {"id": "archive-1", "ocr_text": "OPEN"}
        selected = build_words(record["id"], record["ocr_text"])[0]["id"]
        self.assertFalse(validate_source(record)["reviewed"])
        with self.assertRaises(ProvenanceError):
            resolve_lines({"lines": [[selected]]}, [record])

    def test_unicode_words_keep_original_spelling_apostrophes_and_offsets(self):
        record = source("CAFÉ — O’NEILL’S can't WAIT; twenty-four!")
        words = build_words(record["id"], record["ocr_text"])
        self.assertEqual(
            [word["text"] for word in words],
            ["CAFÉ", "O’NEILL’S", "can't", "WAIT", "twenty-four"],
        )
        output = resolve_lines({"lines": [[word["id"] for word in words]]}, [record])
        self.assertEqual(plain_text(output), "CAFÉ O’NEILL’S can't WAIT twenty-four")
        for token in output[0]:
            self.assertEqual(record["ocr_text"][token["start"]:token["end"]], token["text"])

    def test_malformed_model_responses_are_rejected(self):
        record = source()
        selected = build_words(record["id"], record["ocr_text"])[0]["id"]
        malformed = [
            None, [], {}, {"lines": [[selected]], "text": "Unverified extra words"},
            {"lines": None}, {"lines": "OPEN"}, {"lines": []},
            {"lines": [[]]}, {"lines": [selected]}, {"lines": [[None]]},
            {"lines": [[{"id": selected}]]}, {"lines": [[1]]},
            {"lines": [[selected] * 21]}, {"lines": [[selected]] * 13},
            {"lines": [[selected] * 20] * 6},
        ]
        for payload in malformed:
            with self.subTest(payload=payload):
                with self.assertRaises(ProvenanceError):
                    resolve_lines(payload, [record])

    def test_malformed_source_metadata_is_rejected(self):
        invalid = [
            None, {"ocr_text": "OPEN"}, source(id="../archive"), source(id=""),
            source(id=5), source(ocr_text=None), source(ocr_text="x" * 50001),
            source(reviewed="false"),
        ]
        for record in invalid:
            with self.subTest(record=repr(record)[:80]):
                with self.assertRaises(ProvenanceError):
                    validate_source(record)


class CropProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.image = b"synthetic image bytes for digest validation only"
        self.record = source("LOVE LOST AND FOUND")
        self.words = build_words(self.record["id"], self.record["ocr_text"])
        self.crop = {
            "word_id": self.words[0]["id"], "text": "LOVE", "x": 10, "y": 15,
            "width": 80, "height": 25, "method": "test-localization", "confidence": 98.5,
        }
        self.record.update({
            "image_url": "/archive/photo.jpg", "image_width": 200, "image_height": 100,
            "image_sha256": sha256(self.image).hexdigest(), "word_crops": [self.crop],
        })

    def test_valid_crop_attaches_to_exact_token_and_respects_image_edges(self):
        self.crop.update({"x": 120, "y": 75, "width": 80, "height": 25})
        checked = validate_source(self.record)
        expected = {key: value for key, value in self.crop.items() if key not in {"word_id", "text"}}
        self.assertEqual(checked["words"][0]["crop"], expected)
        self.assertNotIn("crop", checked["words"][1])
        lines = resolve_lines({"lines": [[self.words[0]["id"]]]}, [self.record], require_crops=True)
        self.assertEqual(lines[0][0]["crop"], expected)

    def test_crop_dimensions_require_finite_positive_integers(self):
        for field in ["image_width", "image_height"]:
            for value in [None, True, False, 0, -1, 200.0, "200", float("nan"), float("inf")]:
                with self.subTest(field=field, value=value):
                    record = {**self.record, field: value}
                    with self.assertRaises(ProvenanceError):
                        validate_source(record)
        with self.assertRaises(ProvenanceError):
            validate_source({**self.record, "image_width": 50_001, "image_height": 1_000})

    def test_crop_rectangles_reject_invalid_types_nonfinite_values_and_bounds(self):
        for field in ["x", "y", "width", "height"]:
            for value in [None, True, "10", 10.0, float("nan"), float("inf"), -1]:
                with self.subTest(field=field, value=value):
                    crop = {**self.crop, field: value}
                    with self.assertRaises(ProvenanceError):
                        validate_source({**self.record, "word_crops": [crop]})
        for values in [
            {"width": 0}, {"height": 0}, {"x": 121, "width": 80},
            {"y": 76, "height": 25}, {"width": 201}, {"height": 101},
        ]:
            with self.subTest(values=values):
                with self.assertRaises(ProvenanceError):
                    validate_source({**self.record, "word_crops": [{**self.crop, **values}]})

    def test_crop_requires_image_digest_and_valid_localization_metadata(self):
        for digest in [None, "", "a" * 63, "g" * 64, "a" * 65, int("1" * 64)]:
            with self.subTest(digest=digest):
                with self.assertRaises(ProvenanceError):
                    validate_source({**self.record, "image_sha256": digest})
        for field, values in [
            ("confidence", [None, True, "99", -1, 101, 10 ** 400, float("nan"), float("inf")]),
            ("method", [None, [], "", "x" * 81]),
        ]:
            for value in values:
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ProvenanceError):
                        validate_source({**self.record, "word_crops": [{**self.crop, field: value}]})

    def test_crops_cannot_change_a_current_token_or_supply_conflicting_boxes(self):
        changed_text = {**self.crop, "text": "CLOSED"}
        with self.assertRaises(ProvenanceError):
            validate_source({**self.record, "word_crops": [changed_text]})
        with self.assertRaises(ProvenanceError):
            validate_source({**self.record, "word_crops": [self.crop, {**self.crop, "x": 11}]})

    def test_cached_word_array_cannot_inject_or_override_crop_provenance(self):
        forged = deepcopy(self.words)
        forged[0]["crop"] = {"x": 150, "y": 50, "width": 20, "height": 20}
        checked = validate_source({**self.record, "words": forged})
        self.assertEqual(checked["words"][0]["crop"]["x"], 10)
        checked_without_crops = validate_source({**self.record, "words": forged, "word_crops": []})
        self.assertNotIn("crop", checked_without_crops["words"][0])

    def test_stale_or_unknown_ids_do_not_attach_crops_to_new_text(self):
        corrected = validate_source({**self.record, "ocr_text": "LOVE LOST AND OPEN"})
        self.assertEqual(corrected["word_crops"], [])
        self.assertTrue(all("crop" not in word for word in corrected["words"]))
        unknown = {**self.crop, "word_id": "unknown:word:0"}
        checked = validate_source({**self.record, "word_crops": [self.crop, unknown]})
        self.assertEqual(checked["word_crops"], [self.crop])

    def test_require_crops_excludes_uncropped_tokens_even_with_valid_text_ids(self):
        selected = {"lines": [[self.words[1]["id"]]]}
        self.assertEqual(plain_text(resolve_lines(selected, [self.record])), "LOST")
        with self.assertRaises(ProvenanceError):
            resolve_lines(selected, [self.record], require_crops=True)
        with self.assertRaises(ProvenanceError):
            resolve_lines(selected, [{**self.record, "reviewed": False}], require_reviewed=False, require_crops=True)

    def test_image_digest_verification_rejects_changed_or_missing_photo(self):
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            image = data_dir / "archive" / "photo.jpg"
            image.parent.mkdir()
            image.write_bytes(self.image)
            self.assertIsNone(verify_crop_images([self.record], data_dir))
            image.write_bytes(b"different photo bytes")
            with self.assertRaises(ProvenanceError):
                verify_crop_images([self.record], data_dir)
            image.unlink()
            with self.assertRaises(ProvenanceError):
                verify_crop_images([self.record], data_dir)

    def test_image_digest_verification_rejects_remote_and_escaping_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            (data_dir / "archive").mkdir()
            outside = data_dir / "photo.jpg"
            outside.write_bytes(self.image)
            (data_dir / "archive" / "linked.jpg").symlink_to(outside)
            for image_url in [
                "https://archive.example/photo.jpg", "/archive/../photo.jpg",
                "/archive/%2e%2e/photo.jpg", "/photo.jpg", "/archive/linked.jpg",
            ]:
                with self.subTest(image_url=image_url):
                    with self.assertRaises(ProvenanceError):
                        verify_crop_images([{**self.record, "image_url": image_url}], data_dir)


if __name__ == "__main__":
    unittest.main()
