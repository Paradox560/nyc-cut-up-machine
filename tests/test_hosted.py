from dataclasses import replace
from email.message import Message
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from api.index import handler
from cutup.config import Config, load_config
from cutup.hosted_store import HostedStore
from cutup.http_client import ProviderError
from cutup.store import CorpusStore, application_store


class HostedTests(unittest.TestCase):
    def test_local_store_remains_local_and_hosted_uses_packaged_data(self):
        with TemporaryDirectory() as directory, patch.dict('os.environ', {'VERCEL': '1'}):
            config = load_config(Path(directory))
            self.assertEqual(config.data_dir, Path(directory) / 'deployment_data')
            self.assertIsInstance(application_store(config), HostedStore)
            self.assertIs(type(application_store(replace(config, hosted=False))), CorpusStore)

    def test_composition_survives_distinct_store_instances_without_disk_writes(self):
        with TemporaryDirectory() as directory, patch('cutup.hosted_store.ElasticClient') as factory:
            config = Config(data_dir=Path(directory), hosted=True)
            client = factory.return_value
            client.request.return_value = {}
            composition = {'id': 'a' * 32, 'exact_text': 'Hello NYC', 'lines': [], 'sources': []}
            HostedStore(config).save_composition(composition)
            saved_payload = client.request.call_args.kwargs['payload']
            client.request.return_value = {'_source': saved_payload}
            self.assertEqual(HostedStore(config).get_composition(composition['id']), composition)
            self.assertEqual(list(Path(directory).iterdir()), [])
            with self.assertRaises(ProviderError):
                HostedStore(config).upsert({'id': 'photo'})

    def test_first_composition_creates_disabled_object_mapping(self):
        with patch('cutup.hosted_store.ElasticClient') as factory:
            client = factory.return_value
            client.request.side_effect = [ProviderError('missing', code='elasticsearch_404'), {}, {}]
            HostedStore(Config(hosted=True)).save_composition({'id': 'b' * 32})
            mapping = client.request.call_args_list[1].kwargs['payload']['mappings']
            self.assertFalse(mapping['properties']['composition']['enabled'])
            self.assertEqual(mapping['dynamic'], 'strict')

    def test_missing_composition_and_invalid_identifier_do_not_write(self):
        with patch('cutup.hosted_store.ElasticClient') as factory:
            store = HostedStore(Config(hosted=True))
            self.assertIsNone(store.get_composition('../secret'))
            factory.return_value.request.assert_not_called()
            factory.return_value.request.side_effect = ProviderError('missing', code='elasticsearch_404')
            self.assertIsNone(store.get_composition('c' * 32))

    def test_hosted_origin_requires_known_https_origin(self):
        instance = handler.__new__(handler)
        instance.headers = Message()
        instance.headers['Host'] = 'streetscript.vercel.app'
        instance.headers['Origin'] = 'https://streetscript.vercel.app'
        with patch.dict('os.environ', {'VERCEL_URL': 'streetscript.vercel.app'}, clear=True):
            instance.checked_origin()
            instance.headers.replace_header('Origin', 'https://evil.example')
            with self.assertRaises(ProviderError): instance.checked_origin()
            instance.headers.replace_header('Origin', 'https://streetscript.vercel.app')
            instance.headers.replace_header('Host', 'evil.example')
            with self.assertRaises(ProviderError): instance.checked_origin()

    def test_rewrite_preserves_word_search_query(self):
        instance = handler.__new__(handler)
        instance.server = SimpleNamespace()
        instance.path = '/api/index?__route=words&q=lost+love'
        with patch('cutup.server.Handler.dispatch') as dispatch:
            instance.dispatch('GET')
        self.assertEqual(instance.path, '/api/words?q=lost+love')
        dispatch.assert_called_once_with('GET')


if __name__ == '__main__':
    unittest.main()
