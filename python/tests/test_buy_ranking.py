import path_setup  # noqa: F401
import copy
import inspect
import io
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

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

    def test_configured_max_and_neighbor_limits_bound_pair_generation(self):
        rows = [
            candidate(iid, 100 - iid, 80, 100)
            for iid in range(1, 7)
        ]
        pairs = br.comparison_pairs(
            rows,
            {
                "buy_scoring": {
                    "pairwise_max_candidates": 4,
                    "pairwise_neighbors": 2,
                }
            },
        )
        self.assertEqual(
            pairs,
            [
                ("1:H", "2:H"),
                ("1:H", "3:H"),
                ("2:H", "3:H"),
                ("2:H", "4:H"),
                ("3:H", "4:H"),
            ],
        )

    def test_bundle_hunt_and_legacy_candidates_are_excluded(self):
        rows = [
            candidate(1, 92, 87, 96),
            candidate(2, 91, 86, 95),
            candidate(3, 99, 90, 100, watch="Bundle"),
            candidate(4, 99, 90, 100, watch="Legacy"),
        ]
        rows[2]["watch_obj"] = {"bundle_hunt": True}
        rows[3]["score"] = {
            "deal_score": 10,
            "value_band": "steal",
            "hunt_fit": True,
            "rank_position": 1,
            "rank_confidence": "high",
        }
        self.assertEqual(
            br.comparison_pairs(rows, {}),
            [("1:H", "2:H")],
        )
        ranked = br.apply_rankings(rows, [], {})
        self.assertNotIn("rank_position", ranked[2]["score"])
        self.assertNotIn("rank_position", ranked[3]["score"])

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

    def test_stale_ranks_are_cleared_outside_active_ranked_set(self):
        active = [candidate(1, 90, 85, 95), candidate(2, 89, 84, 94)]
        subthreshold = candidate(3, 84, 80, 90)
        bundle = candidate(4, 95, 90, 99, watch="Bundle")
        bundle["watch_obj"] = {"bundle_hunt": True}
        legacy = candidate(5, 95, 90, 99, watch="Legacy")
        legacy["score"] = {
            "deal_score": 10,
            "hunt_fit": True,
        }
        rows = active + [subthreshold, bundle, legacy]
        for row in rows:
            row["score"]["rank_position"] = 99
            row["score"]["rank_confidence"] = "high"

        ranked = br.apply_rankings(rows, [], {})

        self.assertEqual(
            {row["score"]["rank_position"] for row in active},
            {1, 2},
        )
        for row in (subthreshold, bundle, legacy):
            self.assertNotIn("rank_position", row["score"])
            self.assertNotIn("rank_confidence", row["score"])


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
            patch.object(bot, "_rank_with_gemini", return_value=[]) as gemini,
        ):
            ranked = bot.rank_candidates(
                rows,
                "gateway-key",
                object(),
                config,
            )
        gemini.assert_called_once()
        self.assertEqual(
            [row["score"]["rank_position"] for row in ranked],
            [1, 2, 3],
        )
        self.assertTrue(
            all(row["score"]["rank_confidence"] == "low" for row in ranked)
        )

    def test_disconnected_gateway_falls_through_to_connected_gemini(self):
        rows = [
            candidate(1, 92, 85, 97),
            candidate(2, 91, 85, 96),
            candidate(3, 90, 85, 95),
        ]
        gateway_incomplete = [
            {
                "left": "1:H",
                "right": "2:H",
                "winner": "left",
                "confidence": 0.95,
                "reason": "gateway partial",
            }
        ]
        gemini_connected = [
            {
                "left": "1:H",
                "right": "2:H",
                "winner": "right",
                "confidence": 0.9,
                "reason": "second is better",
            },
            {
                "left": "2:H",
                "right": "3:H",
                "winner": "right",
                "confidence": 0.9,
                "reason": "third is better",
            },
        ]
        config = {"buy_scoring": {"pairwise_neighbors": 1}}
        with (
            patch.object(
                bot, "_rank_with_gateway", return_value=gateway_incomplete
            ),
            patch.object(
                bot, "_rank_with_gemini", return_value=gemini_connected
            ) as gemini,
        ):
            ranked = bot.rank_candidates(
                rows,
                "gateway-key",
                object(),
                config,
            )
        gemini.assert_called_once()
        self.assertEqual(
            [row["score"]["rank_position"] for row in ranked],
            [3, 2, 1],
        )
        self.assertTrue(
            all(row["score"]["rank_confidence"] == "high" for row in ranked)
        )

    def test_connected_gateway_result_skips_gemini(self):
        rows = [
            candidate(1, 92, 85, 97),
            candidate(2, 91, 85, 96),
            candidate(3, 90, 85, 95),
        ]
        connected = [
            {
                "left": "1:H",
                "right": "2:H",
                "winner": "right",
                "confidence": 0.9,
                "reason": "second is better",
            },
            {
                "left": "2:H",
                "right": "3:H",
                "winner": "right",
                "confidence": 0.9,
                "reason": "third is better",
            },
        ]
        with (
            patch.object(bot, "_rank_with_gateway", return_value=connected),
            patch.object(bot, "_rank_with_gemini") as gemini,
        ):
            ranked = bot.rank_candidates(
                rows,
                "gateway-key",
                object(),
                {"buy_scoring": {"pairwise_neighbors": 1}},
            )
        gemini.assert_not_called()
        self.assertEqual(
            [row["score"]["rank_position"] for row in ranked],
            [3, 2, 1],
        )

    def test_valid_pair_rows_survive_malformed_and_duplicate_siblings(self):
        rows = [
            candidate(1, 92, 85, 97),
            candidate(2, 91, 85, 96),
            candidate(3, 90, 85, 95),
        ]
        mixed = [
            {
                "left": "1:H",
                "right": "2:H",
                "winner": "right",
                "confidence": 0.9,
                "reason": "valid first edge",
            },
            {
                "left": "1:H",
                "right": "unknown:H",
                "winner": "right",
                "confidence": 0.9,
                "reason": "unknown candidate",
            },
            {
                "left": "1:H",
                "right": "2:H",
                "winner": "left",
                "confidence": 0.9,
                "reason": "duplicate edge",
            },
            {
                "left": "2:H",
                "right": "3:H",
                "winner": "right",
                "confidence": 0.9,
                "reason": "valid second edge",
            },
            {
                "left": "2:H",
                "right": "3:H",
                "winner": "invalid",
                "confidence": 0.9,
                "reason": "malformed winner",
            },
        ]
        expected = [
            {
                "left": "1:H",
                "right": "2:H",
                "winner": "right",
                "confidence": 0.9,
                "reason": "valid first edge",
            },
            {
                "left": "2:H",
                "right": "3:H",
                "winner": "right",
                "confidence": 0.9,
                "reason": "valid second edge",
            },
        ]
        pairs = [("1:H", "2:H"), ("2:H", "3:H")]
        self.assertEqual(bot._valid_rank_outcomes(mixed, pairs), expected)

        with (
            patch.object(bot, "_rank_with_gateway", return_value=mixed),
            patch.object(bot, "_rank_with_gemini", return_value=[]) as gemini,
        ):
            ranked = bot.rank_candidates(
                rows,
                "gateway-key",
                object(),
                {"buy_scoring": {"pairwise_neighbors": 1}},
            )
        gemini.assert_not_called()
        self.assertEqual(
            [row["score"]["rank_position"] for row in ranked],
            [3, 2, 1],
        )

    def test_provider_results_rank_only_top_configured_shortlist(self):
        rows = [
            candidate(1001 + index, 100 - index // 2, 0, 100)
            for index in range(22)
        ]
        config = {
            "buy_scoring": {
                "pairwise_max_candidates": 20,
                "pairwise_neighbors": 1,
            }
        }
        pairs = br.comparison_pairs(rows, config)
        outcomes = [
            {
                "left": left,
                "right": right,
                "winner": "right",
                "confidence": 0.9,
                "reason": "right wins",
            }
            for left, right in pairs
        ]
        with patch.object(
            bot, "_rank_with_gateway", return_value=outcomes
        ) as gateway:
            ranked = bot.rank_candidates(rows, "gateway-key", None, config)

        gateway.assert_called_once()
        self.assertEqual(len(pairs), 19)
        self.assertEqual(ranked[19]["score"]["rank_position"], 1)
        self.assertEqual(ranked[19]["score"]["rank_confidence"], "high")
        self.assertEqual(
            [row["score"]["rank_position"] for row in ranked[20:]],
            [21, 22],
        )
        self.assertTrue(
            all(
                row["score"]["rank_confidence"] == "low"
                for row in ranked[20:]
            )
        )

    def test_no_configured_provider_falls_back_without_failure_noise(self):
        rows = [candidate(1, 92, 85, 97), candidate(2, 91, 85, 96)]
        stderr = io.StringIO()
        with patch("sys.stderr", new=stderr):
            ranked = bot.rank_candidates(rows, "", None, {})
        self.assertEqual(
            [row["score"]["rank_position"] for row in ranked],
            [1, 2],
        )
        self.assertEqual(stderr.getvalue(), "")

    def test_rank_persistence_follows_initial_score_write(self):
        store = scored_store.MemoryScoredStore()
        row = candidate(1, 90, 85, 95)
        row["item"]["price"] = {"amount": 100, "currency_code": "RON"}
        scored_at = datetime(2026, 9, 7, tzinfo=timezone.utc)
        store.upsert_score(
            scored_store.row_from_item_score(
                row["item"],
                row["score"],
                row["watch"],
                source="search",
                scored_at=scored_at,
            )
        )
        self.assertIsNone(store.load_recent()[0]["rank_position"])

        br.apply_rankings([row], [])
        bot.persist_ranked_candidates(store, [row])

        persisted = store.load_recent()[0]
        self.assertEqual(persisted["buy_score"], 90)
        self.assertEqual(persisted["rank_position"], 1)
        self.assertEqual(persisted["rank_confidence"], "low")
        self.assertEqual(persisted["source"], "search")
        self.assertEqual(persisted["scored_at"], scored_at)

    def test_rank_persistence_coerces_numeric_string_item_id(self):
        store = MagicMock()
        row = candidate("123", 90, 85, 95)
        br.apply_rankings([row], [])

        bot.persist_ranked_candidates(store, [row])

        store.replace_rankings.assert_called_once_with(
            [
                {
                    "item_id": 123,
                    "hunt_name": "H",
                    "rank_position": 1,
                    "rank_confidence": "low",
                }
            ]
        )

    def test_rank_persistence_skips_invalid_id_and_still_clears_stale_ranks(self):
        store = MagicMock()
        row = candidate("not-an-id", 90, 85, 95)
        br.apply_rankings([row], [])
        stderr = io.StringIO()

        with patch("sys.stderr", new=stderr):
            bot.persist_ranked_candidates(store, [row])

        store.replace_rankings.assert_called_once_with([])
        self.assertIn("invalid item id 'not-an-id'", stderr.getvalue())
        self.assertIn("not-an-id:H", stderr.getvalue())

    def test_main_assigns_ranking_return_before_rank_persistence_and_selection(self):
        source = inspect.getsource(bot.main)
        rank_call = source.index("merged = rank_candidates(")
        rank_write = source.index("persist_ranked_candidates(")
        selection = source.index("assemble_bundles(")
        self.assertLess(rank_call, rank_write)
        self.assertLess(rank_write, selection)


if __name__ == "__main__":
    unittest.main()
