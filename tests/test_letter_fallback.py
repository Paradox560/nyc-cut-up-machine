from pathlib import Path
import unittest
from unittest.mock import Mock

from cutup.composer import compose_with_letters
from cutup.config import Config
from cutup.http_client import ProviderError
from cutup.provenance import build_words, validate_source, validate_assembled_lines


def source():
    record = {'id': 'fallback-photo', 'reviewed': True, 'ocr_text': 'NEW YORK LOVE',
              'image_url': '/archive/fallback-photo.jpg', 'image_width': 400, 'image_height': 200,
              'image_sha256': 'a' * 64}
    record['word_crops'] = [{'word_id': word['id'], 'text': word['text'], 'x': i * 80,
                             'y': 20, 'width': 70, 'height': 40, 'method': 'test', 'confidence': 100}
                            for i, word in enumerate(build_words(record['id'], record['ocr_text']))]
    return validate_source(record)


class LetterFallbackTests(unittest.TestCase):
    def test_missing_punctuation_retries_with_enum_and_verifies_original_words(self):
        client = Mock()
        client.compose.side_effect = [{'lines': [['NEW', 'YORK!']]}, {'lines': [['NEW', 'YORK'], ['LOVE']]}]
        trace = []
        photo = source()
        lines = compose_with_letters(Config(), client, 'A city headline', 'headline', [photo], trace)
        self.assertEqual(client.compose.call_count, 2)
        self.assertIsNone(client.compose.call_args_list[0].kwargs['allowed_words'])
        self.assertEqual(client.compose.call_args_list[1].kwargs['allowed_words'], ['NEW', 'YORK', 'LOVE'])
        self.assertEqual(lines, [[photo['words'][0], photo['words'][1]], [photo['words'][2]]])
        self.assertEqual(validate_assembled_lines(lines, [photo]), lines)
        self.assertIn("'!'", trace[0]['detail'])
        self.assertIn('strict whole-word', trace[0]['detail'])

    def test_fallback_rejects_unsupported_word_without_third_call(self):
        client = Mock()
        client.compose.side_effect = [{'lines': [['missing!']]}, {'lines': [['UNSOURCED']]}]
        with self.assertRaises(ProviderError):
            compose_with_letters(Config(), client, 'A city headline', 'headline', [source()], [])
        self.assertEqual(client.compose.call_count, 2)

    def test_custom_message_still_fails_exactly_without_rewriting(self):
        client = Mock()
        with self.assertRaises(ProviderError) as error:
            compose_with_letters(Config(), client, 'NEW YORK!', 'custom', [source()], [])
        self.assertEqual(error.exception.code, 'missing_character')
        client.compose.assert_not_called()
