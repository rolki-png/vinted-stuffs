import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import scored_store as ss


class MemoryStoreTests(unittest.TestCase):
    def test_upsert_and_load_by_seller(self):
        store = ss.MemoryScoredStore()
        row = ss.row_from_item_score(
            item={
                "id": 111,
                "title": "Craft tee",
                "price": {"amount": "40", "currency_code": "RON"},
                "brand_title": "Craft",
                "size_title": "M",
                "status": "Very good",
                "url": "https://www.vinted.ro/items/111",
                "favourite_count": 2,
                "user": {"id": 99, "login": "seller"},
                "_profile": {"country_code": "ro"},
            },
            score={
                "id": 111,
                "deal_score": 7,
                "value_band": "acceptable",
                "hunt_fit": True,
                "scam_risk": "low",
                "reason": "ok extra",
            },
            hunt_name="Craft ADV M-L",
            source="search",
            scored_at=datetime(2026, 9, 5, tzinfo=timezone.utc),
        )
        store.upsert_score(row)
        loaded = store.load_by_seller(99)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["item_id"], 111)
        self.assertEqual(loaded[0]["deal_score"], 7)
        self.assertEqual(loaded[0]["seller_id"], 99)

    def test_upsert_overwrites_same_pk(self):
        store = ss.MemoryScoredStore()
        base = ss.row_from_item_score(
            item={
                "id": 1,
                "title": "a",
                "price": {"amount": "10", "currency_code": "RON"},
                "user": {"id": 5, "login": "x"},
                "_profile": {},
            },
            score={
                "deal_score": 5,
                "value_band": "skip",
                "hunt_fit": False,
                "scam_risk": "medium",
                "reason": "old",
            },
            hunt_name="H",
            source="search",
        )
        store.upsert_score(base)
        base2 = dict(base)
        base2["deal_score"] = 8
        base2["reason"] = "new"
        store.upsert_score(base2)
        loaded = store.load_by_seller(5)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["deal_score"], 8)
        self.assertEqual(loaded[0]["reason"], "new")

    def test_candidate_from_cached_rebuilds_bot_row(self):
        row = {
            "item_id": 42,
            "hunt_name": "Craft ADV M-L",
            "title": "Craft ADV",
            "price": 55.0,
            "currency": "RON",
            "brand": "Craft",
            "size": "L",
            "condition": "New without tags",
            "url": "https://www.vinted.ro/items/42",
            "favourite_count": 1,
            "seller_id": 7,
            "seller_login": "bob",
            "seller_country": "ro",
            "deal_score": 7,
            "value_band": "acceptable",
            "hunt_fit": True,
            "scam_risk": "low",
            "reason": "bundle extra",
            "has_score": True,
            "source": "closet_crawl",
        }
        watch = {"name": "Craft ADV M-L", "country": "ro", "target_type": "men's"}
        cand = ss.candidate_from_cached(row, watch)
        self.assertEqual(cand["watch"], "Craft ADV M-L")
        self.assertIs(cand["watch_obj"], watch)
        self.assertEqual(cand["item"]["id"], 42)
        self.assertEqual(cand["item"]["user"]["id"], 7)
        self.assertEqual(cand["score"]["deal_score"], 7)
        self.assertTrue(cand["score"]["hunt_fit"])

    def test_cached_extra_plus_new_keep_assembles_bundle(self):
        import vinted_bot as bot

        config = {
            "min_deal_score": 9,
            "require_hunt_fit": True,
            "keep_value_bands": ["steal", "hunt"],
            "solo_floor_clothing_ron": 0,
            "bundle_extra_min_score": 7,
            "checkout_extra_ron": {"ro": 25, "default": 25},
        }
        watch = {"name": "Craft ADV M-L", "target_type": "men's gym", "country": "ro"}
        store = ss.MemoryScoredStore()
        store.upsert_score(
            ss.row_from_item_score(
                item={
                    "id": 2,
                    "title": "extra",
                    "price": {"amount": "80", "currency_code": "RON"},
                    "user": {"id": 99, "login": "seller"},
                    "_profile": {"country_code": "ro"},
                },
                score={
                    "deal_score": 7,
                    "value_band": "acceptable",
                    "hunt_fit": True,
                    "scam_risk": "low",
                    "reason": "extra",
                },
                hunt_name=watch["name"],
                source="search",
            )
        )
        cached = store.load_by_seller(99)
        prior = [ss.candidate_from_cached(r, watch) for r in cached]
        keep = {
            "item": {
                "id": 1,
                "title": "keep",
                "price": {"amount": "150", "currency_code": "RON"},
                "url": "https://www.vinted.ro/items/1",
                "user": {"id": 99, "login": "seller"},
                "_profile": {"country_code": "ro"},
            },
            "score": {
                "deal_score": 9,
                "value_band": "steal",
                "hunt_fit": True,
                "scam_risk": "low",
                "reason": "keep",
            },
            "watch": watch["name"],
            "watch_obj": watch,
        }
        bundles, solos = bot.assemble_bundles(bot.merge_scored([keep], prior), config)
        self.assertEqual(len(bundles), 1)
        self.assertEqual(len(solos), 0)
        self.assertEqual(bundles[0]["extras"][0]["item"]["id"], 2)

    def test_index_bundle_opportunities(self):
        rows = [
            {
                "id": 1, "watch": "H", "title": "a", "price": 40, "deal_score": 7,
                "value_band": "acceptable", "hunt_fit": True, "seller_id": 9,
                "seller": "s", "scored_at": "2026-09-05T01:00:00+00:00",
            },
            {
                "id": 2, "watch": "H", "title": "b", "price": 50, "deal_score": 8,
                "value_band": "hunt", "hunt_fit": True, "seller_id": 9,
                "seller": "s", "scored_at": "2026-09-05T02:00:00+00:00",
            },
            {
                "id": 3, "watch": "H", "title": "skip", "price": 10, "deal_score": 3,
                "value_band": "skip", "hunt_fit": True, "seller_id": 9,
                "seller": "s", "scored_at": "2026-09-05T03:00:00+00:00",
            },
        ]
        opps = ss.index_bundle_opportunities(rows, min_items=2, min_deal_score=6)
        self.assertEqual(len(opps), 1)
        self.assertEqual(opps[0]["kind"], "index_near_bundle")
        self.assertEqual(len(opps[0]["items"]), 2)
        self.assertIn("suggested_offer_ron", opps[0])
        self.assertEqual(opps[0]["checkout_extra_ron"], 25)
        self.assertTrue(opps[0].get("offer_weak"))

    def test_revive_skips_unknown_hunt_and_excluded_ids(self):
        import vinted_bot as bot

        store = ss.MemoryScoredStore()
        watch = {"name": "Craft ADV M-L", "country": "ro"}
        store.upsert_score(
            ss.row_from_item_score(
                item={
                    "id": 10,
                    "title": "a",
                    "price": {"amount": "1", "currency_code": "RON"},
                    "url": "https://www.vinted.ro/items/10",
                    "user": {"id": 1, "login": "s"},
                    "_profile": {"country_code": "ro"},
                },
                score={
                    "deal_score": 7,
                    "value_band": "acceptable",
                    "hunt_fit": True,
                    "scam_risk": "low",
                    "reason": "x",
                },
                hunt_name="Craft ADV M-L",
                source="search",
            )
        )
        store.upsert_score(
            ss.row_from_item_score(
                item={
                    "id": 11,
                    "title": "b",
                    "price": {"amount": "1", "currency_code": "RON"},
                    "url": "https://www.vinted.ro/items/11",
                    "user": {"id": 1, "login": "s"},
                    "_profile": {"country_code": "ro"},
                },
                score={
                    "deal_score": 7,
                    "value_band": "acceptable",
                    "hunt_fit": True,
                    "scam_risk": "low",
                    "reason": "y",
                },
                hunt_name="Deleted Hunt",
                source="search",
            )
        )

        def fake_available(specs):
            return {str(s["id"]) for s in specs}, {}

        with patch.object(bot, "check_items_available", side_effect=fake_available):
            revived = bot.revive_scored_for_sellers(
                store, [1], [watch], exclude_ids={"10"}, scored_store_mod=ss,
            )
        self.assertEqual(revived, [])


    def test_listing_upsert_does_not_wipe_score(self):
        store = ss.MemoryScoredStore()
        scored = ss.row_from_item_score(
            item={
                "id": 1,
                "title": "dress",
                "price": {"amount": "40", "currency_code": "RON"},
                "user": {"id": 9, "login": "s"},
                "_profile": {"country_code": "ro"},
            },
            score={
                "deal_score": 8,
                "value_band": "hunt",
                "hunt_fit": True,
                "scam_risk": "low",
                "reason": "good",
            },
            hunt_name="H",
            source="search",
        )
        store.upsert_score(scored)
        listing_only = ss.row_from_item(
            {
                "id": 1,
                "title": "dress updated",
                "price": {"amount": "35", "currency_code": "RON"},
                "user": {"id": 9, "login": "s"},
                "_profile": {"country_code": "ro"},
            },
            "H",
            "backfill",
            hunt_fit=True,
        )
        store.upsert_score(listing_only)
        row = store.load_by_seller(9)[0]
        self.assertTrue(row["has_score"])
        self.assertEqual(row["deal_score"], 8)
        self.assertEqual(row["title"], "dress updated")
        self.assertEqual(row["price"], 35.0)


if __name__ == "__main__":
    unittest.main()
