import path_setup  # noqa: F401
import copy
import unittest
from unittest.mock import patch

import buy_ranking as br
import scored_store
import vinted_bot as bot


def candidate(iid, score, low, high, watch="H", confidence=0.8):
    return {
        "item": {"id": iid, "title": str(iid)},
        "watch": watch,
        "score": {
            "score_version": 2,
            "buy_score": score,
            "buy_band": "keep",
            "score_confidence": confidence,
            "score_interval_low": low,
            "score_interval_high": high,
            "verification_concern": "none",
            "hunt_fit": True,
        },
    }


class RankingTests(unittest.TestCase):
    def test_pairs_only_overlapping_qualified_neighbors(self):
        rows = [
            candidate(1, 92, 87, 96),
            candidate(2, 89, 85, 93),
            candidate(3, 85, 83, 87),
            candidate(4, 84, 80, 88),
        ]
        pairs = br.comparison_pairs(
            rows, {"buy_scoring": {"pairwise_neighbors": 1}}
        )
        flattened = {key for pair in pairs for key in pair}
        self.assertNotIn("4:H", flattened)
        self.assertIn(("1:H", "2:H"), pairs)
        self.assertNotIn(("1:H", "3:H"), pairs)

    def test_candidate_key_includes_watch(self):
        self.assertNotEqual(
            br.candidate_key(candidate(1, 90, 85, 95, watch="Gym")),
            br.candidate_key(candidate(1, 90, 85, 95, watch="Maternity")),
        )

    def test_configured_keep_and_confidence_thresholds_control_pairs(self):
        rows = [
            candidate(1, 94, 90, 97, confidence=0.89),
            candidate(2, 93, 90, 96, confidence=0.95),
            candidate(3, 92, 89, 95, confidence=0.95),
        ]
        config = {
            "buy_scoring": {
                "keep_min_score": 93,
                "min_keep_confidence": 0.9,
            }
        }
        self.assertEqual(br.comparison_pairs(rows, config), [])

    def test_bradley_terry_orders_pairwise_winner(self):
        order = br.bradley_terry_rank(
            ["1:H", "2:H", "3:H"],
            [
                {"left": "1:H", "right": "2:H", "winner": "left"},
                {"left": "1:H", "right": "3:H", "winner": "left"},
                {"left": "2:H", "right": "3:H", "winner": "left"},
            ],
        )
        self.assertEqual(order, ["1:H", "2:H", "3:H"])

    def test_empty_outcomes_fall_back_to_score_order(self):
        ranked = br.apply_rankings(
            [candidate(2, 88, 84, 92), candidate(1, 91, 87, 95)],
            [],
        )
        self.assertEqual(
            [row["score"]["rank_position"] for row in ranked],
            [2, 1],
        )
        self.assertTrue(
            all(row["score"]["rank_confidence"] == "low" for row in ranked)
        )

    def test_disconnected_outcomes_fall_back_to_score_order(self):
        ranked = br.apply_rankings(
            [
                candidate(1, 90, 85, 95),
                candidate(2, 92, 87, 96),
                candidate(3, 91, 86, 95),
            ],
            [
                {
                    "left": "1:H",
                    "right": "2:H",
                    "winner": "left",
                    "confidence": 0.99,
                }
            ],
        )
        by_key = {br.candidate_key(row): row["score"] for row in ranked}
        self.assertEqual(by_key["2:H"]["rank_position"], 1)
        self.assertEqual(by_key["3:H"]["rank_position"], 2)
        self.assertEqual(by_key["1:H"]["rank_position"], 3)
        self.assertTrue(
            all(score["rank_confidence"] == "low" for score in by_key.values())
        )

    def test_ranking_never_changes_score_or_promotes_subthreshold_row(self):
        rows = [
            candidate(1, 90, 85, 95),
            candidate(2, 89, 84, 94),
            candidate(3, 84, 80, 90),
        ]
        before = copy.deepcopy(rows)
        ranked = br.apply_rankings(
            rows,
            [
                {
                    "left": "1:H",
                    "right": "2:H",
                    "winner": "right",
                    "confidence": 0.9,
                }
            ],
        )
        self.assertEqual(
            [row["score"]["buy_score"] for row in ranked],
            [row["score"]["buy_score"] for row in before],
        )
        self.assertNotIn("rank_position", ranked[2]["score"])
        self.assertNotIn("rank_confidence", ranked[2]["score"])


class RankingIntegrationTests(unittest.TestCase):
    def test_prompt_contains_only_requested_candidate_context(self):
        rows = [
            candidate(1, 92, 87, 96, watch="Gym"),
            candidate(2, 89, 85, 93, watch="Maternity"),
            candidate(3, 86, 82, 90, watch="Unpaired"),
        ]
        rows[0]["item"]["title"] = "requested left"
        rows[1]["item"]["title"] = "requested right"
        rows[2]["item"]["title"] = "must not leak"
        rows[0]["score"]["score_factors"] = {
            "usefulness": 90,
            "delivered_cost_ron": 102,
        }
        rows[0]["score"]["factor_evidence"] = {"usefulness": "daily wear"}

        prompt = bot._comparison_prompt(rows, [("1:Gym", "2:Maternity")])

        self.assertIn("requested left", prompt)
        self.assertIn("requested right", prompt)
        self.assertIn('"delivered_price_ron": 102', prompt)
        self.assertIn('"interval": [', prompt)
        self.assertIn("daily wear", prompt)
        self.assertNotIn("must not leak", prompt)
        self.assertNotIn("3:Unpaired", prompt)

    def test_zero_or_one_candidate_skips_model_calls(self):
        with (
            patch.object(bot, "_rank_with_gateway") as gateway,
            patch.object(bot, "_rank_with_gemini") as gemini,
        ):
            for rows in ([], [candidate(1, 90, 85, 95)]):
                with self.subTest(candidate_count=len(rows)):
                    ranked = bot.rank_candidates(
                        rows,
                        "gateway-key",
                        object(),
                        {},
                    )
                    self.assertEqual(ranked, rows)
            gateway.assert_not_called()
            gemini.assert_not_called()

    def test_malformed_gateway_result_falls_through_to_gemini(self):
        rows = [
            candidate(1, 92, 87, 96),
            candidate(2, 91, 86, 95),
        ]
        valid = [
            {
                "left": "1:H",
                "right": "2:H",
                "winner": "right",
                "confidence": 0.9,
                "reason": "more useful",
            }
        ]
        with (
            patch.object(
                bot,
                "_rank_with_gateway",
                return_value=[
                    {
                        "left": "1:H",
                        "right": "unknown:H",
                        "winner": "right",
                        "confidence": 0.9,
                        "reason": "invalid key",
                    }
                ],
            ),
            patch.object(bot, "_rank_with_gemini", return_value=valid) as gemini,
        ):
            ranked = bot.rank_candidates(
                rows,
                "gateway-key",
                object(),
                {},
            )
        gemini.assert_called_once()
        self.assertEqual(ranked[1]["score"]["rank_position"], 1)
        self.assertEqual(ranked[1]["score"]["rank_confidence"], "high")

    def test_provider_failures_fall_back_deterministically(self):
        rows = [
            candidate(1, 90, 85, 95),
            candidate(2, 92, 87, 96),
        ]
        with (
            patch.object(
                bot, "_rank_with_gateway", side_effect=RuntimeError("gateway down")
            ),
            patch.object(
                bot, "_rank_with_gemini", side_effect=RuntimeError("gemini down")
            ),
        ):
            ranked = bot.rank_candidates(
                rows,
                "gateway-key",
                object(),
                {},
            )
        self.assertEqual(ranked[1]["score"]["rank_position"], 1)
        self.assertTrue(
            all(row["score"]["rank_confidence"] == "low" for row in ranked)
        )

    def test_incomplete_disconnected_results_fall_back_deterministically(self):
        rows = [
            candidate(1, 92, 85, 97),
            candidate(2, 91, 85, 96),
            candidate(3, 90, 85, 95),
        ]
        incomplete = [
            {
                "left": "1:H",
                "right": "2:H",
                "winner": "right",
                "confidence": 0.99,
                "reason": "partial response",
            }
        ]
        config = {"buy_scoring": {"pairwise_neighbors": 1}}
        with (
            patch.object(bot, "_rank_with_gateway", return_value=incomplete),
            patch.object(bot, "_rank_with_gemini", return_value=incomplete),
        ):
            ranked = bot.rank_candidates(
                rows,
                "gateway-key",
                object(),
                config,
            )
        self.assertEqual(
            [row["score"]["rank_position"] for row in ranked],
            [1, 2, 3],
        )
        self.assertTrue(
            all(row["score"]["rank_confidence"] == "low" for row in ranked)
        )

    def test_rank_persistence_follows_initial_score_write(self):
        store = scored_store.MemoryScoredStore()
        row = candidate(1, 90, 85, 95)
        row["item"]["price"] = {"amount": 100, "currency_code": "RON"}
        store.upsert_score(
            scored_store.row_from_item_score(
                row["item"],
                row["score"],
                row["watch"],
                source="search",
            )
        )
        self.assertIsNone(store.load_recent()[0]["rank_position"])

        br.apply_rankings([row], [])
        bot.persist_ranked_candidates(store, [row], scored_store)

        persisted = store.load_recent()[0]
        self.assertEqual(persisted["buy_score"], 90)
        self.assertEqual(persisted["rank_position"], 1)
        self.assertEqual(persisted["rank_confidence"], "low")


if __name__ == "__main__":
    unittest.main()
