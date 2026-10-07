import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cutup.config import Config, load_config


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_configuration_repr_never_contains_api_keys(self):
        config = Config(mistral_api_key="mistral-secret-sentinel", elasticsearch_api_key="elastic-secret-sentinel")
        self.assertNotIn("mistral-secret-sentinel", repr(config))
        self.assertNotIn("elastic-secret-sentinel", repr(config))

    def test_environment_overrides_local_file_without_interpolating_values(self):
        (self.root / ".env.local").write_text(
            "MISTRAL_API_KEY='literal-$HOME-$(not-a-command)'\n"
            "ELASTICSEARCH_URL=https://cluster.example:443/\n"
            "ELASTICSEARCH_API_KEY=file-value\n",
            encoding="utf-8",
        )
        with patch.dict(os.environ, {"ELASTICSEARCH_API_KEY": "environment-value"}):
            config = load_config(self.root)
        self.assertEqual(config.mistral_api_key, "literal-$HOME-$(not-a-command)")
        self.assertEqual(config.elasticsearch_api_key, "environment-value")
        self.assertEqual(config.elasticsearch_url, "https://cluster.example:443")
        self.assertTrue(config.configured)
        self.assertNotIn(config.mistral_api_key, repr(config))
        self.assertNotIn(config.elasticsearch_api_key, repr(config))

    def test_incomplete_setup_is_allowed_but_not_marked_configured(self):
        self.assertFalse(load_config(self.root).configured)
        with patch.dict(os.environ, {"MISTRAL_API_KEY": "local-test-placeholder"}):
            self.assertFalse(load_config(self.root).configured)

    def test_safe_elasticsearch_endpoints_are_accepted(self):
        for endpoint in ["https://cluster.example:443", "http://localhost:9200", "http://127.0.0.1:9200"]:
            with self.subTest(endpoint=endpoint):
                with patch.dict(os.environ, {"ELASTICSEARCH_URL": endpoint}):
                    self.assertEqual(load_config(self.root).elasticsearch_url, endpoint)

    def test_unsafe_or_malformed_endpoints_are_rejected(self):
        invalid = [
            "http://cluster.example:9200", "file:///tmp/index", "https:///missing-host",
            "https://username:password@cluster.example", "https://cluster.example?token=secret",
            "https://cluster.example#fragment", "https://cluster.example:bogus",
            "https://cluster.example:99999",
        ]
        for endpoint in invalid:
            with self.subTest(endpoint=endpoint):
                with patch.dict(os.environ, {"ELASTICSEARCH_URL": endpoint}):
                    with self.assertRaises(ValueError):
                        load_config(self.root)

    def test_endpoint_validation_does_not_echo_url_credentials(self):
        endpoint = "https://private-user:secret-url-password@cluster.example"
        with patch.dict(os.environ, {"ELASTICSEARCH_URL": endpoint}):
            with self.assertRaises(ValueError) as raised:
                load_config(self.root)
        self.assertNotIn("private-user", str(raised.exception))
        self.assertNotIn("secret-url-password", str(raised.exception))

    def test_index_name_cannot_target_other_indices_or_url_paths(self):
        for index in ["*", "_all", "real,other", "../other", "MyIndex", ""]:
            with self.subTest(index=index):
                with patch.dict(os.environ, {"ELASTICSEARCH_INDEX": index}):
                    with self.assertRaises(ValueError):
                        load_config(self.root)


if __name__ == "__main__":
    unittest.main()
