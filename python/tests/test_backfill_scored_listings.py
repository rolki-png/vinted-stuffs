import path_setup  # noqa: F401
import unittest
from pathlib import Path
from unittest.mock import patch

import backfill_scored_listings as backfill


class FakeStore:
    def __init__(self, rows):
        self.rows = [dict(row) for row in rows]
        self.upserted = []

    def load_recent(self, limit):
        return [dict(row) for row in self.rows[:limit]]

    def upsert_many(self, rows):
        self.upserted.extend(rows)
        by_pair = {
            (str(row["item_id"]), str(row["hunt_name"])): row for row in self.rows
        }
        for incoming in rows:
            pair = (str(incoming["item_id"]), str(incoming["hunt_name"]))
            by_pair[pair].update(incoming)


def legacy_row(item_id, *, hunt="Gym", score=7, **overrides):
    return {
        "item_id": item_id,
        "hunt_name": hunt,
        "deal_score": score,
        "score_version": None,
        "has_score": True,
        "reason": "",
        **overrides,
    }


class BackfillV2SelectionTests(unittest.TestCase):
    def test_selects_every_scored_legacy_row_for_active_hunts(self):
        store = FakeStore(
            [
                legacy_row(1, score=9),
                legacy_row(2, score=7),
                legacy_row(3, score=1),
                legacy_row(4, score=10, score_version=2),
                legacy_row(5, hunt="Removed Hunt", score=9),
                legacy_row(6, has_score=False),
                legacy_row(7, reason="unavailable during backfill"),
                legacy_row(2, score=7),
            ]
        )

        pairs = backfill.legacy_active_pairs(store, {"Gym": {"name": "Gym"}})

        self.assertEqual(pairs, [("1", "Gym"), ("2", "Gym"), ("3", "Gym")])

    def test_bounded_batches_rotate_past_cursor_and_known_unavailable(self):
        pairs = [(str(item_id), "Gym") for item_id in range(1, 6)]
        progress = {
            "cursor": ["2", "Gym"],
            "unavailable_pairs": [["4", "Gym"]],
        }

        second_page = backfill.bounded_legacy_batch(pairs, progress, limit=2)
        progress["cursor"] = list(second_page[-1])
        wrapped_page = backfill.bounded_legacy_batch(pairs, progress, limit=2)

        self.assertEqual(second_page, [("3", "Gym"), ("5", "Gym")])
        self.assertEqual(wrapped_page, [("1", "Gym"), ("2", "Gym")])

    def test_completion_excludes_confirmed_unavailable_but_not_retryable_gaps(self):
        progress = {"unavailable_pairs": [["1", "Gym"]]}

        partial = backfill.legacy_completion(
            [("1", "Gym"), ("2", "Gym")], progress
        )
        complete = backfill.legacy_completion([("1", "Gym")], progress)

        self.assertEqual(partial["remaining"], 1)
        self.assertEqual(partial["unavailable"], 1)
        self.assertEqual(partial["status"], "partial")
        self.assertEqual(partial["exit_code"], backfill.PARTIAL_EXIT)
        self.assertEqual(complete["remaining"], 0)
        self.assertEqual(complete["status"], "complete")
        self.assertEqual(complete["exit_code"], 0)

    def test_cli_exposes_explicit_legacy_mode(self):
        args = backfill.build_parser().parse_args(["--legacy-active-v2"])
        self.assertTrue(args.legacy_active_v2)


class BackfillV2RunTests(unittest.TestCase):
    def test_checks_availability_before_scoring_and_preserves_unavailable_history(self):
        store = FakeStore([legacy_row(1, reason="original one"), legacy_row(2, reason="original two")])
        state = {}
        events = []
        item = {
            "id": 1,
            "title": "live",
            "price": {"amount": "50", "currency_code": "RON"},
            "user": {"id": 8, "login": "seller"},
            "_profile": {"country_code": "ro"},
        }

        def fetch(_pairs, _watches):
            events.append("availability")
            return backfill.AvailabilityResult(
                items={"1": item},
                checked_pairs={("1", "Gym"), ("2", "Gym")},
                available_pairs={("1", "Gym")},
            )

        def score(_watch, items, _gateway, _gemini, config):
            events.append("score")
            self.assertEqual([row["id"] for row in items], [1])
            self.assertIs(config, CONFIG)
            return [
                {
                    "id": 1,
                    "score_version": 2,
                    "buy_score": 88,
                    "buy_band": "keep",
                    "score_confidence": 0.8,
                    "score_interval_low": 84,
                    "score_interval_high": 92,
                    "score_factors": {},
                    "factor_evidence": {},
                    "verification_concern": "none",
                    "verification_reason": "",
                    "hunt_fit": True,
                    "reason": "v2 reason",
                }
            ]

        with (
            patch.object(backfill, "fetch_items", side_effect=fetch),
            patch.object(backfill.bot, "attach_seller_profiles"),
            patch.object(backfill.bot, "score_listings", side_effect=score),
            patch.object(backfill.time, "sleep"),
        ):
            summary = backfill.run_legacy_active_v2(
                store=store,
                watch_by_name={"Gym": {"name": "Gym", "country": "ro"}},
                config=CONFIG,
                state=state,
                gateway="gateway-key",
                gemini_client=None,
                limit=10,
            )

        self.assertEqual(events, ["availability", "score"])
        self.assertEqual(
            [(row["item_id"], row["score_version"]) for row in store.upserted],
            [(1, 2)],
        )
        unavailable = next(row for row in store.rows if row["item_id"] == 2)
        self.assertEqual(unavailable["reason"], "original two")
        self.assertIsNone(unavailable["score_version"])
        self.assertEqual(
            state["legacy_active_v2"]["unavailable_pairs"], [["2", "Gym"]]
        )
        self.assertEqual(summary["remaining"], 0)
        self.assertEqual(summary["exit_code"], 0)

    def test_unconfirmed_fetches_remain_retryable_and_advance_cursor(self):
        store = FakeStore([legacy_row(1), legacy_row(2), legacy_row(3)])
        state = {}

        with (
            patch.object(
                backfill,
                "fetch_items",
                return_value=backfill.AvailabilityResult(
                    items={}, checked_pairs=set(), available_pairs=set()
                ),
            ),
            patch.object(backfill.bot, "score_listings") as score,
        ):
            summary = backfill.run_legacy_active_v2(
                store=store,
                watch_by_name={"Gym": {"name": "Gym", "country": "ro"}},
                config=CONFIG,
                state=state,
                gateway="gateway-key",
                gemini_client=None,
                limit=2,
            )

        score.assert_not_called()
        self.assertEqual(summary["selected"], 2)
        self.assertEqual(summary["unknown"], 2)
        self.assertEqual(summary["remaining"], 3)
        self.assertEqual(summary["exit_code"], backfill.PARTIAL_EXIT)
        self.assertEqual(state["legacy_active_v2"]["cursor"], ["2", "Gym"])
        self.assertEqual(state["legacy_active_v2"]["unavailable_pairs"], [])
        self.assertEqual(
            backfill.bounded_legacy_batch(
                backfill.legacy_active_pairs(store, {"Gym": {}}),
                state["legacy_active_v2"],
                limit=2,
            ),
            [("3", "Gym"), ("1", "Gym")],
        )


class WorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (
            Path(__file__).resolve().parents[2]
            / ".github"
            / "workflows"
            / "vinted-bot.yml"
        ).read_text()

    def test_workflow_has_separate_uv_rollout_and_normal_paths(self):
        self.assertIn("legacy_active_v2:", self.source)
        self.assertIn("uses: astral-sh/setup-uv@", self.source)
        self.assertNotIn("pip install", self.source)
        self.assertIn("if: ${{ !inputs.legacy_active_v2 }}", self.source)
        self.assertIn("if: ${{ inputs.legacy_active_v2 }}", self.source)
        self.assertIn(
            "uv run --project python python python/vinted_bot.py", self.source
        )
        self.assertIn(
            "uv run --project python python python/backfill_scored_listings.py",
            self.source,
        )
        self.assertIn("--legacy-active-v2 --limit 10000 --export", self.source)

    def test_workflow_never_interpolates_secrets_inside_shell_source(self):
        in_run_block = False
        run_indent = 0
        shell_lines = []
        for line in self.source.splitlines():
            stripped = line.lstrip()
            indent = len(line) - len(stripped)
            if stripped == "run: |":
                in_run_block = True
                run_indent = indent
                continue
            if in_run_block and stripped and indent <= run_indent:
                in_run_block = False
            if in_run_block:
                shell_lines.append(line)

        self.assertNotIn("${{ secrets.", "\n".join(shell_lines))

    def test_rollout_completion_is_checked_after_state_commit(self):
        rollout = self.source.index(
            "uv run --project python python python/backfill_scored_listings.py"
        )
        commit = self.source.index("- name: Commit updated state")
        completion = self.source.index("- name: Check legacy rollout completion")
        self.assertLess(rollout, commit)
        self.assertLess(commit, completion)
        self.assertIn("LEGACY_ACTIVE_V2_EXIT_CODE", self.source)
        self.assertIn("data/seen_listings.json", self.source)
        self.assertIn("data/indexed_scores.json", self.source)


CONFIG = {
    "buy_scoring": {
        "score_version": 2,
        "keep_min_score": 85,
        "bundle_min_score": 60,
        "min_keep_confidence": 0.6,
    }
}


if __name__ == "__main__":
    unittest.main()
