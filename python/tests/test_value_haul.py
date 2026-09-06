import path_setup  # noqa: F401
import unittest

import value_haul as vh

VH = {
    "min_items": 3,
    "min_items_steal": 2,
    "steal_max_delivered_per_item_ron": 30,
    "max_candidates_to_score": 12,
}
WATCH = {
    "target_sizes": ["M", "L"],
    "target_type": "men's gym clothing suitable for building a multi-item bundle",
    "notes": "H&M Sport Nike Adidas",
}


def item(iid, title, brand="H&M", size="M", price="20"):
    return {
        "id": iid,
        "title": title,
        "brand_title": brand,
        "size_title": size,
        "price": {"amount": price, "currency_code": "RON"},
        "status": "Very good",
    }


class GateTests(unittest.TestCase):
    def test_three_candidates_pass(self):
        self.assertTrue(vh.passes_value_haul_gate(3, 28.0, VH))

    def test_three_expensive_fail(self):
        self.assertFalse(vh.passes_value_haul_gate(3, 50.0, VH))

    def test_two_cheap_pass(self):
        self.assertTrue(vh.passes_value_haul_gate(2, 18.0, VH))

    def test_two_near_fee_inclusive_pass(self):
        # Real H&M Sport haul was ~21 RON/item delivered; gate must clear that.
        self.assertTrue(vh.passes_value_haul_gate(2, 22.0, VH))

    def test_two_expensive_fail(self):
        self.assertFalse(vh.passes_value_haul_gate(2, 35.0, VH))

    def test_one_fails(self):
        self.assertFalse(vh.passes_value_haul_gate(1, 10.0, VH))


class PrefilterTests(unittest.TestCase):
    def test_size_m_slash_l_matches(self):
        self.assertTrue(vh.size_matches(item(1, "tee", size="M/L"), ["M", "L"]))

    def test_size_xl_does_not_match_l(self):
        self.assertFalse(vh.size_matches(item(1, "tee", size="XL"), ["M", "L"]))

    def test_wrong_size_rejected(self):
        self.assertFalse(vh.size_matches(item(1, "tee", size="S"), ["M", "L"]))

    def test_missing_size_does_not_match_via_title(self):
        it = item(1, "Please L me alone gym", size="")
        it["size_title"] = None
        self.assertFalse(vh.size_matches(it, ["M", "L"]))

    def test_maternity_seed_rejects_plain_hm_requires_mama_or_signal(self):
        mat_watch = {
            "target_sizes": ["L", "XL"],
            "target_type": "women's maternity clothing",
            "name": "H&M Mama bundle seed L-XL",
            "bundle_hunt": True,
            "notes": "Bundle seed like H&M Sport hauls — not premium solo hunting.",
        }
        # Bare H&M shirt must NOT pass (this was producing junk near-hauls).
        self.assertFalse(
            vh.looks_like_haul_fit(
                item(1, "Czarna Koszula 100% bawełna", brand="H&M", size="L"), mat_watch
            )
        )
        self.assertFalse(
            vh.looks_like_haul_fit(item(2, "Półgolf w paski", brand="H&M", size="L"), mat_watch)
        )
        # H&M Mama line / local maternity wording still counts.
        self.assertTrue(
            vh.looks_like_haul_fit(item(3, "Tricou Mama", brand="H&M", size="L"), mat_watch)
        )
        self.assertTrue(
            vh.looks_like_haul_fit(
                item(4, "Koszulka ciążowa H&M L", brand="H&M", size="L"), mat_watch
            )
        )
        self.assertFalse(
            vh.looks_like_haul_fit(item(5, "Nike tee", brand="Nike", size="L"), mat_watch)
        )

    def test_gym_title_accepted(self):
        self.assertTrue(vh.looks_like_gymwear(item(1, "H&M Sport póló"), WATCH))

    def test_random_home_rejected(self):
        self.assertFalse(
            vh.looks_like_gymwear(item(1, "Ikea cushion cover", brand="Ikea"), WATCH)
        )

    def test_prefilter_caps_and_keeps_gym(self):
        items = [
            item(1, "Nike training tee", price="15"),
            item(2, "Adidas gym short", size="L", price="18"),
            item(3, "H&M Sport top", price="12"),
            item(4, "Candle holder", brand="Home", size="M", price="5"),
        ]
        out = vh.prefilter_candidates(items, WATCH, {"value_haul": VH})
        ids = [x["id"] for x in out]
        self.assertIn(1, ids)
        self.assertIn(2, ids)
        self.assertIn(3, ids)
        self.assertNotIn(4, ids)

    def test_maternity_prefilter_accepts_mama_rejects_gym(self):
        mat_watch = {
            "target_sizes": ["L", "XL"],
            "target_type": "women's maternity clothing",
            "name": "H&M Mama bundle seed L-XL",
            "notes": "H&M Mama Next ASOS maternity",
        }
        items = [
            item(1, "H&M Mama nursing top", brand="H&M", size="L", price="25"),
            item(2, "Nike training tee", brand="Nike", size="L", price="20"),
            item(3, "Seraphine maternity dress", brand="Seraphine", size="XL", price="40"),
        ]
        out = vh.prefilter_candidates(items, mat_watch, {"value_haul": VH})
        ids = [x["id"] for x in out]
        self.assertIn(1, ids)
        self.assertIn(3, ids)
        self.assertNotIn(2, ids)

    def test_maternity_prompt_mentions_nursing(self):
        payload = vh.build_haul_payload(
            "seller",
            "ro",
            25.0,
            [item(1, "H&M Mama top", brand="H&M", size="L")],
            {
                "target_type": "women's maternity clothing",
                "target_sizes": ["L", "XL"],
                "notes": "Mama",
            },
        )
        prompt = vh.value_haul_prompt(payload, VH)
        self.assertIn("maternity", prompt.lower())
        self.assertIn("nursing", prompt.lower())


class FingerprintTests(unittest.TestCase):
    def test_fingerprint_sorted_useful_only(self):
        items = [item(3, "c"), item(1, "a"), item(2, "b")]
        score = {"reject_ids": [2]}
        useful = vh.useful_items(items, score)
        self.assertEqual(vh.value_haul_fingerprint(99, useful), "99:1,3")


class PayloadAndAlertTests(unittest.TestCase):
    def test_payload_totals(self):
        items = [
            item(1, "H&M Sport", price="16.67"),
            item(2, "H&M Sport", size="L", price="16.67"),
            item(3, "Nike tee", price="16.66"),
        ]
        payload = vh.build_haul_payload("robert", "hu", 40.0, items, WATCH)
        self.assertEqual(payload["kind"], "value_haul")
        self.assertEqual(payload["matching_items"], 3)
        self.assertAlmostEqual(payload["total_listing_price"], 50.0, places=1)
        self.assertAlmostEqual(payload["estimated_total"], 90.0, places=1)
        self.assertIn("value_haul", vh.value_haul_prompt(payload, VH).lower())

    def test_parse_object(self):
        raw = '{"deal_score":9,"value_band":"steal","useful_item_count":3,"effective_price_per_useful_item":21.2,"hunt_fit":true,"scam_risk":"low","reason":"good","reject_ids":[]}'
        score = vh.parse_value_haul_score(raw)
        self.assertEqual(score["deal_score"], 9)

    def test_alert_requires_gate_after_rejects(self):
        items = [item(1, "a"), item(2, "b"), item(3, "c")]
        score = {
            "deal_score": 9,
            "value_band": "steal",
            "hunt_fit": True,
            "scam_risk": "low",
            "reject_ids": [1],
            "effective_price_per_useful_item": 18.0,
            "useful_item_count": 2,
        }
        useful = vh.useful_items(items, score)
        self.assertEqual(len(useful), 2)
        self.assertTrue(vh.is_value_haul_alert(score, useful, 25.0, VH))

    def test_alert_rejects_high_scam(self):
        items = [item(1, "a"), item(2, "b"), item(3, "c")]
        score = {
            "deal_score": 9,
            "value_band": "steal",
            "hunt_fit": True,
            "scam_risk": "high",
            "reject_ids": [],
            "effective_price_per_useful_item": 15.0,
        }
        self.assertFalse(vh.is_value_haul_alert(score, items, 25.0, VH))


class NearHaulTests(unittest.TestCase):
    def test_near_haul_record_kind(self):
        items = [item(1, "tee a"), item(2, "tee b")]
        haul = {
            "seller": "bob",
            "seller_id": 9,
            "country": "pl",
            "checkout_extra_ron": 25,
        }
        row = vh.near_haul_record(haul, items, "Gym bundle seeds M-L", "2026-01-01T00:00:00Z", 22.5)
        self.assertEqual(row["kind"], "near_haul")
        self.assertEqual(row["value_band"], "opportunity")
        self.assertIsNone(row["deal_score"])
        self.assertEqual(row["seller"], "bob")
        self.assertEqual(len(row["items"]), 2)
        self.assertIn("Fee-gated", row["reason"])
        self.assertIn("suggested_offer_ron", row)
        self.assertIn("offer_weak", row)

    def test_value_haul_record_includes_offer(self):
        items = [item(1, "a", price="20"), item(2, "b", price="20"), item(3, "c", price="20")]
        row = vh.value_haul_record(
            {"seller": "bob", "seller_id": 9, "country": "ro", "checkout_extra_ron": 30},
            {"deal_score": 9, "value_band": "steal", "reason": "ok"},
            items,
            "Gym bundle seeds M-L",
            "t1",
        )
        self.assertEqual(row["kind"], "value_haul")
        self.assertEqual(row["suggested_offer_ron"], 54)
        self.assertFalse(row["offer_weak"])

    def test_merge_supersedes_near_with_value(self):
        items = [item(1, "a"), item(2, "b")]
        near = vh.near_haul_record(
            {"seller": "bob", "seller_id": 9, "country": "pl", "checkout_extra_ron": 25},
            items,
            "Gym",
            "t1",
            22.0,
        )
        value = vh.value_haul_record(
            {"seller": "bob", "seller_id": 9, "country": "pl", "checkout_extra_ron": 25},
            {"deal_score": 9, "value_band": "steal", "reason": "steal"},
            items,
            "Gym",
            "t2",
        )
        merged = vh.merge_bundle_rows([near], [value], max_opportunity=80)
        opps = [r for r in merged if r.get("kind") in ("value_haul", "near_haul")]
        self.assertEqual(len(opps), 1)
        self.assertEqual(opps[0]["kind"], "value_haul")

    def test_near_gate_looser_than_value(self):
        self.assertFalse(vh.passes_value_haul_gate(2, 40.0, VH))
        self.assertTrue(vh.passes_near_haul_gate(2, 40.0, {**VH, "near_max_delivered_per_item_ron": 45}))
        self.assertFalse(vh.passes_near_haul_gate(2, 50.0, {**VH, "near_max_delivered_per_item_ron": 45}))
        self.assertFalse(vh.passes_near_haul_gate(1, 10.0, VH))

    def test_merge_keeps_near_when_value_absent(self):
        items = [item(1, "a"), item(2, "b")]
        near = vh.near_haul_record(
            {"seller": "bob", "seller_id": 9, "country": "pl", "checkout_extra_ron": 25},
            items,
            "Gym",
            "t1",
            22.0,
        )
        merged = vh.merge_bundle_rows([], [near], max_opportunity=80)
        self.assertEqual(merged[0]["kind"], "near_haul")


    def test_enrich_fills_missing_offer_on_old_row(self):
        items = [item(1, "a", price="40"), item(2, "b", price="50")]
        old = {
            "kind": "near_haul",
            "seller_id": 1,
            "listing_sum": 90,
            "checkout_extra_ron": 25,
            "watch": "Gym bundle seeds M-L",
            "items": [{"id": 1, "watch": "Gym"}, {"id": 2, "watch": "Gym"}],
        }
        enriched = vh.enrich_bundle_offer_fields([old])
        self.assertEqual(enriched[0]["suggested_offer_ron"], 58)
        self.assertTrue(enriched[0]["offer_weak"])


if __name__ == "__main__":
    unittest.main()
