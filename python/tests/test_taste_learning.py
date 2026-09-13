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
        self.assertEqual(tl.resolve_family("Broad dri-fit shorts M-L"), "gym")
        self.assertEqual(tl.resolve_family("Broad training shorts M-L"), "gym")

    def test_knitwear(self):
        self.assertEqual(tl.resolve_family("Johnstons of Elgin M-L"), "knitwear")

    def test_scoica(self):
        self.assertEqual(tl.resolve_family("Cybex Cloud G scoică"), "scoica")
        self.assertEqual(tl.resolve_family("Broad scoică auto i-Size"), "scoica")

    def test_watch_override(self):
        self.assertEqual(
            tl.resolve_family("Weird name", {"family": "gym"}),
            "gym",
        )

    def test_other(self):
        self.assertEqual(tl.resolve_family("Random thrift"), "other")


class TestPrompt(unittest.TestCase):
    def test_v2_outcome_line_uses_buy_score_and_band(self):
        line = tl._format_outcome_line(
            {
                "title": "Technical shorts",
                "score_version": 2,
                "buy_score": 88,
                "buy_band": "keep",
                "deal_score": 1,
                "value_band": "skip",
            }
        )
        self.assertIn("band=keep score=88/100", line)
        self.assertNotIn("band=skip score=1", line)

    def test_legacy_outcome_line_uses_deal_score_and_value_band(self):
        line = tl._format_outcome_line(
            {
                "title": "Technical shorts",
                "deal_score": 9,
                "value_band": "steal",
            }
        )
        self.assertIn("score=?", line)
        self.assertNotIn("/10", line)

    def test_includes_bought_not_parked(self):
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
        self.assertNotIn("Maybe", block)
        self.assertIn("Bought", block)

    def test_unreasoned_and_nonlearning_removes_are_excluded(self):
        block = tl.build_taste_prompt_block(
            [
                {"status": "removed", "reason_code": None, "title": "unknown"},
                {"status": "removed", "reason_code": "other", "title": "other"},
                {
                    "status": "removed",
                    "reason_code": "sold_unavailable",
                    "title": "sold",
                },
            ]
        )
        self.assertEqual(block, "")

    def test_three_consistent_reasons_emit_factor_scoped_guidance(self):
        rows = [
            {
                "status": "removed",
                "reason_code": "poor_value",
                "hunt_family": "gym",
                "title": f"shorts {i}",
                "brand": "Nike",
                "size": "L",
            }
            for i in range(3)
        ]
        block = tl.build_taste_prompt_block(rows)
        self.assertIn("poor_value", block)
        self.assertIn("value adjustment only", block)

    def test_two_same_reason_and_mixed_two_plus_one_do_not_emit_guidance(self):
        two_poor_value = [
            {
                "status": "removed",
                "reason_code": "poor_value",
                "hunt_family": "gym",
                "title": f"shorts {i}",
            }
            for i in range(2)
        ]
        self.assertEqual(tl.build_taste_prompt_block(two_poor_value), "")
        mixed_reasons = [
            *two_poor_value,
            {
                "status": "removed",
                "reason_code": "rarely_useful",
                "hunt_family": "gym",
                "title": "leggings",
            },
        ]
        self.assertEqual(tl.build_taste_prompt_block(mixed_reasons), "")

    def test_qualifying_reason_shows_three_examples_below_display_limit(self):
        rows = [
            {
                "status": "removed",
                "reason_code": "poor_value",
                "hunt_family": "gym",
                "title": f"shorts {i}",
            }
            for i in range(3)
        ]
        block = tl.build_taste_prompt_block(rows, per_polarity=1)
        for i in range(3):
            self.assertIn(f"shorts {i}", block)

    def test_empty_outcomes(self):
        self.assertEqual(tl.build_taste_prompt_block([]), "")


class TestTasteConfig(unittest.TestCase):
    def test_defaults(self):
        cfg = tl.taste_config({})
        self.assertTrue(cfg["enabled"])
        self.assertEqual(cfg["prompt_examples_per_polarity"], 5)
        self.assertNotIn("hard_suppress_min_removes", cfg)
        self.assertNotIn("hard_suppress_require_zero_bought", cfg)
        self.assertFalse(hasattr(tl, "hard_suppress"))


if __name__ == "__main__":
    unittest.main()
