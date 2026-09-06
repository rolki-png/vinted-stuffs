import unittest

import bundle_offer as bo


class SuggestBundleOfferTests(unittest.TestCase):
    def test_maternity_shape_toward_187(self):
        # 5 Mama pieces @ 227 listing; extra chosen so target 50/item → ~187 goods.
        out = bo.suggest_bundle_offer(
            227.0,
            63.0,
            5,
            target_per_item=50.0,
            max_haircut=0.25,
            min_haircut=0.10,
        )
        self.assertIsNotNone(out)
        self.assertEqual(out["suggested_offer_ron"], 187)
        self.assertFalse(out["offer_weak"])
        self.assertEqual(out["offer_target_per_item_ron"], 50.0)

    def test_gym_hits_target_inside_alerted_band(self):
        # 3 items @ 60 listing + 30 extra = 30/item at full price.
        # Target 30 → raw 60; min 10% off → hi=54 → offer 54.
        out = bo.suggest_bundle_offer(
            60.0,
            30.0,
            3,
            target_per_item=30.0,
            max_haircut=0.25,
            min_haircut=0.10,
        )
        self.assertEqual(out["suggested_offer_ron"], 54)
        self.assertFalse(out["offer_weak"])

    def test_near_allows_35_percent_haircut(self):
        # Need aggressive bid: target forces raw well below 25% floor but above 35%.
        # listing 200, n=2, extra=20, target=30 → raw = 40; lo@25%=150, lo@35%=130
        out_alerted = bo.suggest_bundle_offer(
            200.0, 20.0, 2, target_per_item=30.0, max_haircut=0.25
        )
        out_near = bo.suggest_bundle_offer(
            200.0, 20.0, 2, target_per_item=30.0, max_haircut=0.35
        )
        self.assertEqual(out_alerted["suggested_offer_ron"], 150)
        self.assertTrue(out_alerted["offer_weak"])
        self.assertEqual(out_near["suggested_offer_ron"], 130)
        self.assertTrue(out_near["offer_weak"])

    def test_weak_when_unreachable_at_max_haircut(self):
        out = bo.suggest_bundle_offer(
            300.0,
            40.0,
            3,
            target_per_item=30.0,
            max_haircut=0.25,
        )
        # raw = 50; lo = 225 → clamp to 225, weak
        self.assertEqual(out["suggested_offer_ron"], 225)
        self.assertTrue(out["offer_weak"])

    def test_min_haircut_even_when_full_price_beats_target(self):
        # Full price already cheap; still at least 10% off list.
        out = bo.suggest_bundle_offer(
            100.0,
            10.0,
            5,
            target_per_item=50.0,
            max_haircut=0.25,
            min_haircut=0.10,
        )
        # raw = 240 → clamp to hi = 90
        self.assertEqual(out["suggested_offer_ron"], 90)
        self.assertFalse(out["offer_weak"])

    def test_omit_when_too_few_items_or_zero_listing(self):
        self.assertIsNone(
            bo.suggest_bundle_offer(50.0, 10.0, 1, target_per_item=30.0, max_haircut=0.25)
        )
        self.assertIsNone(
            bo.suggest_bundle_offer(0.0, 10.0, 3, target_per_item=30.0, max_haircut=0.25)
        )


class OfferFieldsTests(unittest.TestCase):
    def test_maternity_watch_uses_50_target(self):
        fields = bo.offer_fields(
            227.0,
            63.0,
            5,
            kind="value_haul",
            watch_name="Mamalicious maternity L-XL",
        )
        self.assertEqual(fields["suggested_offer_ron"], 187)
        self.assertEqual(fields["offer_target_per_item_ron"], 50.0)

    def test_near_kind_uses_near_haircut(self):
        fields = bo.offer_fields(
            200.0,
            20.0,
            2,
            kind="near_haul",
            watch_name="Gym bundle seeds M-L",
        )
        self.assertEqual(fields["suggested_offer_ron"], 130)
        self.assertTrue(fields["offer_weak"])


if __name__ == "__main__":
    unittest.main()
