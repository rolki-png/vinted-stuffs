import path_setup  # noqa: F401
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

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

    def test_index_bundles_keep_v2_and_legacy_scores_separate(self):
        common = {
            "watch": "H",
            "hunt_fit": True,
            "seller_id": 9,
            "seller": "s",
            "scored_at": "2026-09-05T02:00:00+00:00",
            "has_score": True,
        }
        rows = [
            {
                **common, "id": 1, "title": "legacy keep", "price": 40,
                "deal_score": 9, "value_band": "hunt",
            },
            {
                **common, "id": 2, "title": "legacy extra", "price": 50,
                "deal_score": 7, "value_band": "acceptable",
            },
            {
                **common, "id": 3, "title": "v2 keep", "price": 60,
                "score_version": 2, "buy_score": 90, "buy_band": "keep",
                "score_confidence": 0.7, "score_interval_low": 85,
                "score_interval_high": 94, "verification_concern": "none",
                "rank_position": 1, "rank_confidence": "high",
            },
            {
                **common, "id": 4, "title": "v2 extra", "price": 30,
                "score_version": 2, "buy_score": 70, "buy_band": "bundle",
                "score_confidence": 0.8, "score_interval_low": 64,
                "score_interval_high": 76, "verification_concern": "inspect",
                "rank_position": 2, "rank_confidence": "medium",
            },
        ]

        opportunities = ss.index_bundle_opportunities(rows)

        self.assertEqual(len(opportunities), 2)
        item_groups = [opportunity["items"] for opportunity in opportunities]
        self.assertIn([3, 4], [[item["id"] for item in items] for items in item_groups])
        self.assertIn([1, 2], [[item["id"] for item in items] for items in item_groups])
        v2_items = next(items for items in item_groups if items[0]["id"] == 3)
        self.assertEqual(v2_items[0]["role"], "keep")
        self.assertEqual(v2_items[1]["role"], "extra")
        self.assertEqual(v2_items[0]["score_version"], 2)
        self.assertEqual(v2_items[0]["score_interval_low"], 85)
        self.assertEqual(v2_items[0]["rank_position"], 1)

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

    def test_v2_round_trip_preserves_structured_score(self):
        score = {
            "id": 99,
            "score_version": 2,
            "buy_score": 88,
            "buy_band": "keep",
            "score_confidence": 0.74,
            "score_interval_low": 82,
            "score_interval_high": 93,
            "score_factors": {"quality": 84, "value": 91},
            "factor_evidence": {"quality": "dense fabric"},
            "verification_concern": "inspect",
            "verification_reason": "confirm care label",
            "hunt_fit": True,
            "reason": "high expected use",
            "rank_position": 2,
            "rank_confidence": "medium",
        }
        row = ss.row_from_item_score(
            {
                "id": 99,
                "title": "technical shorts",
                "price": {"amount": "80", "currency_code": "RON"},
                "user": {"id": 7, "login": "seller"},
                "_profile": {"country_code": "ro"},
            },
            score,
            "Gym",
            "search",
        )
        store = ss.MemoryScoredStore()
        store.upsert_score(row)
        cached = ss.candidate_from_cached(store.load_by_seller(7)[0], {"name": "Gym"})
        exported = ss.export_row(store.load_by_seller(7)[0])
        self.assertEqual(cached["score"]["buy_score"], 88)
        self.assertEqual(cached["score"]["score_factors"]["quality"], 84)
        self.assertEqual(exported["score_version"], 2)
        self.assertEqual(exported["buy_band"], "keep")
        self.assertIsNone(exported["deal_score"])

    def test_postgres_upsert_serializes_v2_json_objects(self):
        conn = MagicMock()
        cursor = conn.cursor.return_value.__enter__.return_value
        row = ss.row_from_item_score(
            {
                "id": 100,
                "title": "technical shorts",
                "price": {"amount": "80", "currency_code": "RON"},
                "user": {"id": 7, "login": "seller"},
                "_profile": {"country_code": "ro"},
            },
            {
                "score_version": 2,
                "buy_score": 88,
                "score_factors": {"quality": 84},
                "factor_evidence": {"quality": "dense fabric"},
                "hunt_fit": True,
            },
            "Gym",
            "search",
        )

        ss.PsycopgScoredStore(conn).upsert_score(row)

        sql_row = cursor.execute.call_args.args[1]
        self.assertEqual(json.loads(sql_row["score_factors"]), {"quality": 84})
        self.assertEqual(
            json.loads(sql_row["factor_evidence"]),
            {"quality": "dense fabric"},
        )
        self.assertIsInstance(row["score_factors"], dict)

    def test_postgres_upsert_accepts_legacy_rows_without_v2_keys(self):
        conn = MagicMock()
        cursor = conn.cursor.return_value.__enter__.return_value
        row = ss.row_from_item_score(
            {
                "id": 100,
                "title": "technical shorts",
                "price": {"amount": "80", "currency_code": "RON"},
                "user": {"id": 7, "login": "seller"},
                "_profile": {"country_code": "ro"},
            },
            {
                "deal_score": 8,
                "value_band": "hunt",
                "hunt_fit": True,
                "scam_risk": "low",
            },
            "Gym",
            "search",
        )
        for field in ss.V2_FIELDS:
            row.pop(field)

        ss.PsycopgScoredStore(conn).upsert_score(row)

        sql_row = cursor.execute.call_args.args[1]
        self.assertTrue(all(sql_row[field] is None for field in ss.V2_FIELDS))

    def test_runtime_schema_adds_v2_columns_before_rank_index(self):
        alters = "\n".join(ss.ALTERS)
        for field in ss.V2_FIELDS:
            self.assertIn(f"ADD COLUMN IF NOT EXISTS {field} ", alters)
        self.assertTrue(
            ss.ALTERS[-1].startswith(
                "CREATE INDEX IF NOT EXISTS scored_listings_v2_rank_idx"
            )
        )

    def test_listing_only_upsert_does_not_wipe_v2_score(self):
        store = ss.MemoryScoredStore()
        scored = ss.row_from_item_score(
            {
                "id": 101,
                "title": "dress",
                "price": {"amount": "90", "currency_code": "RON"},
                "user": {"id": 8, "login": "seller"},
                "_profile": {"country_code": "ro"},
            },
            {
                "score_version": 2,
                "buy_score": 90,
                "buy_band": "keep",
                "score_confidence": 0.8,
                "score_interval_low": 86,
                "score_interval_high": 94,
                "score_factors": {},
                "factor_evidence": {},
                "verification_concern": "none",
                "verification_reason": "",
                "hunt_fit": True,
                "reason": "strong",
            },
            "Maternity",
            "search",
        )
        store.upsert_score(scored)
        store.upsert_score(
            ss.row_from_item(
                {
                    "id": 101,
                    "title": "dress updated",
                    "price": {"amount": "85", "currency_code": "RON"},
                    "user": {"id": 8, "login": "seller"},
                    "_profile": {"country_code": "ro"},
                },
                "Maternity",
                "backfill",
            )
        )
        loaded = store.load_by_seller(8)[0]
        self.assertEqual(loaded["buy_score"], 90)
        self.assertEqual(loaded["title"], "dress updated")

    def test_scored_upsert_replaces_v2_fields_without_mixing_semantics(self):
        store = ss.MemoryScoredStore()
        item = {
            "id": 102,
            "title": "dress",
            "price": {"amount": "90", "currency_code": "RON"},
            "user": {"id": 8, "login": "seller"},
            "_profile": {"country_code": "ro"},
        }
        store.upsert_score(
            ss.row_from_item_score(
                item,
                {
                    "score_version": 2,
                    "buy_score": 90,
                    "buy_band": "keep",
                    "score_factors": {},
                    "factor_evidence": {},
                    "hunt_fit": True,
                },
                "Maternity",
                "search",
            )
        )
        store.upsert_score(
            ss.row_from_item_score(
                item,
                {
                    "deal_score": 8,
                    "value_band": "hunt",
                    "hunt_fit": True,
                    "scam_risk": "low",
                },
                "Maternity",
                "search",
            )
        )

        loaded = store.load_by_seller(8)[0]
        self.assertEqual(loaded["deal_score"], 8)
        self.assertIsNone(loaded["score_version"])
        self.assertIsNone(loaded["buy_score"])


if __name__ == "__main__":
    unittest.main()
