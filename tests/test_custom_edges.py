"""Integration edges for the photographed alphabet path; no live service calls."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from cutup.composer import FORM_HINTS, compose
from cutup.config import Config
from cutup.http_client import ProviderError
from cutup.provenance import plain_text, validate_source
from cutup.store import CorpusStore
from test_assembly import IMAGE, photo


class CustomEvidenceEdges(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = Config(project_root=self.root, data_dir=self.root / 'data',
                             mistral_api_key='fixture', elasticsearch_url='https://example.test',
                             elasticsearch_api_key='fixture')
        self.archive = self.config.data_dir / 'archive'
        self.archive.mkdir(parents=True)
        (self.archive / 'photo.jpg').write_bytes(IMAGE)
        self.mistral_patch = patch('cutup.composer.MistralClient')
        self.mistral = self.mistral_patch.start().return_value
        self.addCleanup(self.mistral_patch.stop)
        self.mistral.request.return_value = {'results': [{'categories': {}, 'category_scores': {}}]}

    def test_inventory_supplies_rare_letter_missing_from_semantic_results(self):
        with patch('cutup.composer.ElasticClient') as elastic:
            elastic.return_value.search.return_value = []
            elastic.return_value.glyph_sources.return_value = [photo('J')]
            result = compose(self.config, 'JJJ', 'custom')
        self.assertEqual(plain_text(result['lines']), 'JJJ')
        self.assertEqual(len(result['lines'][0][0]['pieces']), 3)
        self.assertEqual(result['sources'][0]['id'], 'photo')
        self.mistral.compose.assert_not_called()

    def test_letter_generation_repair_is_bounded_and_never_saves_unsupported_output(self):
        with patch('cutup.composer.ElasticClient') as elastic:
            elastic.return_value.search.return_value = [photo('A')]
            elastic.return_value.glyph_sources.return_value = []
            self.mistral.compose.return_value = {'lines': [['Z']]}
            with self.assertRaises(ProviderError) as error:
                compose(self.config, 'A city', 'poem')
            self.assertEqual(error.exception.code, 'provenance_rejected')
            self.assertEqual(self.mistral.compose.call_count, 2)
        self.assertFalse((self.config.data_dir / 'compositions').exists())

    def test_inventory_photo_digest_is_verified_before_assembly_or_chat(self):
        (self.archive / 'photo.jpg').write_bytes(b'replaced photo')
        with patch('cutup.composer.ElasticClient') as elastic:
            elastic.return_value.search.return_value = []
            elastic.return_value.glyph_sources.return_value = [photo('J')]
            with self.assertRaises(ProviderError) as error:
                compose(self.config, 'JJJ', 'custom')
            self.assertEqual(error.exception.code, 'source_image_changed')
            self.mistral.compose.assert_not_called()
        self.assertFalse((self.config.data_dir / 'compositions').exists())

    def test_synthetic_alphabet_cannot_supply_live_message_even_when_unreviewed_allowed(self):
        source = deepcopy(photo('J'))
        source['synthetic'] = True
        with patch('cutup.composer.ElasticClient') as elastic:
            elastic.return_value.search.return_value = [source]
            elastic.return_value.glyph_sources.return_value = []
            with self.assertRaises(ProviderError) as error:
                compose(self.config, 'JJJ', 'custom', include_unreviewed=True)
            self.assertEqual(error.exception.code, 'missing_character')
        self.assertFalse((self.config.data_dir / 'compositions').exists())


    def test_letter_only_source_requires_matching_local_photo(self):
        source = validate_source({**photo('J'), 'word_crops': []})
        with patch('cutup.composer.ElasticClient') as elastic:
            elastic.return_value.search.return_value = []
            elastic.return_value.glyph_sources.return_value = [source]
            result = compose(self.config, 'JJJ', 'custom')
            token = result['lines'][0][0]
            self.assertEqual(token['kind'], 'assembled')
            self.assertEqual(result['retrieved_source_ids'], ['photo'])
            self.assertTrue(all(piece['source_id'] == 'photo' and piece['crop'] for piece in token['pieces']))
            (self.archive / 'photo.jpg').unlink()
            with self.assertRaises(ProviderError) as error:
                compose(self.config, 'JJJ', 'custom')
            self.assertEqual(error.exception.code, 'source_image_changed')
            self.assertEqual(len(list((self.config.data_dir / 'compositions').glob('*.json'))), 1)

    def test_letter_paths_moderate_before_retrieval_and_before_saving(self):
        events = []
        def moderate(path, payload):
            events.append(('moderation', payload['input'][0]))
            return {'results': [{'categories': {}, 'category_scores': {}}]}
        self.mistral.request.side_effect = moderate
        for form, prompt, expected in [('custom', 'JJJ', 'JJJ'), ('headline', 'A city', 'JJJ')]:
            with self.subTest(form=form), patch('cutup.composer.ElasticClient') as elastic:
                events.clear()
                elastic.return_value.search.side_effect = lambda *args, **kwargs: events.append(('search', prompt)) or [photo('J')]
                elastic.return_value.glyph_sources.return_value = []
                self.mistral.compose.return_value = {'lines': [['JJJ']]}
                result = compose(self.config, prompt, form)
                self.assertEqual(events, [('moderation', prompt), ('search', prompt), ('moderation', expected)])
                self.assertEqual(sum(step['step'] == 'Moderation' for step in result['trace']), 2)

    def test_letter_paths_reject_flagged_brief_before_retrieval(self):
        self.mistral.request.return_value = {'results': [{'categories': {'violence': True}}]}
        with patch('cutup.composer.ElasticClient') as elastic:
            for form in ['custom', 'headline']:
                with self.subTest(form=form), self.assertRaisesRegex(ValueError, 'flagged the brief'):
                    compose(self.config, 'JJJ', form)
            elastic.assert_not_called()
        self.mistral.compose.assert_not_called()
        self.assertFalse((self.config.data_dir / 'compositions').exists())

    def test_letter_paths_reject_flagged_finished_text_without_saving(self):
        clean = {'results': [{'categories': {}}]}
        flagged = {'results': [{'categories': {'violence': True}}]}
        with patch('cutup.composer.ElasticClient') as elastic:
            elastic.return_value.search.return_value = [photo('J')]
            elastic.return_value.glyph_sources.return_value = []
            self.mistral.compose.return_value = {'lines': [['JJJ']]}
            for form in ['custom', 'headline']:
                self.mistral.request.side_effect = [clean, flagged]
                with self.subTest(form=form), self.assertRaises(ProviderError) as error:
                    compose(self.config, 'JJJ', form)
                self.assertEqual(error.exception.code, 'moderation_flagged')
        self.assertFalse((self.config.data_dir / 'compositions').exists())

    def test_letter_forms_keep_style_hints_and_single_client(self):
        with patch('cutup.composer.ElasticClient') as elastic, patch('cutup.composer.MistralClient') as factory:
            client = factory.return_value
            client.request.return_value = {'results': [{'categories': {}}]}
            client.compose.return_value = {'lines': [['JJJ']]}
            elastic.return_value.search.return_value = [photo('J')]
            elastic.return_value.glyph_sources.return_value = []
            for form in ['eviction-notice', 'shop-sign', 'headline']:
                factory.reset_mock()
                compose(self.config, 'A city', form)
                data = json.loads(client.compose.call_args.args[0][1]['content'])
                self.assertEqual(data['style_hint'], FORM_HINTS[form])
                factory.assert_called_once_with(self.config)

    def test_rearrange_letters_preserves_source_pool_without_elasticsearch(self):
        store = CorpusStore(self.config.data_dir)
        store.upsert(photo('J'))
        earlier_id = 'a' * 32
        store.save_composition({'id': earlier_id, 'retrieved_source_ids': ['photo']})
        self.mistral.compose.return_value = {'lines': [['JJJ']]}
        with patch('cutup.composer.ElasticClient') as elastic:
            result = compose(self.config, 'A city', 'headline', reuse_id=earlier_id)
            elastic.assert_not_called()
        self.assertEqual(result['retrieved_source_ids'], ['photo'])
        self.assertEqual(result['lines'][0][0]['kind'], 'assembled')
        self.assertEqual(self.mistral.request.call_count, 2)
        self.assertTrue(any(step['step'] == 'Reused vocabulary' for step in result['trace']))

    def test_rearrange_cannot_fetch_missing_letters_from_other_sources(self):
        store = CorpusStore(self.config.data_dir)
        store.upsert(photo('J'))
        earlier_id = 'a' * 32
        store.save_composition({'id': earlier_id, 'retrieved_source_ids': ['photo']})
        self.mistral.compose.return_value = {'lines': [['Z']]}
        with patch('cutup.composer.ElasticClient') as elastic:
            elastic.return_value.glyph_sources.return_value = [photo('Z')]
            with self.assertRaises(ProviderError) as error:
                compose(self.config, 'A city', reuse_id=earlier_id)
            self.assertEqual(error.exception.code, 'provenance_rejected')
            elastic.assert_not_called()
        self.assertEqual(len(list((self.config.data_dir / 'compositions').glob('*.json'))), 1)

    def test_moderation_off_remains_explicit_for_letter_composition(self):
        with patch('cutup.composer.ElasticClient') as elastic, patch.dict('os.environ', {'CUTUP_MODERATION': 'off'}):
            elastic.return_value.search.return_value = [photo('J')]
            elastic.return_value.glyph_sources.return_value = []
            result = compose(self.config, 'JJJ', 'custom')
        self.mistral.request.assert_not_called()
        self.assertTrue(any('Moderation is switched off' in warning for warning in result['warnings']))


if __name__ == '__main__':
    unittest.main()
