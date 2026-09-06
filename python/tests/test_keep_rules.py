import path_setup  # noqa: F401
import unittest

import vinted_bot as bot

CONFIG = {
    "min_deal_score": 9,
    "require_hunt_fit": True,
    "keep_value_bands": ["steal", "hunt"],
    "solo_floor_clothing_ron": 0,
}
CONFIG_FLOOR = {
    **CONFIG,
    "solo_floor_clothing_ron": 100,
}
GYM = {"target_type": "men's gym clothing", "min_deal_score": 9}
KNIT = {"target_type": "men's premium knitwear", "min_deal_score": 9}


class KeepRuleTests(unittest.TestCase):
    def test_steal_clothing_under_old_floor_is_keep(self):
        item = {"price": {"amount": "80", "currency_code": "RON"}}
        score = {
            "deal_score": 9,
            "value_band": "steal",
            "hunt_fit": True,
            "scam_risk": "medium",
        }
        self.assertTrue(bot.is_keep(score, CONFIG_FLOOR, GYM, item))

    def test_hunt_score_8_is_not_keep(self):
        item = {"price": {"amount": "150", "currency_code": "RON"}}
        score = {
            "deal_score": 8,
            "value_band": "hunt",
            "hunt_fit": True,
            "scam_risk": "medium",
        }
        self.assertFalse(bot.is_keep(score, CONFIG, GYM, item))

    def test_premium_hunt_under_floor_passes_when_floor_disabled(self):
        item = {"price": {"amount": "60", "currency_code": "RON"}}
        score = {
            "deal_score": 9,
            "value_band": "hunt",
            "hunt_fit": True,
            "scam_risk": "low",
        }
        self.assertTrue(bot.is_keep(score, CONFIG, KNIT, item))

    def test_hunt_clothing_under_floor_blocked_when_floor_set(self):
        item = {"price": {"amount": "80", "currency_code": "RON"}}
        score = {
            "deal_score": 9,
            "value_band": "hunt",
            "hunt_fit": True,
            "scam_risk": "medium",
        }
        self.assertFalse(bot.is_keep(score, CONFIG_FLOOR, GYM, item))

    def test_checkout_fees_scale_with_listing_sum(self):
        cfg = {
            "checkout_fees": {
                "hu": {
                    "estimated_shipping_ron": 18,
                    "buyer_fee_fixed_ron": 3,
                    "buyer_fee_pct": 0.05,
                }
            }
        }
        # 100 RON listing → 18 + 3 + 5 = 26
        self.assertAlmostEqual(bot.checkout_extra_ron("hu", cfg, 100), 26.0)
        # 300 RON listing → 18 + 3 + 15 = 36 (not a flat 40)
        self.assertAlmostEqual(bot.checkout_extra_ron("hu", cfg, 300), 36.0)

    def test_bundle_hunt_watch_never_keep(self):
        item = {"price": {"amount": "200", "currency_code": "RON"}}
        score = {
            "deal_score": 10,
            "value_band": "steal",
            "hunt_fit": True,
            "scam_risk": "low",
        }
        watch = {
            "target_type": "men's gym clothing",
            "bundle_hunt": True,
            "min_deal_score": 8,
        }
        self.assertFalse(bot.is_keep(score, CONFIG, watch, item))

    def test_maternity_score_8_is_keep_when_watch_allows(self):
        item = {"price": {"amount": "150", "currency_code": "RON"}}
        score = {
            "deal_score": 8,
            "value_band": "hunt",
            "hunt_fit": True,
            "scam_risk": "low",
        }
        watch = {
            "target_type": "women's premium maternity clothing",
            "min_deal_score": 8,
        }
        self.assertTrue(bot.is_keep(score, CONFIG, watch, item))

    def test_value_haul_path_includes_maternity_excludes_sneakers(self):
        self.assertTrue(
            bot.is_value_haul_path_watch({"target_type": "women's premium maternity clothing"})
        )
        self.assertTrue(
            bot.is_value_haul_path_watch({"target_type": "men's gym clothing"})
        )
        self.assertFalse(
            bot.is_value_haul_path_watch({"target_type": "men's sneakers"})
        )

    def test_taste_hard_suppress_blocks_keep(self):
        item = {
            "id": 1,
            "brand_title": "Nike",
            "size_title": "L",
            "price": {"amount": "40", "currency_code": "RON"},
        }
        score = {
            "deal_score": 9,
            "value_band": "steal",
            "hunt_fit": True,
            "scam_risk": "low",
        }
        watch = {"name": "Lululemon gym M-L", "target_type": "men's gym clothing"}
        outcomes = [
            {"status": "removed", "hunt_family": "gym", "brand": "Nike", "size": "L"},
            {"status": "removed", "hunt_family": "gym", "brand": "Nike", "size": "L"},
            {"status": "removed", "hunt_family": "gym", "brand": "Nike", "size": "L"},
        ]
        self.assertTrue(bot.is_keep(score, CONFIG, watch, item))
        self.assertFalse(
            bot.is_keep_with_taste(score, CONFIG, watch, item, outcomes)
        )

    def test_scoring_prompt_appends_taste_block(self):
        watch = {
            "name": "Lululemon gym M-L",
            "query": "lululemon",
            "target_type": "men's gym",
            "target_sizes": ["M", "L"],
            "notes": "x",
            "hunt_price": 50,
            "price_to": 80,
        }
        items = [
            {
                "id": 1,
                "title": "shorts",
                "price": {"amount": "40", "currency_code": "RON"},
            }
        ]
        prompt = bot._scoring_prompt(
            watch,
            items,
            taste_block=(
                "Buyer taste from desk outcomes:\n"
                "Bought (strong positive):\n- Good"
            ),
        )
        self.assertIn("Buyer taste from desk outcomes", prompt)
        self.assertIn("Good", prompt)


if __name__ == "__main__":
    unittest.main()
