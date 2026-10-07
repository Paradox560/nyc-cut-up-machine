import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cutup.glyphs import extract_source_letters, parse_makebox


class GlyphExtractionTests(unittest.TestCase):
    def test_makebox_bottom_left_coordinates_map_to_original_photo(self):
        parent = {"x": 100, "y": 200, "width": 80, "height": 60}
        result = parse_makebox("A 5 10 25 50 0\nB 30 0 70 60 0\nX -1 0 4 9 0\nY 0 0 99 9 0", parent, 1000, 1000)
        self.assertEqual(result, [
            {"text": "A", "x": 105, "y": 210, "width": 20, "height": 40},
            {"text": "B", "x": 130, "y": 200, "width": 40, "height": 60},
        ])

    def test_letters_are_rejected_when_recognized_word_does_not_match(self):
        digest = "a" * 64
        source = {"id": "test", "title": "Synthetic test fixture", "image_url": "/archive/test.jpg",
                  "reviewed": True, "ocr_text": "CAT", "image_sha256": digest,
                  "word_crops": [{"word_id": "test:word", "text": "CAT", "x": 10, "y": 20,
                                  "width": 90, "height": 40}]}
        results = [subprocess.CompletedProcess([], 0, "", ""),
                   subprocess.CompletedProcess([], 0, "C 0 0 20 40 0\nO 25 0 45 40 0\nT 50 0 70 40 0", "")]
        with tempfile.TemporaryDirectory() as directory, \
             patch("cutup.glyphs.image_metadata", return_value={"image_width": 1000, "image_height": 1000, "image_sha256": digest}), \
             patch("cutup.glyphs.subprocess.run", side_effect=results):
            result = extract_source_letters(source, Path(directory) / "test.jpg", Path(directory),
                                             tesseract="test-tesseract", sips="test-sips")
        self.assertEqual(result["letter_crops"], [])
        self.assertEqual(result["rejected_words"], [{"word": "CAT", "recognized": "COT"}])


if __name__ == "__main__":
    unittest.main()
