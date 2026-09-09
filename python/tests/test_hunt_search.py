import path_setup  # noqa: F401
"""Brand hunts must search the Vinted catalog by brand id, not keywords."""
import unittest
from unittest.mock import patch

import vinted_bot as bot

TEN_THOUSAND = {
    "name": "Ten Thousand gym M-L",
    "query": "ten thousand",
    "country": "ro",
    "order": "newest_first",
    "per_page": 24,
    "price_to": 250,
    "brand_ids": [3162601],
}

KEYWORD_HUNT = {
    "name": "Gym seed Adidas shorts M-L",
    "query": "adidas short",
    "country": "ro",
    "order": "newest_first",
    "per_page": 50,
}


class HuntSearchTests(unittest.TestCase):
    def test_brand_hunt_omits_keyword_from_catalog_search(self):
        plan = bot._watch_search_plan(TEN_THOUSAND)
        self.assertEqual(plan["query"], "")
        self.assertEqual(plan["brandIds"], [3162601])
        self.assertEqual(plan["name"], "Ten Thousand gym M-L")

    def test_keyword_hunt_still_sends_search_text(self):
        plan = bot._watch_search_plan(KEYWORD_HUNT)
        self.assertEqual(plan["query"], "adidas short")
        self.assertNotIn("brandIds", plan)

    def test_new_brand_ids_need_a_catalog_sweep(self):
        state = {}
        self.assertTrue(bot.hunt_needs_brand_sweep(TEN_THOUSAND, state))
        self.assertFalse(bot.hunt_needs_brand_sweep(KEYWORD_HUNT, state))
        bot.mark_brand_swept(state, TEN_THOUSAND)
        self.assertFalse(bot.hunt_needs_brand_sweep(TEN_THOUSAND, state))
        changed = {**TEN_THOUSAND, "brand_ids": [3162601, 99]}
        self.assertTrue(bot.hunt_needs_brand_sweep(changed, state))

    def test_new_brand_hunt_paginates_in_mixed_batch(self):
        def fake_vinted(args, timeout=60, stdin_payload=None):
            searches = stdin_payload["searches"]
            by_name = {s["name"]: s for s in searches}
            self.assertTrue(by_name[TEN_THOUSAND["name"]].get("all"))
            self.assertNotIn("all", by_name[KEYWORD_HUNT["name"]])
            return {"searches": [{"name": n, "items": []} for n in by_name]}

        with patch.object(bot, "_vinted_json", side_effect=fake_vinted):
            bot.search_all_watches(
                [TEN_THOUSAND, KEYWORD_HUNT],
                sweep_names={TEN_THOUSAND["name"]},
            )

    def test_brand_hunt_drops_keyword_hits_that_are_not_that_brand(self):
        junk = {
            "id": 1,
            "title": "An Abundance of Katherines - John Green",
            "brand": "Penguin",
            "price": {"amount": "55", "currency_code": "RON"},
        }
        hit = {
            "id": 2,
            "title": "Interval Shorts",
            "brand": "Ten Thousand",
            "brand_id": 3162601,
            "price": {"amount": "90", "currency_code": "RON"},
        }

        def fake_vinted(args, timeout=60, stdin_payload=None):
            self.assertEqual(stdin_payload["searches"][0]["query"], "")
            return {"searches": [{"name": TEN_THOUSAND["name"], "items": [junk, hit]}]}

        with patch.object(bot, "_vinted_json", side_effect=fake_vinted):
            found = bot.search_all_watches([TEN_THOUSAND])

        titles = [it["title"] for it in found[TEN_THOUSAND["name"]]]
        self.assertEqual(titles, ["Interval Shorts"])
        self.assertEqual(found[TEN_THOUSAND["name"]][0]["brand_title"], "Ten Thousand")

    def test_brand_hunt_does_not_attach_closet_items_from_title_keywords(self):
        album = {
            "title": "Boney M Ten thousand lightyears",
            "brand_title": "Boney M",
        }
        shorts = {
            "title": "Interval Training Briefs M",
            "brand_title": "Ten Thousand",
            "brand_id": 3162601,
        }
        self.assertEqual(bot.matching_watches(album, [TEN_THOUSAND, KEYWORD_HUNT]), [])
        names = [w["name"] for w in bot.matching_watches(shorts, [TEN_THOUSAND, KEYWORD_HUNT])]
        self.assertEqual(names[0], "Ten Thousand gym M-L")
        self.assertNotIn("Gym seed Adidas shorts M-L", names)

    def test_purge_drops_off_brand_index_and_seen_keys(self):
        import hunt_catalog as hc

        rows = [
            {"id": 1, "watch": "Ten Thousand gym M-L", "brand": "Penguin", "title": "book"},
            {"id": 2, "watch": "Ten Thousand gym M-L", "brand": "Ten Thousand", "title": "shorts"},
            {"id": 3, "watch": "Gym seed Adidas shorts M-L", "brand": "Nike", "title": "seed"},
        ]
        kept = hc.filter_scored_export_rows(rows, [TEN_THOUSAND, KEYWORD_HUNT])
        self.assertEqual([r["id"] for r in kept], [2, 3])
        keep_pairs = hc.keep_pairs_from_rows(kept)
        keys = [
            "1:Ten Thousand gym M-L",
            "2:Ten Thousand gym M-L",
            "9:Ten Thousand gym M-L",
            "3:Gym seed Adidas shorts M-L",
        ]
        self.assertEqual(
            hc.filter_seen_keys(keys, [TEN_THOUSAND, KEYWORD_HUNT], keep_pairs),
            ["2:Ten Thousand gym M-L", "3:Gym seed Adidas shorts M-L"],
        )
        pool = [
            {"watch": TEN_THOUSAND["name"], "item": {"id": 1, "brand_title": "Penguin"}},
            {"watch": TEN_THOUSAND["name"], "item": {"id": 2, "brand_title": "Ten Thousand"}},
        ]
        self.assertEqual(
            [r["item"]["id"] for r in hc.filter_pool_rows(pool, [TEN_THOUSAND])],
            [2],
        )
        mama = {
            "name": "Mamalicious leggings XL-L/XL",
            "query": "mamalicious leggings",
            "brand_ids": [4694493],
        }
        self.assertTrue(
            hc.item_matches_hunt_catalog({"brand_title": "Mamalicious"}, mama)
        )
        nb = {
            "name": "New Balance 990 size 43",
            "query": "new balance 990",
            "brand_ids": [1775],
        }
        self.assertTrue(hc.item_matches_hunt_catalog({"brand_title": "New Balance"}, nb))
        self.assertFalse(
            hc.item_matches_hunt_catalog({"brand_title": "Dr. Martens"}, TEN_THOUSAND)
        )


if __name__ == "__main__":
    unittest.main()
