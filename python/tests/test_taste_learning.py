# python/tests/test_taste_learning.py
import path_setup  # noqa: F401
import unittest

import taste_learning as tl


class TestFamily(unittest.TestCase):
    def test_maternity(self):
        self.assertEqual(tl.resolve_family("Seraphine maternity XL-L/XL"), "maternity")

    def test_sneakers(self):
        self.assertEqual(tl.resolve_family("New Balance 990 size 43"), "sneakers")

    def test_gym(self):
        self.assertEqual(tl.resolve_family("Lululemon gym M-L"), "gym")

    def test_knitwear(self):
        self.assertEqual(tl.resolve_family("Johnstons of Elgin M-L"), "knitwear")

    def test_watch_override(self):
        self.assertEqual(
            tl.resolve_family("Weird name", {"family": "gym"}),
            "gym",
        )

    def test_other(self):
        self.assertEqual(tl.resolve_family("Random thrift"), "other")


class TestPrompt(unittest.TestCase):
    def test_includes_bought_and_removed_not_parked(self):
        block = tl.build_taste_prompt_block(
            [
                {
                    "status": "bought",
                    "title": "Good shorts",
                    "brand": "Nike",
                    "size": "L",
                    "price_ron": 40,
                    "value_band": "steal",
                    "deal_score": 9,
                },
                {
                    "status": "removed",
                    "title": "Trash tee",
                    "brand": "NoName",
                    "size": "M",
                    "price_ron": 80,
                    "value_band": "skip",
                    "deal_score": 3,
                },
                {
                    "status": "parked",
                    "title": "Maybe",
                    "brand": "X",
                    "size": "L",
                    "price_ron": 50,
                    "value_band": "hunt",
                    "deal_score": 8,
                },
            ]
        )
        self.assertIn("Good shorts", block)
        self.assertIn("Trash tee", block)
        self.assertNotIn("Maybe", block)
        self.assertIn("Bought", block)
        self.assertIn("Removed", block)

    def test_empty_outcomes(self):
        self.assertEqual(tl.build_taste_prompt_block([]), "")


class TestHardSuppress(unittest.TestCase):
    def test_suppress_after_threshold(self):
        outcomes = [
            {"status": "removed", "hunt_family": "gym", "brand": "Nike", "size": "L"},
            {"status": "removed", "hunt_family": "gym", "brand": "Nike", "size": "L"},
            {"status": "removed", "hunt_family": "gym", "brand": "nike", "size": "L"},
        ]
        cand = {"hunt_family": "gym", "brand": "Nike", "size": "L"}
        self.assertTrue(tl.hard_suppress(cand, outcomes, min_removes=3))

    def test_bought_blocks_suppress(self):
        outcomes = [
            {"status": "removed", "hunt_family": "gym", "brand": "Nike", "size": "L"},
            {"status": "removed", "hunt_family": "gym", "brand": "Nike", "size": "L"},
            {"status": "removed", "hunt_family": "gym", "brand": "Nike", "size": "L"},
            {"status": "bought", "hunt_family": "gym", "brand": "Nike", "size": "L"},
        ]
        cand = {"hunt_family": "gym", "brand": "Nike", "size": "L"}
        self.assertFalse(tl.hard_suppress(cand, outcomes, min_removes=3))

    def test_no_brand_never_suppress(self):
        outcomes = [
            {"status": "removed", "hunt_family": "gym", "brand": "", "size": "L"}
        ] * 5
        self.assertFalse(
            tl.hard_suppress({"hunt_family": "gym", "brand": "", "size": "L"}, outcomes)
        )

    def test_cross_family_ignored(self):
        outcomes = [
            {
                "status": "removed",
                "hunt_family": "maternity",
                "brand": "Nike",
                "size": "L",
            }
        ] * 5
        self.assertFalse(
            tl.hard_suppress(
                {"hunt_family": "gym", "brand": "Nike", "size": "L"}, outcomes
            )
        )


class TestTasteConfig(unittest.TestCase):
    def test_defaults(self):
        cfg = tl.taste_config({})
        self.assertTrue(cfg["enabled"])
        self.assertEqual(cfg["prompt_examples_per_polarity"], 5)
        self.assertEqual(cfg["hard_suppress_min_removes"], 3)
        self.assertTrue(cfg["hard_suppress_require_zero_bought"])


if __name__ == "__main__":
    unittest.main()
