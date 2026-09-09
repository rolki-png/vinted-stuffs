import path_setup  # noqa: F401
import copy
import io
import unittest
from unittest.mock import patch

import vinted_bot as bot


class ScoringPromptTests(unittest.TestCase):
    def setUp(self):
        self.watch = {
            "name": "Gym",
            "query": "gym shorts",
            "target_type": "men's gym shorts",
            "target_sizes": ["M", "L"],
            "notes": "technical shorts",
            "hunt_price": 100,
            "price_to": 180,
            "country": "ro",
        }
        self.items = [
            {
                "id": 1,
                "title": "Lululemon shorts",
                "price": {"amount": "80", "currency_code": "RON"},
                "brand_title": "Lululemon",
                "size_title": "L",
                "status": "Very good",
                "_profile": {"country_code": "ro"},
            }
        ]
        self.extracted = {
            "id": 1,
            "hunt_fit": True,
            "verification_concern": "none",
            "verification_reason": "",
            "reason": "useful",
            "personal_adjustments": {
                "fit_probability": 0,
                "usefulness": 0,
                "quality": 0,
                "condition": 0,
                "versatility": 0,
                "value": 0,
                "duplication_probability": 0,
            },
            "factors": {
                "fit_probability": {
                    "value": 1,
                    "confidence": 1,
                    "evidence": "L",
                },
                "usefulness": {
                    "value": 90,
                    "confidence": 1,
                    "evidence": "daily",
                },
                "quality": {
                    "value": 90,
                    "confidence": 1,
                    "evidence": "material",
                },
                "condition": {
                    "value": 90,
                    "confidence": 1,
                    "evidence": "very good",
                },
                "versatility": {
                    "value": 90,
                    "confidence": 1,
                    "evidence": "broad",
                },
                "equivalent_replacement_cost": {
                    "value": 400,
                    "currency": "RON",
                    "confidence": 1,
                    "evidence": "equivalent",
                },
                "duplication_probability": {
                    "value": 0,
                    "confidence": 1,
                    "evidence": "none",
                },
            },
        }

    def extraction_for(self, item_id):
        extraction = copy.deepcopy(self.extracted)
        extraction["id"] = item_id
        return extraction

    def test_prompt_requests_factors_but_not_buy_score(self):
        prompt = bot._extraction_prompt(self.watch, self.items)
        self.assertIn("equivalent_replacement_cost", prompt)
        self.assertIn("duplication_probability", prompt)
        self.assertIn(
            '0 only with confidence 0 and evidence beginning "unknown"',
            prompt,
        )
        self.assertNotIn('"buy_score"', prompt)
        self.assertIn("brand alone", prompt.lower())

    def test_unspecified_sizes_do_not_reject_accessories(self):
        watch = {**self.watch, "target_sizes": []}
        prompt = bot._extraction_prompt(watch, self.items)
        self.assertIn("Target sizes: unspecified", prompt)
        self.assertIn("do not reject for size", prompt.lower())
        self.assertIn("accessories", prompt.lower())

    def test_specified_sizes_still_reject_wrong_size(self):
        prompt = bot._extraction_prompt(self.watch, self.items)
        self.assertIn("incorrect sizes", prompt.lower())
        self.assertNotIn("do not reject for size", prompt.lower())

    def test_removed_scoring_prompt_alias_has_no_branch_callers(self):
        self.assertFalse(hasattr(bot, "_scoring_prompt"))

    def test_normalization_calculates_delivered_cost(self):
        scores = bot.normalize_extractions(
            [self.extracted],
            self.items,
            self.watch,
            {
                "checkout_fees": {
                    "ro": {
                        "estimated_shipping_ron": 15,
                        "buyer_fee_fixed_ron": 3,
                        "buyer_fee_pct": 0.05,
                    }
                }
            },
        )
        self.assertEqual(scores[0]["score_factors"]["delivered_cost_ron"], 102)
        self.assertEqual(scores[0]["score_version"], 2)

    def test_gateway_with_zero_valid_rows_falls_through_to_gemini(self):
        malformed = [{"id": 1, "deal_score": 10, "hunt_fit": True}]
        with (
            patch.object(bot, "score_with_gateway", return_value=malformed),
            patch.object(
                bot, "score_with_gemini", return_value=[self.extracted]
            ) as gemini,
        ):
            scores = bot.score_listings(
                self.watch,
                self.items,
                "gateway-key",
                object(),
                {},
            )
        gemini.assert_called_once()
        self.assertEqual(scores[0]["score_version"], 2)

    def test_gateway_keeps_valid_rows_when_siblings_are_missing_or_malformed(self):
        items = [
            self.items[0],
            {**self.items[0], "id": 2},
            {**self.items[0], "id": 3},
        ]
        gateway_rows = [
            self.extracted,
            {"id": 2, "factors": {"quality": "high"}},
        ]
        with (
            patch.object(bot, "score_with_gateway", return_value=gateway_rows),
            patch.object(bot, "score_with_gemini", return_value=[]) as gemini,
        ):
            scores = bot.score_listings(
                self.watch,
                items,
                "gateway-key",
                object(),
                {},
            )
        gemini.assert_not_called()
        self.assertEqual([score["id"] for score in scores], [1])

    def test_gateway_does_not_fall_through_after_valid_but_unpriced_row(self):
        unpriced = {
            **self.items[0],
            "price": {"amount": "unknown", "currency_code": "RON"},
        }
        stderr = io.StringIO()
        with (
            patch.object(
                bot, "score_with_gateway", return_value=[self.extracted]
            ),
            patch.object(bot, "score_with_gemini", return_value=[]) as gemini,
            patch("sys.stderr", new=stderr),
        ):
            scores = bot.score_listings(
                self.watch,
                [unpriced],
                "gateway-key",
                object(),
                {},
            )
        gemini.assert_not_called()
        self.assertEqual(scores, [])
        self.assertNotIn("Scored 0", stderr.getvalue())
        self.assertEqual(
            stderr.getvalue(),
            "Vercel AI Gateway returned 1 valid factor extraction(s), but "
            "matching rows were unpriced; leaving them unscored.\n",
        )

    def test_gemini_truthfully_logs_valid_but_unpriced_row(self):
        unpriced = {
            **self.items[0],
            "price": {"amount": "unknown", "currency_code": "RON"},
        }
        stderr = io.StringIO()
        with (
            patch.object(
                bot, "score_with_gemini", return_value=[self.extracted]
            ),
            patch("sys.stderr", new=stderr),
        ):
            scores = bot.score_listings(
                self.watch,
                [unpriced],
                "",
                object(),
                {},
            )
        self.assertEqual(scores, [])
        self.assertNotIn("Scored 0", stderr.getvalue())
        self.assertEqual(
            stderr.getvalue(),
            "Gemini returned 1 valid factor extraction(s), but matching rows "
            "were unpriced; leaving them unscored.\n",
        )

    def test_gemini_may_return_valid_subset_after_empty_gateway_result(self):
        items = [self.items[0], {**self.items[0], "id": 2}]
        with (
            patch.object(
                bot,
                "score_with_gateway",
                return_value=[{"id": 1, "factors": {}}],
            ),
            patch.object(
                bot,
                "score_with_gemini",
                return_value=[self.extracted],
            ),
        ):
            scores = bot.score_listings(
                self.watch,
                items,
                "gateway-key",
                object(),
                {},
            )
        self.assertEqual([score["id"] for score in scores], [1])

    def test_zero_unknown_replacement_cost_reaches_calculator_block_path(self):
        extraction = self.extraction_for(1)
        extraction["factors"]["equivalent_replacement_cost"] = {
            "value": 0,
            "currency": "RON",
            "confidence": 0,
            "evidence": "  UnKnOwN: no comparable evidence",
        }
        with patch.object(bot, "score_with_gateway", return_value=[extraction]):
            scores = bot.score_listings(
                self.watch,
                self.items,
                "gateway-key",
                None,
                {},
            )
        self.assertEqual(scores[0]["buy_score"], 0)
        self.assertEqual(scores[0]["verification_concern"], "block")

    def test_zero_replacement_with_unrelated_evidence_is_rejected(self):
        extraction = self.extraction_for(1)
        extraction["factors"]["equivalent_replacement_cost"] = {
            "value": 0,
            "currency": "RON",
            "confidence": 0,
            "evidence": "not provided",
        }
        with patch.object(bot, "score_with_gateway", return_value=[extraction]):
            scores = bot.score_listings(
                self.watch,
                self.items,
                "gateway-key",
                None,
                {},
            )
        self.assertEqual(scores, [])

    def test_negative_and_nonfinite_replacement_costs_are_rejected(self):
        invalid_rows = []
        for value in (-1, float("inf")):
            extraction = self.extraction_for(1)
            extraction["factors"]["equivalent_replacement_cost"]["value"] = value
            invalid_rows.append(extraction)
        for extraction in invalid_rows:
            with self.subTest(value=extraction["factors"]["equivalent_replacement_cost"]["value"]):
                with patch.object(
                    bot, "score_with_gateway", return_value=[extraction]
                ):
                    scores = bot.score_listings(
                        self.watch,
                        self.items,
                        "gateway-key",
                        None,
                        {},
                    )
                self.assertEqual(scores, [])

    def test_adjustment_validation_uses_configured_cap(self):
        over_cap = self.extraction_for(1)
        over_cap["personal_adjustments"]["quality"] = 6
        fallback = self.extraction_for(1)
        config = {"buy_scoring": {"personal_adjustment_cap": 5}}
        with (
            patch.object(bot, "score_with_gateway", return_value=[over_cap]),
            patch.object(
                bot, "score_with_gemini", return_value=[fallback]
            ) as gemini,
        ):
            scores = bot.score_listings(
                self.watch,
                self.items,
                "gateway-key",
                object(),
                config,
            )
        gemini.assert_called_once()
        self.assertEqual(scores[0]["score_factors"]["personal_adjustments"]["quality"], 0)

    def test_normalization_prefers_seller_country_for_solo_delivered_fees(self):
        item = {
            **self.items[0],
            "_profile": {"country_code": "hu"},
            "price": {"amount": "100", "currency_code": "RON"},
        }
        config = {
            "checkout_fees": {
                "ro": {
                    "estimated_shipping_ron": 1,
                    "buyer_fee_fixed_ron": 0,
                    "buyer_fee_pct": 0,
                },
                "hu": {
                    "estimated_shipping_ron": 18,
                    "buyer_fee_fixed_ron": 3,
                    "buyer_fee_pct": 0.05,
                },
            }
        }
        scores = bot.normalize_extractions(
            [self.extracted],
            [item],
            self.watch,
            config,
        )
        self.assertEqual(scores[0]["score_factors"]["delivered_cost_ron"], 126)

    def test_malformed_output_from_both_scorers_stays_unscored(self):
        malformed = [{"id": 1, "factors": {"quality": "high"}}]
        with (
            patch.object(bot, "score_with_gateway", return_value=malformed),
            patch.object(bot, "score_with_gemini", return_value=malformed),
        ):
            scores = bot.score_listings(
                self.watch,
                self.items,
                "gateway-key",
                object(),
                {},
            )
        self.assertEqual(scores, [])

    def test_omitted_personal_adjustments_are_treated_as_empty(self):
        payload = self.extraction_for(1)
        payload.pop("personal_adjustments")
        with patch.object(bot, "score_with_gateway", return_value=[payload]):
            scores = bot.score_listings(
                self.watch,
                self.items,
                "gateway-key",
                None,
                {},
            )
        self.assertEqual(len(scores), 1)
        self.assertEqual(scores[0]["score_factors"]["personal_adjustments"]["quality"], 0)


if __name__ == "__main__":
    unittest.main()
