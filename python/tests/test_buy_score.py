import path_setup  # noqa: F401
import json
import unittest
from pathlib import Path

import buy_score as bs


def extraction(**overrides):
    factors = {
        "fit_probability": {"value": 0.95, "confidence": 0.9, "evidence": "target size"},
        "usefulness": {"value": 92, "confidence": 0.9, "evidence": "daily role"},
        "quality": {"value": 90, "confidence": 0.8, "evidence": "documented material"},
        "condition": {"value": 95, "confidence": 0.9, "evidence": "new without tags"},
        "versatility": {"value": 90, "confidence": 0.8, "evidence": "several settings"},
        "equivalent_replacement_cost": {
            "value": 450,
            "currency": "RON",
            "confidence": 0.8,
            "evidence": "conservative equivalent",
        },
        "duplication_probability": {"value": 0.05, "confidence": 0.8, "evidence": "new role"},
    }
    factors.update(overrides.pop("factors", {}))
    return {
        "id": 1,
        "hunt_fit": True,
        "verification_concern": "none",
        "verification_reason": "",
        "reason": "strong daily purchase",
        "factors": factors,
        "personal_adjustments": overrides.pop("personal_adjustments", {}),
        **overrides,
    }


class BuyScoreTests(unittest.TestCase):
    def test_higher_delivered_cost_cannot_improve_score(self):
        low = bs.calculate_buy_score(extraction(), 100, {})
        high = bs.calculate_buy_score(extraction(), 200, {})
        self.assertGreater(low["buy_score"], high["buy_score"])

    def test_missing_quality_shrinks_to_neutral_and_lowers_confidence(self):
        known = bs.calculate_buy_score(extraction(), 100, {})
        missing = extraction(
            factors={"quality": {"value": 50, "confidence": 0, "evidence": "unknown"}}
        )
        unknown = bs.calculate_buy_score(missing, 100, {})
        self.assertLess(unknown["buy_score"], known["buy_score"])
        self.assertLess(unknown["score_confidence"], known["score_confidence"])

    def test_brand_is_not_a_calculator_input(self):
        plain = bs.calculate_buy_score(extraction(brand="H&M"), 100, {})
        premium = bs.calculate_buy_score(extraction(brand="Lululemon"), 100, {})
        self.assertEqual(plain["buy_score"], premium["buy_score"])

    def test_adjustment_is_scoped_and_capped(self):
        row = bs.calculate_buy_score(
            extraction(personal_adjustments={"quality": -80, "value": 80}),
            100,
            {},
        )
        self.assertEqual(row["score_factors"]["personal_adjustments"]["quality"], -10)
        self.assertEqual(row["score_factors"]["personal_adjustments"]["value"], 10)

    def test_invalid_replacement_cost_is_not_keepable(self):
        row = bs.calculate_buy_score(
            extraction(
                factors={
                    "equivalent_replacement_cost": {
                        "value": 0,
                        "currency": "RON",
                        "confidence": 1,
                        "evidence": "invalid",
                    }
                }
            ),
            100,
            {},
        )
        self.assertEqual(row["buy_band"], "skip")
        self.assertEqual(row["verification_concern"], "block")
        self.assertEqual(row["buy_score"], 0)
        self.assertEqual(row["score_interval_low"], 0)
        self.assertEqual(row["score_interval_high"], 0)
        self.assertEqual(row["score_confidence"], 0)

    def test_buy_bands(self):
        self.assertEqual(bs.buy_band(59), "skip")
        self.assertEqual(bs.buy_band(60), "bundle")
        self.assertEqual(bs.buy_band(75), "good")
        self.assertEqual(bs.buy_band(85), "keep")
        self.assertEqual(bs.buy_band(95), "exceptional")

    def test_cross_hunt_golden_examples(self):
        path = Path(__file__).parent / "fixtures" / "buy_score_golden.json"
        cases = json.loads(path.read_text())
        results = {
            case["name"]: bs.calculate_buy_score(
                case["extraction"], case["delivered_cost_ron"], {}
            )
            for case in cases
        }
        for case in cases:
            self.assertEqual(results[case["name"]]["buy_band"], case["expected_band"])
            if case.get("better_than"):
                self.assertGreater(
                    results[case["name"]]["buy_score"],
                    results[case["better_than"]]["buy_score"],
                )


if __name__ == "__main__":
    unittest.main()
