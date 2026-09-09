import path_setup  # noqa: F401
import json
import unittest
from pathlib import Path

import bundle_score as bs


def member(item_id, buy_score, *, role="extra", confidence=0.8, **overrides):
    row = {
        "id": item_id,
        "role": role,
        "score_version": 2,
        "buy_score": buy_score,
        "score_confidence": confidence,
        "verification_concern": "none",
        "hunt_fit": True,
    }
    row.update(overrides)
    return row


class BundleScoreTests(unittest.TestCase):
    def test_worse_anchor_cannot_improve_score(self):
        strong = bs.calculate_bundle_score(
            [member(1, 92, role="keep"), member(2, 70)],
            kind="keep_bundle",
        )
        weak = bs.calculate_bundle_score(
            [member(1, 80, role="keep"), member(2, 70)],
            kind="keep_bundle",
        )
        self.assertGreater(strong["bundle_score"], weak["bundle_score"])

    def test_blocked_item_ignored(self):
        base = bs.calculate_bundle_score(
            [member(1, 90, role="keep"), member(2, 70)],
            kind="keep_bundle",
        )
        with_block = bs.calculate_bundle_score(
            [
                member(1, 90, role="keep"),
                member(2, 70),
                member(3, 99, verification_concern="block"),
            ],
            kind="keep_bundle",
        )
        self.assertEqual(base["bundle_score"], with_block["bundle_score"])
        self.assertEqual(base["bundle_anchor_item_id"], with_block["bundle_anchor_item_id"])

    def test_near_haul_always_null(self):
        result = bs.calculate_bundle_score(
            [member(1, 90, role="haul"), member(2, 80, role="haul")],
            kind="near_haul",
        )
        self.assertIsNone(result["bundle_score"])
        self.assertIsNone(result["bundle_confidence"])

    def test_index_near_is_scored(self):
        result = bs.calculate_bundle_score(
            [member(1, 71), member(2, 64)],
            kind="index_near_bundle",
        )
        self.assertIsNotNone(result["bundle_score"])
        self.assertGreaterEqual(result["bundle_score"], 60)
        self.assertLessEqual(result["bundle_score"], 100)
        self.assertEqual(result["bundle_anchor_item_id"], 1)

    def test_legacy_members_yield_null(self):
        result = bs.calculate_bundle_score(
            [
                {
                    "id": 1,
                    "role": "keep",
                    "deal_score": 9,
                    "value_band": "steal",
                },
                {"id": 2, "role": "extra", "deal_score": 7},
            ],
            kind="keep_bundle",
        )
        self.assertIsNone(result["bundle_score"])

    def test_extras_term_bounded(self):
        result = bs.calculate_bundle_score(
            [member(1, 95, role="keep", confidence=1.0)]
            + [member(i, 100, confidence=1.0) for i in range(2, 12)],
            kind="keep_bundle",
        )
        self.assertLessEqual(result["bundle_score"] - 95, 12)
        self.assertLessEqual(result["bundle_score"], 100)

    def test_assign_ranks_scores_above_null(self):
        rows = bs.assign_bundle_ranks(
            [
                {
                    "bundle_score": None,
                    "kept_at": "2026-09-07T12:00:00+00:00",
                    "seller_id": 1,
                    "items": [{"id": 1}, {"id": 2}],
                },
                {
                    "bundle_score": 90,
                    "kept_at": "2026-09-06T12:00:00+00:00",
                    "seller_id": 2,
                    "items": [{"id": 3}, {"id": 4}],
                },
                {
                    "bundle_score": 95,
                    "kept_at": "2026-09-05T12:00:00+00:00",
                    "seller_id": 3,
                    "items": [{"id": 5}, {"id": 6}],
                },
            ]
        )
        self.assertIsNone(rows[0]["bundle_rank_position"])
        self.assertEqual(rows[2]["bundle_rank_position"], 1)
        self.assertEqual(rows[1]["bundle_rank_position"], 2)

    def test_golden_fixtures(self):
        path = Path(__file__).parent / "fixtures" / "bundle_score_golden.json"
        cases = json.loads(path.read_text())
        results = {
            case["name"]: bs.calculate_bundle_score(
                case["members"], kind=case["kind"], config={}
            )
            for case in cases
        }
        for case in cases:
            self.assertEqual(
                results[case["name"]]["bundle_score"],
                case["expected_score"],
                case["name"],
            )
            better = case.get("better_than")
            if better:
                self.assertGreater(
                    results[case["name"]]["bundle_score"],
                    results[better]["bundle_score"],
                    f"{case['name']} should beat {better}",
                )


if __name__ == "__main__":
    unittest.main()
