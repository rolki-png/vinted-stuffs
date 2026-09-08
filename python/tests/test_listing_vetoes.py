import path_setup  # noqa: F401
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import listing_vetoes as lv


class ApplyToFindsTests(unittest.TestCase):
    def test_remove_omits_find_by_default(self):
        rows = [
            {"id": 1, "title": "keep me", "deal_score": 9},
            {"id": 2, "title": "sold midi", "deal_score": 10},
        ]
        vetoes = {2: "removed"}
        out = lv.apply_to_finds(rows, vetoes)
        self.assertEqual([r["id"] for r in out], [1])
        self.assertNotIn("veto_status", out[0])

    def test_legacy_hidden_status_treated_as_removed(self):
        rows = [{"id": 1}, {"id": 2}]
        out = lv.apply_to_finds(rows, {2: "hidden"})
        self.assertEqual([r["id"] for r in out], [1])

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

    def test_modes_parked_and_all_omit_removed(self):
        rows = [
            {"id": 1, "title": "a"},
            {"id": 2, "title": "b"},
            {"id": 3, "title": "c"},
        ]
        vetoes = {1: "parked", 2: "removed"}
        self.assertEqual(
            [r["id"] for r in lv.apply_to_finds(rows, vetoes, mode="parked")],
            [1],
        )
        all_rows = lv.apply_to_finds(rows, vetoes, mode="all")
        self.assertEqual([r["id"] for r in all_rows], [3, 1])
        by_id = {r["id"]: r for r in all_rows}
        self.assertEqual(by_id[1]["veto_status"], "parked")
        self.assertNotIn("veto_status", by_id[3])
        with self.assertRaises(ValueError):
            lv.apply_to_finds(rows, vetoes, mode="hidden")

    def test_bought_omitted_from_active_shown_in_bought_and_all(self):
        rows = [
            {"id": 1, "title": "active"},
            {"id": 2, "title": "bought"},
            {"id": 3, "title": "parked"},
            {"id": 4, "title": "removed"},
        ]
        vetoes = {2: "bought", 3: "parked", 4: "removed"}
        self.assertEqual(
            [r["id"] for r in lv.apply_to_finds(rows, vetoes, mode="active")],
            [1, 3],
        )
        bought = lv.apply_to_finds(rows, vetoes, mode="bought")
        self.assertEqual([r["id"] for r in bought], [2])
        self.assertEqual(bought[0]["veto_status"], "bought")
        all_rows = lv.apply_to_finds(rows, vetoes, mode="all")
        self.assertEqual([r["id"] for r in all_rows], [1, 3, 2])
        self.assertNotIn(4, [r["id"] for r in all_rows])
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

    def test_remove_member_shrinks_to_two(self):
        bundles = [self._bundle(1, 2, 3)]
        out = lv.apply_to_bundles(bundles, {3: "removed"})
        self.assertEqual(len(out), 1)
        self.assertEqual([it["id"] for it in out[0]["items"]], [1, 2])
        self.assertEqual(out[0]["listing_sum"], 20.0)

    def test_remove_leaving_one_drops_bundle(self):
        bundles = [self._bundle(1, 2)]
        out = lv.apply_to_bundles(bundles, {2: "removed"})
        self.assertEqual(out, [])

    def test_bought_member_stripped_from_active_like_purchased(self):
        bundles = [self._bundle(1, 2, 3)]
        out = lv.apply_to_bundles(bundles, {3: "bought"}, mode="active")
        self.assertEqual(len(out), 1)
        self.assertEqual([it["id"] for it in out[0]["items"]], [1, 2])
        out2 = lv.apply_to_bundles([self._bundle(1, 2)], {2: "bought"}, mode="active")
        self.assertEqual(out2, [])

    def test_park_member_tags_bundle_and_sorts_down(self):
        active = self._bundle(10, 11)
        parked = self._bundle(20, 21)
        out = lv.apply_to_bundles([parked, active], {20: "parked"})
        self.assertEqual(len(out), 2)
        self.assertEqual([it["id"] for it in out[0]["items"]], [10, 11])
        self.assertEqual(out[1]["veto_status"], "parked")
        self.assertEqual([it["id"] for it in out[1]["items"]], [20, 21])


class BotPredicateTests(unittest.TestCase):
    def test_park_is_not_removed_for_bot(self):
        vetoes = {1: "removed", 2: "parked"}
        self.assertTrue(lv.is_removed(vetoes, 1))
        self.assertFalse(lv.is_removed(vetoes, 2))
        self.assertTrue(lv.is_parked(vetoes, 2))
        store = lv.MemoryVetoStore()
        store.set_status(1, "removed")
        store.set_status(2, "parked")
        self.assertEqual(store.load_removed_ids(), {1})

    def test_suppress_ids_include_bought_not_parked(self):
        store = lv.MemoryVetoStore()
        store.set_status(1, "removed")
        store.set_status(2, "bought")
        store.set_status(3, "parked")
        self.assertEqual(store.load_suppress_ids(), {1, 2})
        self.assertEqual(store.load_removed_ids(), {1})
        self.assertTrue(lv.is_bought({2: "bought"}, 2))
    def test_filter_scored_rows_gates_keep_alert_path(self):
        removed = {2}
        rows = [
            {"item": {"id": 1}, "score": {"deal_score": 9}},
            {"item": {"id": 2}, "score": {"deal_score": 10}},
            {"item": {"id": 3}, "score": {"deal_score": 8}},
        ]
        kept = lv.filter_scored_rows(rows, removed)
        self.assertEqual([r["item"]["id"] for r in kept], [1, 3])
        self.assertTrue(lv.item_is_removed(2, removed))
        self.assertFalse(lv.item_is_removed(1, removed))
        self.assertFalse(lv.item_is_removed(99, {1}))
        self.assertEqual(
            [it["id"] for it in lv.filter_items([{"id": 1}, {"id": 2}], {2})],
            [1],
        )


class MemoryStoreTests(unittest.TestCase):
    def test_set_clear_load_map(self):
        store = lv.MemoryVetoStore()
        store.set_status(42, "parked")
        store.set_status(99, "hidden")  # legacy → removed
        self.assertEqual(store.load_map(), {42: "parked", 99: "removed"})
        store.set_status(42, "removed")
        self.assertEqual(store.load_map()[42], "removed")
        store.clear(99)
        self.assertEqual(store.load_map(), {42: "removed"})
        self.assertEqual(store.load_removed_ids(), {42})

    def test_remove_reason_round_trip_and_no_stale_reason(self):
        store = lv.MemoryVetoStore()
        store.set_status(1, "removed", {"hunt_family": "gym"}, "poor_value")
        self.assertEqual(store.load_outcomes()[0]["reason_code"], "poor_value")
        store.set_status(1, "bought", {"hunt_family": "gym"})
        self.assertIsNone(store.load_outcomes()[0]["reason_code"])

    def test_invalid_remove_reason_rejected(self):
        store = lv.MemoryVetoStore()
        with self.assertRaisesRegex(ValueError, "invalid remove reason"):
            store.set_status(1, "removed", {}, "brand_bad")

    def test_enrichment_and_outcomes_by_family(self):
        store = lv.MemoryVetoStore()
        store.set_status(
            1,
            "bought",
            {
                "hunt_name": "Lululemon gym M-L",
                "hunt_family": "gym",
                "brand": "Lululemon",
                "size": "L",
                "price_ron": 90,
                "value_band": "steal",
                "deal_score": 9,
                "title": "ABC shorts",
            },
        )
        store.set_status(
            2,
            "removed",
            {
                "hunt_family": "gym",
                "brand": "Nike",
                "size": "M",
                "title": "meh",
            },
        )
        store.set_status(3, "parked", {"hunt_family": "gym", "brand": "X"})
        store.set_status(
            4,
            "removed",
            {"hunt_family": "maternity", "brand": "Seraphine", "title": "dress"},
        )
        gym = store.load_outcomes("gym")
        self.assertEqual({r["item_id"] for r in gym}, {1, 2})
        self.assertTrue(all(r["status"] in ("bought", "removed") for r in gym))
        bought = next(r for r in gym if r["item_id"] == 1)
        self.assertEqual(bought["brand"], "Lululemon")
        self.assertEqual(bought["title"], "ABC shorts")
        mat = store.load_outcomes("maternity")
        self.assertEqual([r["item_id"] for r in mat], [4])

    def test_v2_enrichment_round_trip_and_legacy_stale_clearing(self):
        store = lv.MemoryVetoStore()
        store.set_status(
            5,
            "bought",
            {"score_version": 2, "buy_score": 88, "buy_band": "keep"},
        )
        v2 = store.load_outcomes()[0]
        self.assertEqual(v2["score_version"], 2)
        self.assertEqual(v2["buy_score"], 88)
        self.assertEqual(v2["buy_band"], "keep")
        self.assertIsNone(v2["deal_score"])
        self.assertIsNone(v2["value_band"])

        store.set_status(
            5,
            "removed",
            {"deal_score": 9, "value_band": "steal"},
            "poor_value",
        )
        legacy = store.load_outcomes()[0]
        self.assertEqual(legacy["score_version"], 2)
        self.assertEqual(legacy["buy_score"], 88)
        self.assertEqual(legacy["buy_band"], "keep")
        self.assertIsNone(legacy["deal_score"])
        self.assertIsNone(legacy["value_band"])

    def test_metadata_update_preserves_v2_score_context(self):
        store = lv.MemoryVetoStore()
        store.set_status(
            6,
            "removed",
            {"score_version": 2, "buy_score": 91, "buy_band": "keep"},
            "poor_value",
        )

        store.set_status(6, "bought", {"title": "updated title"})

        row = store.load_outcomes()[0]
        self.assertEqual(row["score_version"], 2)
        self.assertEqual(row["buy_score"], 91)
        self.assertEqual(row["buy_band"], "keep")
        self.assertEqual(row["title"], "updated title")

    def test_partial_or_invalid_score_context_preserves_existing_scale(self):
        store = lv.MemoryVetoStore()
        store.set_status(
            8,
            "removed",
            {"deal_score": 9, "value_band": "steal", "title": "old"},
            "poor_value",
        )

        store.set_status(
            8,
            "removed",
            {"score_version": 2, "buy_score": 88, "title": "partial v2"},
            "poor_value",
        )
        legacy = store.load_outcomes()[0]
        self.assertIsNone(legacy["deal_score"])
        self.assertIsNone(legacy["value_band"])
        self.assertIsNone(legacy["score_version"])
        self.assertEqual(legacy["title"], "partial v2")

        store.set_status(
            9,
            "bought",
            {"score_version": 2, "buy_score": 90, "buy_band": "keep"},
        )
        store.set_status(9, "bought", {"deal_score": 10, "title": "partial legacy"})
        v2 = next(row for row in store.load_outcomes() if row["item_id"] == 9)
        self.assertEqual(v2["score_version"], 2)
        self.assertEqual(v2["buy_score"], 90)
        self.assertEqual(v2["buy_band"], "keep")
        self.assertIsNone(v2["deal_score"])
        self.assertEqual(v2["title"], "partial legacy")

        store.set_status(
            9,
            "bought",
            {
                "score_version": 2,
                "buy_score": 101,
                "buy_band": "exceptional",
                "deal_score": 9,
                "value_band": "steal",
            },
        )
        still_v2 = next(
            row for row in store.load_outcomes() if row["item_id"] == 9
        )
        self.assertEqual(still_v2["buy_score"], 90)
        self.assertEqual(still_v2["buy_band"], "keep")


class PsycopgStoreTests(unittest.TestCase):
    def test_upsert_binds_explicit_score_update_decision(self):
        conn = MagicMock()
        cursor = conn.cursor.return_value.__enter__.return_value
        store = lv.PsycopgVetoStore(conn)

        store.set_status(
            10,
            "bought",
            {"score_version": 2, "buy_score": 88, "buy_band": "keep"},
        )
        params = cursor.execute.call_args.args[1]
        self.assertEqual(params["score_update_kind"], "v2")

        store.set_status(10, "bought", {"score_version": 2, "buy_score": 91})
        params = cursor.execute.call_args.args[1]
        self.assertEqual(params["score_update_kind"], "preserve")
        self.assertIsNone(params["score_version"])
        self.assertIsNone(params["buy_score"])
        self.assertIsNone(params["buy_band"])

        store.set_status(
            10,
            "removed",
            {"deal_score": 9, "value_band": "steal"},
            "poor_value",
        )
        params = cursor.execute.call_args.args[1]
        self.assertEqual(params["score_update_kind"], "preserve")

    def test_v2_outcome_load_round_trip(self):
        conn = MagicMock()
        cursor = conn.cursor.return_value.__enter__.return_value
        updated_at = datetime(2026, 9, 7, tzinfo=timezone.utc)
        cursor.fetchall.return_value = [
            (
                7,
                "bought",
                None,
                "Gym",
                "gym",
                "Craft",
                "L",
                80.0,
                None,
                None,
                2,
                88,
                "keep",
                "Technical shorts",
                updated_at,
            )
        ]

        outcomes = lv.PsycopgVetoStore(conn).load_outcomes("gym")

        self.assertEqual(outcomes[0]["score_version"], 2)
        self.assertEqual(outcomes[0]["buy_score"], 88)
        self.assertEqual(outcomes[0]["buy_band"], "keep")
        self.assertIsNone(outcomes[0]["deal_score"])
        self.assertEqual(outcomes[0]["updated_at"], updated_at.isoformat())

    def test_runtime_and_standalone_schemas_are_v2_symmetric(self):
        migration = (
            Path(__file__).resolve().parents[1]
            / "sql"
            / "005_listing_veto_v2_scores.sql"
        ).read_text()
        alters = "\n".join(lv.ALTER_COLUMNS_SQL)
        for field, sql_type in {
            "score_version": "INT",
            "buy_score": "INT",
            "buy_band": "TEXT",
        }.items():
            self.assertIn(f"{field} {sql_type} NULL", lv.DDL)
            self.assertIn(
                f"ADD COLUMN IF NOT EXISTS {field} {sql_type} NULL", alters
            )
            self.assertIn(
                f"ADD COLUMN IF NOT EXISTS {field} {sql_type} NULL", migration
            )
            self.assertIn(field, lv.UPSERT_SQL)
            self.assertIn(field, lv.LOAD_SQL)


if __name__ == "__main__":
    unittest.main()
