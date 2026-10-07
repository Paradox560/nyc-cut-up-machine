import unittest

from cutup.provenance import (
    ProvenanceError,
    build_words,
    plain_text,
    resolve_lines,
    validate_source,
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


if __name__ == "__main__":
    unittest.main()
