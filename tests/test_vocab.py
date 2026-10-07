import unittest
from unittest.mock import patch

from cutup.config import Config
from cutup.elastic import ElasticClient
from cutup.provenance import build_words


def source(identifier, text, title="Photo"):
    return {"id": identifier, "title": title, "words": build_words(identifier, text)}


class FindWordsTests(unittest.TestCase):
    def setUp(self):
        self.client = ElasticClient(Config(elasticsearch_url="https://x.example", elasticsearch_api_key="k"))

    def test_hits_are_ranked_from_one_and_words_are_trimmed(self):
        long_text = " ".join(f"WORD{i}" for i in range(30))
        with patch.object(ElasticClient, "search", return_value=[source("a", "OPEN ALL NIGHT", "Whitehall"), source("b", long_text)]) as search:
            results = self.client.find_words("night", limit=5)
        search.assert_called_once_with("night", include_unreviewed=False, limit=5)
        self.assertEqual([r["rank"] for r in results], [1, 2])
        self.assertEqual(results[0]["title"], "Whitehall")
        self.assertEqual(results[0]["words"], ["OPEN", "ALL", "NIGHT"])
        self.assertEqual(len(results[1]["words"]), 12)

    def test_numbers_are_not_listed_as_words(self):
        with patch.object(ElasticClient, "search", return_value=[source("a", "OPEN 24 HOURS")]):
            self.assertEqual(self.client.find_words("open")[0]["words"], ["OPEN", "HOURS"])

    def test_only_reviewed_photographs_are_searched(self):
        with patch.object(ElasticClient, "search", return_value=[]) as search:
            self.assertEqual(self.client.find_words("anything"), [])
        self.assertFalse(search.call_args.kwargs["include_unreviewed"])


if __name__ == "__main__":
    unittest.main()
