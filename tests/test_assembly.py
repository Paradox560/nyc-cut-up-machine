from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cutup.assembly import assemble_text, assemble_model_lines, pieces
from cutup.composer import compose
from cutup.config import Config
from cutup.http_client import ProviderError
from cutup.provenance import (ProvenanceError, build_words, build_glyph_id, validate_source,
                              validate_assembled_lines, verify_crop_images, plain_text)
from cutup.store import CorpusStore

IMAGE = b'isolated photographic evidence fixture'


def photo(chars='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz.,!?0123456789', text='NEW YORK'):
    s = {'id': 'photo', 'ocr_text': text, 'reviewed': True, 'image_url': '/archive/photo.jpg',
         'image_width': 2000, 'image_height': 1000, 'image_sha256': sha256(IMAGE).hexdigest()}
    s['word_crops'] = [{'word_id': w['id'], 'text': w['text'], 'x': 100, 'y': 300, 'width': 200, 'height': 80,
                        'method': 'manual', 'confidence': 0} for w in build_words(s['id'], text)]
    s['letter_crops'] = []
    for index, char in enumerate(chars):
        box = {'x': index * 20, 'y': 20, 'width': 18, 'height': 40, 'method': 'manual', 'confidence': 0}
        s['letter_crops'].append({'id': build_glyph_id(s['id'], s['image_sha256'], char, box),
                                 'text': char, 'source_id': s['id'], **box})
    return validate_source(s)


class GlyphProvenanceTests(unittest.TestCase):
    def test_glyph_identity_binds_character_pixels_and_original_photo(self):
        original = photo('A')
        for change in [{'text': 'B'}, {'x': 1}, {'source_id': 'another'}, {'id': 'fabricated'}]:
            mutated = deepcopy(original)
            mutated['letter_crops'][0].update(change)
            with self.subTest(change=change), self.assertRaises(ProvenanceError):
                validate_source(mutated)
        altered = deepcopy(original)
        altered['image_sha256'] = 'f' * 64
        with self.assertRaises(ProvenanceError): validate_source(altered)

    def test_cached_letters_cannot_supply_forged_glyph(self):
        source = photo('A')
        source['letters'] = [{'text': 'X', 'crop': {'x': 0}}]
        self.assertEqual([g['text'] for g in validate_source(source)['letters']], ['A'])

    def test_rejects_non_character_and_malformed_bounds(self):
        for change in [{'text': 'AB'}, {'text': ' '}, {'text': '\n'}, {'x': -1}, {'width': 0}, {'height': True}, {'confidence': float('nan')}]:
            source = photo('A');source['letter_crops'][0].update(change)
            with self.subTest(change=change), self.assertRaises(ProvenanceError): validate_source(source)

    def test_parent_word_must_exist_and_contain_character(self):
        source = photo('A')
        source['letter_crops'][0]['parent_word_id'] = source['words'][0]['id']
        with self.assertRaises(ProvenanceError): validate_source(source)
        source['letter_crops'][0]['parent_word_id'] = 'superseded-token'
        self.assertEqual(validate_source(source)['letters'], [])


class AssemblyTests(unittest.TestCase):
    def test_prefers_original_whole_word_and_spells_obscure_word(self):
        s = photo()
        row = assemble_text('NEW quixotic', [s])[0]
        self.assertEqual(row[0]['id'], s['words'][0]['id'])
        self.assertEqual(row[1]['kind'], 'assembled')
        self.assertEqual(''.join(g['text'] for g in row[1]['pieces']), 'quixotic')
        self.assertTrue(all(g['crop'] for g in row[1]['pieces']))

    def test_preserves_spacing_line_breaks_and_adjacent_punctuation(self):
        text = '  New\tYork,\n\nquixotic!'
        result = assemble_text(text, [photo()])
        self.assertEqual(plain_text(result), text)
        self.assertEqual(result[1], [])
        self.assertEqual(result[0][-1]['prefix'], '')

    def test_lowercase_message_can_use_uppercase_photographed_letters(self):
        result = assemble_text('jazzy', [photo('JAZY')])
        self.assertEqual(''.join(p['text'] for p in result[0][0]['pieces']), 'JAZZY')
        self.assertEqual(plain_text(result), 'jazzy')

    def test_missing_glyph_reports_all_missing_characters_without_retyping(self):
        with self.assertRaisesRegex(ProvenanceError, "'Z'.*'😀'"):
            assemble_text('AZ😀', [photo('A')])

    def test_unreviewed_sources_never_supply_words_or_letters(self):
        s = photo('A');s['reviewed'] = False
        with self.assertRaises(ProvenanceError): assemble_text('A', [s])
        self.assertEqual(plain_text(assemble_text('A', [s], require_reviewed=False)), 'A')

    def test_piece_objects_are_independent_across_repeated_characters(self):
        row = assemble_text('AAA', [photo('A')])[0]
        row[0]['pieces'][0]['crop']['x'] = 999
        self.assertNotEqual(row[0]['pieces'][1]['crop']['x'], 999)

    def test_custom_limits_and_control_characters_are_enforced(self):
        for text in ['', '  ', 'A' * 301, '\n' * 20 + 'A', 'A\x00']:
            with self.subTest(text=repr(text)[:30]), self.assertRaises(ProvenanceError): assemble_text(text, [photo()])

    def test_model_cannot_inject_crop_coordinates_or_extra_fields(self):
        for payload in [{'lines': [['hello world']]}, {'lines': [[{'text': 'A', 'crop': {}}]]}, {'lines': [['A']], 'crop': {}}, {'lines': [[]]}]:
            with self.subTest(payload=payload), self.assertRaises(ProvenanceError): assemble_model_lines(payload, [photo()])

    def test_generated_letter_words_keep_the_original_hundred_word_limit(self):
        payload = {'lines': [['J'] * 20] * 5}
        self.assertEqual(sum(map(len, assemble_model_lines(payload, [photo('J')]))), 100)
        with self.assertRaisesRegex(ProvenanceError, '100 words'):
            assemble_model_lines({'lines': payload['lines'] + [['J']]}, [photo('J')])


class AssembledProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.source = photo('AB')
        self.lines = assemble_text('BA', [self.source])

    def test_accepted_letters_retain_each_registered_photo_crop_and_assembled_mark(self):
        result = validate_assembled_lines(self.lines, [self.source])
        self.assertEqual(result[0][0]['kind'], 'assembled')
        self.assertEqual(plain_text(result), 'BA')
        evidence = {glyph['id']: glyph for glyph in self.source['letters']}
        for glyph in result[0][0]['pieces']:
            self.assertEqual(glyph, evidence[glyph['id']])
            self.assertEqual(glyph['source_id'], self.source['id'])
            self.assertTrue(glyph['crop'])
        result[0][0]['pieces'][0]['crop']['x'] = 999
        self.assertNotEqual(self.lines[0][0]['pieces'][0]['crop']['x'], 999)

    def test_unknown_letter_is_rejected_even_with_plausible_photo_and_crop(self):
        forged = deepcopy(self.lines)
        forged[0][0]['pieces'][0]['id'] = 'photo:g:unknown'
        with self.assertRaises(ProvenanceError):
            validate_assembled_lines(forged, [self.source])

    def test_missing_or_mismatched_letter_evidence_is_rejected(self):
        for field in ('id', 'source_id', 'crop'):
            candidate = deepcopy(self.lines)
            del candidate[0][0]['pieces'][0][field]
            with self.subTest(missing=field), self.assertRaises(ProvenanceError):
                validate_assembled_lines(candidate, [self.source])
        for change in ({'source_id': 'missing-photo'}, {'text': 'Z'},
                       {'crop': {**self.source['letters'][1]['crop'], 'x': 21}},
                       {'crop': {**self.source['letters'][1]['crop'], 'x': 20.0}}):
            candidate = deepcopy(self.lines)
            candidate[0][0]['pieces'][0].update(change)
            with self.subTest(change=change), self.assertRaises(ProvenanceError):
                validate_assembled_lines(candidate, [self.source])
        for sources in ([], [dict(self.source, letter_crops=[])]):
            with self.subTest(sources=sources), self.assertRaises(ProvenanceError):
                validate_assembled_lines(self.lines, sources)

    def test_assembled_spelling_and_marking_cannot_hide_unsourced_letters(self):
        for change in ({'text': 'CA'}, {'text': 'BAZ'}, {'pieces': []},
                       {'kind': 'word'}, {'requested_text': 'UNSOURCED'}):
            candidate = deepcopy(self.lines)
            candidate[0][0].update(change)
            with self.subTest(change=change), self.assertRaises(ProvenanceError):
                validate_assembled_lines(candidate, [self.source])
        candidate = deepcopy(self.lines)
        del candidate[0][0]['kind']
        with self.assertRaises(ProvenanceError):
            validate_assembled_lines(candidate, [self.source])

    def test_whole_words_still_require_original_word_crop_evidence(self):
        lines = assemble_text('NEW', [self.source])
        self.assertEqual(validate_assembled_lines(lines, [self.source]), lines)
        for change in ({'text': 'INVENTED'}, {'requested_text': 'INVENTED'}, {'crop': None}):
            candidate = deepcopy(lines)
            candidate[0][0].update(change)
            with self.subTest(change=change), self.assertRaises(ProvenanceError):
                validate_assembled_lines(candidate, [self.source])

    def test_duplicate_photo_identifiers_are_rejected_by_assembly_and_validator(self):
        sources = [self.source, deepcopy(self.source)]
        for operation in (lambda: assemble_text('BA', sources),
                          lambda: validate_assembled_lines(self.lines, sources)):
            with self.assertRaises(ProvenanceError): operation()

    def test_unreviewed_and_synthetic_letters_do_not_become_verified_sources(self):
        for change in ({'reviewed': False}, {'synthetic': True}):
            with self.subTest(change=change), self.assertRaises(ProvenanceError):
                validate_assembled_lines(self.lines, [{**self.source, **change}])
        with self.assertRaises(ProvenanceError):
            validate_assembled_lines(self.lines, [{**self.source, 'synthetic': True}],
                                     require_reviewed=False)

    def test_letter_only_sources_require_matching_local_photo_bytes(self):
        source = {**self.source, 'ocr_text': '', 'word_crops': []}
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            archive = data / 'archive'
            archive.mkdir()
            image = archive / 'photo.jpg'
            image.write_bytes(IMAGE)
            verify_crop_images([source], data)
            self.assertEqual(validate_assembled_lines(self.lines, [source]), self.lines)
            for replacement in (b'changed photograph', None):
                if replacement is None:
                    image.unlink()
                else:
                    image.write_bytes(replacement)
                with self.subTest(replacement=replacement), self.assertRaises(ProvenanceError):
                    verify_crop_images([source], data)


class CustomCompositionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.config = Config(project_root=self.root,data_dir=self.root/'data',mistral_api_key='test',elasticsearch_url='https://example.test',elasticsearch_api_key='test')
        archive = self.config.data_dir/'archive';archive.mkdir(parents=True);(archive/'photo.jpg').write_bytes(IMAGE)
        self.source = photo()
        self.clean = {'results': [{'categories': {}, 'category_scores': {}}]}

    def test_custom_keeps_verbatim_message_uses_elasticsearch_and_never_rewrites_with_chat(self):
        with patch('cutup.composer.ElasticClient') as elastic, patch('cutup.composer.MistralClient') as mistral:
            mistral.return_value.request.return_value = self.clean
            elastic.return_value.search.return_value = [self.source]
            elastic.return_value.glyph_sources.return_value = []
            text = '  New York,\nquixotic!  '
            result = compose(self.config,text,'custom')
            self.assertEqual(result['exact_text'],text)
            self.assertEqual(result['prompt'],text)
            mistral.return_value.compose.assert_not_called()
            elastic.return_value.search.assert_called_once_with(text,include_unreviewed=False)
            saved = CorpusStore(self.config.data_dir).get_composition(result['id'])
            self.assertEqual(saved['exact_text'],text)
            self.assertGreater(result['stats']['letter_cuts'],0)

    def test_generated_forms_can_spell_novel_words_from_photo_letters(self):
        with patch('cutup.composer.ElasticClient') as elastic, patch('cutup.composer.MistralClient') as mistral:
            mistral.return_value.request.return_value = self.clean
            elastic.return_value.search.return_value = [self.source]
            elastic.return_value.glyph_sources.return_value = []
            mistral.return_value.compose.return_value = {'lines': [['quixotic', 'city']]}
            result = compose(self.config,'A curious city','poem')
            self.assertEqual(plain_text(result['lines']),'quixotic city')
            self.assertTrue(all(p['crop'] for row in result['lines'] for token in row for p in pieces(token)))

    def test_custom_missing_character_fails_without_saving(self):
        with patch('cutup.composer.ElasticClient') as elastic, patch('cutup.composer.MistralClient') as mistral:
            mistral.return_value.request.return_value = self.clean
            elastic.return_value.search.return_value = [photo('A')]
            elastic.return_value.glyph_sources.return_value = []
            with self.assertRaises(ProviderError) as error: compose(self.config,'😀','custom')
            self.assertEqual(error.exception.code,'missing_character')
            self.assertEqual(list((self.config.data_dir/'compositions').glob('*')),[])

    def test_synthetic_demo_does_not_pretend_to_build_custom_photographic_message(self):
        with self.assertRaises(ProviderError) as error: compose(self.config,'hello','custom',demo=True)
        self.assertEqual(error.exception.code,'custom_requires_archive')


if __name__ == '__main__': unittest.main()
