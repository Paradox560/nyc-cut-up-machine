import unittest
from unittest.mock import MagicMock, patch

from cutup import moderation


def response(categories, scores=None):
    return {"results": [{"categories": categories, "category_scores": scores or {k: 0.5 for k in categories}}]}


class ModerationTests(unittest.TestCase):
    def test_clean_text_is_not_flagged(self):
        verdict = moderation.interpret(response({"sexual": False, "violence_and_threats": False}, {"sexual": 0.01, "violence_and_threats": 0.3}))
        self.assertFalse(verdict["flagged"])
        self.assertEqual(verdict["categories"], [])
        self.assertEqual(verdict["top"], {"category": "violence_and_threats", "score": 0.3})

    def test_flagged_categories_are_listed_sorted(self):
        verdict = moderation.interpret(response({"sexual": True, "hate_and_discrimination": True, "pii": False}))
        self.assertTrue(verdict["flagged"])
        self.assertEqual(verdict["categories"], ["hate_and_discrimination", "sexual"])

    def test_malformed_responses_raise_instead_of_passing(self):
        for bad in [None, {}, {"results": []}, {"results": [None]}, "ok", 5]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    moderation.interpret(bad)

    def test_check_text_sends_model_and_truncates_long_text(self):
        client = MagicMock()
        client.request.return_value = response({"sexual": False})
        moderation.check_text(client, "x" * 20000)
        path, payload = client.request.call_args.args
        self.assertEqual(path, "/moderations")
        self.assertEqual(payload["model"], "mistral-moderation-latest")
        self.assertEqual(len(payload["input"][0]), 8000)

    def test_enabled_flag(self):
        with patch.dict("os.environ", {}, clear=False):
            self.assertTrue(moderation.enabled())
        for value in ["off", "OFF", " off "]:
            with patch.dict("os.environ", {"CUTUP_MODERATION": value}):
                self.assertFalse(moderation.enabled())
        with patch.dict("os.environ", {"CUTUP_MODERATION": "on"}):
            self.assertTrue(moderation.enabled())


if __name__ == "__main__":
    unittest.main()
