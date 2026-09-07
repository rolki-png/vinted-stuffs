import path_setup  # noqa: F401
import inspect
import unittest
from unittest.mock import patch

import vinted_bot as bot

CONFIG = {
    "min_deal_score": 9,
    "require_hunt_fit": True,
    "keep_value_bands": ["steal", "hunt"],
    "solo_floor_clothing_ron": 0,
}
CONFIG_FLOOR = {**CONFIG, "solo_floor_clothing_ron": 100}
GYM = {"target_type": "men's gym clothing", "min_deal_score": 9}


def v2(score=88, confidence=0.8, concern="none", hunt_fit=True):
    return {
        "score_version": 2,
        "buy_score": score,
        "buy_band": "keep" if score < 95 else "exceptional",
        "score_confidence": confidence,
        "hunt_fit": hunt_fit,
        "verification_concern": concern,
    }


class KeepRuleTests(unittest.TestCase):
    def test_legacy_cached_row_preserves_previous_keep_rules(self):
        item = {"price": {"amount": "80", "currency_code": "RON"}}
        score = {
            "deal_score": 9,
            "value_band": "steal",
            "hunt_fit": True,
            "scam_risk": "medium",
        }
        self.assertTrue(bot.is_keep(score, CONFIG_FLOOR, GYM, item))

    def test_v2_keep_requires_score_confidence_fit_and_clear_verification(self):
        watch = {"target_type": "men's gym clothing"}
        self.assertTrue(bot.is_keep(v2(), CONFIG, watch, {}))
        self.assertFalse(bot.is_keep(v2(score=84), CONFIG, watch, {}))
        self.assertFalse(bot.is_keep(v2(confidence=0.59), CONFIG, watch, {}))
        self.assertFalse(bot.is_keep(v2(concern="block"), CONFIG, watch, {}))
        self.assertFalse(bot.is_keep(v2(hunt_fit=False), CONFIG, watch, {}))

    def test_v2_bundle_extra_uses_buy_band(self):
        self.assertTrue(
            bot.is_bundle_extra(
                {
                    "score_version": 2,
                    "buy_score": 68,
                    "buy_band": "bundle",
                    "hunt_fit": True,
                    "verification_concern": "none",
                },
                CONFIG,
            )
        )

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
        watch = {
            "target_type": "men's gym clothing",
            "bundle_hunt": True,
            "min_deal_score": 8,
        }
        self.assertFalse(bot.is_keep(v2(score=98), CONFIG, watch, item))

    def test_mens_gym_tee_remains_excluded_before_v2_qualification(self):
        item = {
            "title": "Nike Dri-FIT training T-shirt",
            "price": {"amount": "120", "currency_code": "RON"},
        }
        self.assertFalse(bot.is_keep(v2(score=98), CONFIG, GYM, item))

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

    def test_candidate_helpers_have_no_taste_outcomes_plumbing(self):
        self.assertFalse(hasattr(bot, "is_keep_with_taste"))
        self.assertNotIn(
            "taste_outcomes", inspect.signature(bot.pool_candidates).parameters
        )
        self.assertNotIn(
            "taste_outcomes", inspect.signature(bot.assemble_bundles).parameters
        )

    def test_candidate_keep_uses_calculator_gate(self):
        item = {
            "id": 1,
            "brand_title": "Nike",
            "size_title": "L",
            "price": {"amount": "40", "currency_code": "RON"},
        }
        watch = {"name": "Lululemon gym M-L", "target_type": "men's gym clothing"}
        self.assertTrue(bot.is_keep(v2(), CONFIG, watch, item))
        self.assertFalse(hasattr(bot, "is_taste_hard_suppressed"))

    def test_bundle_extra_uses_calculator_gate(self):
        item = {
            "id": 2,
            "brand_title": "Nike",
            "size_title": "L",
            "price": {"amount": "40", "currency_code": "RON"},
        }
        score = v2(score=68)
        watch = {"name": "Lululemon gym M-L", "target_type": "men's gym clothing"}
        self.assertTrue(bot.is_bundle_extra(score, CONFIG))
        bundles, solos = bot.assemble_bundles(
            [
                {
                    "item": {
                        "id": 1,
                        "brand_title": "Lulu",
                        "size_title": "L",
                        "price": {"amount": "90", "currency_code": "RON"},
                        "user": {"id": 9, "login": "s"},
                    },
                    "score": v2(),
                    "watch": watch["name"],
                    "watch_obj": watch,
                },
                {
                    "item": {**item, "user": {"id": 9, "login": "s"}},
                    "score": score,
                    "watch": watch["name"],
                    "watch_obj": watch,
                },
            ],
            CONFIG,
        )
        self.assertEqual(len(bundles), 1)
        self.assertEqual(
            [row["item"]["id"] for row in bundles[0]["keeps"] + bundles[0]["extras"]],
            [1, 2],
        )
        self.assertEqual(solos, [])

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

    def test_v2_selection_and_closet_ranking_do_not_read_legacy_score_fields(self):
        low = {
            "item": {"id": 1},
            "score": v2(score=86),
            "is_keep": True,
            "sid": 1,
        }
        high = {
            "item": {"id": 2},
            "score": v2(score=92),
            "is_keep": True,
            "sid": 2,
        }
        legacy = {
            "item": {"id": 3},
            "score": {
                "deal_score": 10,
                "value_band": "steal",
                "hunt_fit": True,
                "scam_risk": "low",
            },
            "is_keep": True,
            "sid": 3,
        }
        self.assertEqual(
            [row["item"]["id"] for row in bot.select_best([low, high, legacy], CONFIG)],
            [2, 1, 3],
        )
        self.assertEqual(
            [
                row["sid"]
                for row in bot.select_closet_crawl_sellers(
                    [low, high, legacy], {**CONFIG, "closet_crawl_max_sellers": 3}
                )
            ],
            [2, 1, 3],
        )

    def test_v2_solo_notification_uses_only_v2_score_semantics(self):
        item = {
            "title": "Technical shorts",
            "price": {"amount": "80", "currency_code": "RON"},
            "brand_title": "Craft",
            "url": "https://example.test/1",
        }
        score = {
            **v2(score=91, concern="inspect"),
            "score_interval_low": 86,
            "score_interval_high": 95,
            "reason": "Strong utility",
        }
        with patch.object(bot, "_ntfy_post") as send:
            bot.send_ntfy("topic", item, score)
        title, body = send.call_args.args[1:3]
        self.assertIn("91", title)
        self.assertIn("86-95", title + body)
        self.assertIn("keep", title + body)
        self.assertIn("inspect", title + body)

    def test_v2_bundle_notification_uses_only_v2_score_semantics(self):
        row = {
            "item": {
                "title": "Technical shorts",
                "price": {"amount": "80", "currency_code": "RON"},
                "url": "https://example.test/1",
            },
            "score": {
                **v2(score=91, concern="inspect"),
                "score_interval_low": 86,
                "score_interval_high": 95,
            },
        }
        bundle = {
            "seller": "seller",
            "seller_id": 4,
            "country": "ro",
            "listing_sum": 80,
            "checkout_extra_ron": 22,
            "checkout_total": 102,
            "keeps": [row],
            "extras": [],
        }
        with patch.object(bot, "_ntfy_post") as send:
            bot.send_ntfy_bundle("topic", bundle)
        body = send.call_args.args[2]
        self.assertIn("91", body)
        self.assertIn("86-95", body)
        self.assertIn("keep", body)
        self.assertIn("inspect", body)

    def test_v2_snapshot_contains_v2_fields_without_legacy_score_fields(self):
        score = {
            **v2(score=91, concern="inspect"),
            "score_interval_low": 86,
            "score_interval_high": 95,
            "score_factors": {"quality": 90},
            "factor_evidence": {"quality": "technical fabric"},
            "verification_reason": "inspect label",
            "reason": "Strong utility",
        }
        snapshot = bot._score_snapshot(score)
        self.assertEqual(snapshot["score_version"], 2)
        self.assertEqual(snapshot["buy_score"], 91)
        self.assertEqual(snapshot["score_interval_low"], 86)
        self.assertNotIn("deal_score", snapshot)
        self.assertNotIn("scam_risk", snapshot)

    def test_v2_histogram_uses_ten_point_bins_and_ignores_legacy_rows(self):
        rows = [
            {"score": v2(score=0)},
            {"score": v2(score=9)},
            {"score": v2(score=10)},
            {"score": v2(score=90)},
            {"score": v2(score=100)},
            {"score": {"deal_score": 9}},
        ]
        histogram = bot._v2_score_histogram(rows)
        self.assertEqual(
            list(histogram),
            [
                "0-9",
                "10-19",
                "20-29",
                "30-39",
                "40-49",
                "50-59",
                "60-69",
                "70-79",
                "80-89",
                "90-100",
            ],
        )
        self.assertEqual(histogram["0-9"], 2)
        self.assertEqual(histogram["10-19"], 1)
        self.assertEqual(histogram["90-100"], 2)

    def test_test_mode_builds_factors_for_real_calculator(self):
        watch = {"country": "ro"}
        items = [
            {
                "id": 7,
                "price": {"amount": "80", "currency_code": "RON"},
            }
        ]
        config = {
            "checkout_fees": {
                "ro": {
                    "estimated_shipping_ron": 15,
                    "buyer_fee_fixed_ron": 3,
                    "buyer_fee_pct": 0.05,
                }
            }
        }
        extractions = bot._test_mode_extractions(items, watch, config)
        self.assertNotIn("buy_score", extractions[0])
        self.assertTrue(bot._valid_extractions(extractions, items))
        scores = bot.normalize_extractions(extractions, items, watch, config)
        self.assertEqual(scores[0]["score_version"], 2)
        self.assertEqual(scores[0]["score_factors"]["delivered_cost_ron"], 102)


if __name__ == "__main__":
    unittest.main()
