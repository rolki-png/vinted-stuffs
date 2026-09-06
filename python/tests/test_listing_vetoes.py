import path_setup  # noqa: F401
import unittest

import listing_vetoes as lv


class ApplyToFindsTests(unittest.TestCase):
    def test_hide_removes_find_by_default(self):
        rows = [
            {"id": 1, "title": "keep me", "deal_score": 9},
            {"id": 2, "title": "wedding midi", "deal_score": 10},
        ]
        vetoes = {2: "hidden"}
        out = lv.apply_to_finds(rows, vetoes)
        self.assertEqual([r["id"] for r in out], [1])
        self.assertNotIn("veto_status", out[0])

    def test_park_tags_and_sorts_after_active(self):
        rows = [
            {"id": 1, "title": "parked high", "deal_score": 10},
            {"id": 2, "title": "active mid", "deal_score": 8},
            {"id": 3, "title": "active high", "deal_score": 9},
        ]
        vetoes = {1: "parked"}
        out = lv.apply_to_finds(rows, vetoes)
        self.assertEqual([r["id"] for r in out], [2, 3, 1])
        self.assertEqual(out[2]["veto_status"], "parked")
        self.assertNotIn("veto_status", out[0])

    def test_modes_parked_hidden_all(self):
        rows = [
            {"id": 1, "title": "a"},
            {"id": 2, "title": "b"},
            {"id": 3, "title": "c"},
        ]
        vetoes = {1: "parked", 2: "hidden"}
        self.assertEqual(
            [r["id"] for r in lv.apply_to_finds(rows, vetoes, mode="parked")],
            [1],
        )
        self.assertEqual(
            [r["id"] for r in lv.apply_to_finds(rows, vetoes, mode="hidden")],
            [2],
        )
        all_rows = lv.apply_to_finds(rows, vetoes, mode="all")
        self.assertEqual([r["id"] for r in all_rows], [3, 1, 2])
        by_id = {r["id"]: r for r in all_rows}
        self.assertEqual(by_id[1]["veto_status"], "parked")
        self.assertEqual(by_id[2]["veto_status"], "hidden")
        self.assertNotIn("veto_status", by_id[3])

    def test_clear_restores_via_empty_map(self):
        rows = [{"id": 2, "title": "midi"}]
        out = lv.apply_to_finds(rows, {})
        self.assertEqual([r["id"] for r in out], [2])


class ApplyToBundlesTests(unittest.TestCase):
    def _bundle(self, *ids):
        return {
            "seller": "s",
            "listing_sum": 10.0 * len(ids),
            "checkout_extra_ron": 25,
            "items": [{"id": i, "title": f"t{i}", "price": 10.0} for i in ids],
        }

    def test_hide_member_shrinks_to_two(self):
        bundles = [self._bundle(1, 2, 3)]
        out = lv.apply_to_bundles(bundles, {3: "hidden"})
        self.assertEqual(len(out), 1)
        self.assertEqual([it["id"] for it in out[0]["items"]], [1, 2])
        self.assertEqual(out[0]["listing_sum"], 20.0)

    def test_hide_leaving_one_drops_bundle(self):
        bundles = [self._bundle(1, 2)]
        out = lv.apply_to_bundles(bundles, {2: "hidden"})
        self.assertEqual(out, [])

    def test_park_member_tags_bundle_and_sorts_down(self):
        active = self._bundle(10, 11)
        parked = self._bundle(20, 21)
        out = lv.apply_to_bundles([parked, active], {20: "parked"})
        self.assertEqual(len(out), 2)
        self.assertEqual([it["id"] for it in out[0]["items"]], [10, 11])
        self.assertEqual(out[1]["veto_status"], "parked")
        self.assertEqual([it["id"] for it in out[1]["items"]], [20, 21])


class BotPredicateTests(unittest.TestCase):
    def test_park_is_not_hidden_for_bot(self):
        vetoes = {1: "hidden", 2: "parked"}
        self.assertTrue(lv.is_hidden(vetoes, 1))
        self.assertFalse(lv.is_hidden(vetoes, 2))
        self.assertTrue(lv.is_parked(vetoes, 2))
        store = lv.MemoryVetoStore()
        store.set_status(1, "hidden")
        store.set_status(2, "parked")
        self.assertEqual(store.load_hidden_ids(), {1})

    def test_filter_scored_rows_gates_keep_alert_path(self):
        hidden = {2}
        rows = [
            {"item": {"id": 1}, "score": {"deal_score": 9}},
            {"item": {"id": 2}, "score": {"deal_score": 10}},
            {"item": {"id": 3}, "score": {"deal_score": 8}},
        ]
        kept = lv.filter_scored_rows(rows, hidden)
        self.assertEqual([r["item"]["id"] for r in kept], [1, 3])
        self.assertTrue(lv.item_is_hidden(2, hidden))
        self.assertFalse(lv.item_is_hidden(1, hidden))
        # Parked ids are not in hidden set → still alertable
        self.assertFalse(lv.item_is_hidden(99, {1}))
        self.assertEqual(
            [it["id"] for it in lv.filter_items([{"id": 1}, {"id": 2}], {2})],
            [1],
        )


class MemoryStoreTests(unittest.TestCase):
    def test_set_clear_load_map(self):
        store = lv.MemoryVetoStore()
        store.set_status(42, "parked")
        store.set_status(99, "hidden")
        self.assertEqual(store.load_map(), {42: "parked", 99: "hidden"})
        store.set_status(42, "hidden")  # upgrade park → hide
        self.assertEqual(store.load_map()[42], "hidden")
        store.clear(99)
        self.assertEqual(store.load_map(), {42: "hidden"})


if __name__ == "__main__":
    unittest.main()
