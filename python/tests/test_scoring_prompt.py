import path_setup  # noqa: F401
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

    def test_prompt_requests_factors_but_not_buy_score(self):
        prompt = bot._extraction_prompt(self.watch, self.items)
        self.assertIn("equivalent_replacement_cost", prompt)
        self.assertIn("duplication_probability", prompt)
        self.assertNotIn('"buy_score"', prompt)
        self.assertIn("brand alone", prompt.lower())

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

    def test_malformed_gateway_factors_fall_through_to_gemini(self):
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


if __name__ == "__main__":
    unittest.main()
