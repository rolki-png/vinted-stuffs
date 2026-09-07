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


def v2_score(item_id=1):
    return {
        "id": item_id,
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


class FetchItemsTests(unittest.TestCase):
    watches = {"Gym": {"name": "Gym", "country": "ro"}}

    def test_partial_response_omission_is_unknown_and_retryable(self):
        response = {
            "items": [
                {
                    "id": 1,
                    "available": True,
                    "item": {"id": 1, "title": "live"},
                }
            ]
        }

        with (
            patch.object(backfill.bot, "_vinted_json", return_value=response),
            patch.object(backfill.time, "sleep"),
        ):
            result = backfill.fetch_items(
                [("1", "Gym"), ("2", "Gym")], self.watches
            )

        self.assertEqual(result.checked_pairs, {("1", "Gym")})
        self.assertEqual(result.available_pairs, {("1", "Gym")})
        self.assertEqual(result.unavailable_pairs, set())
        self.assertNotIn(("2", "Gym"), result.checked_pairs)

    def test_only_explicit_false_is_confirmed_unavailable(self):
        response = {
            "items": [
                {"id": 1, "available": False},
                {"id": 2, "available": None},
            ]
        }

        with (
            patch.object(backfill.bot, "_vinted_json", return_value=response),
            patch.object(backfill.time, "sleep"),
        ):
            result = backfill.fetch_items(
                [("1", "Gym"), ("2", "Gym")], self.watches
            )

        self.assertEqual(result.checked_pairs, {("1", "Gym")})
        self.assertEqual(result.available_pairs, set())
        self.assertEqual(result.unavailable_pairs, {("1", "Gym")})

    def test_exception_retries_half_without_classifying_omissions(self):
        retry_response = {
            "items": [
                {"id": "1", "available": False},
                {
                    "id": "2",
                    "available": True,
                    "item": {"id": 2, "title": "live"},
                },
            ]
        }

        with (
            patch.object(
                backfill.bot,
                "_vinted_json",
                side_effect=[RuntimeError("batch failed"), retry_response],
            ) as request,
            patch.object(backfill.time, "sleep"),
        ):
            result = backfill.fetch_items(
                [(str(item_id), "Gym") for item_id in range(1, 5)],
                self.watches,
            )

        retry_payload = request.call_args_list[1].kwargs["stdin_payload"]["items"]
        self.assertEqual([row["id"] for row in retry_payload], [1, 2])
        self.assertEqual(result.checked_pairs, {("1", "Gym"), ("2", "Gym")})
        self.assertEqual(result.available_pairs, {("2", "Gym")})
        self.assertEqual(result.unavailable_pairs, {("1", "Gym")})
        self.assertNotIn(("3", "Gym"), result.checked_pairs)
        self.assertNotIn(("4", "Gym"), result.checked_pairs)

    def test_response_ids_are_coerced_to_requested_pair_identity(self):
        response = {
            "items": [
                {
                    "id": 1.0,
                    "available": True,
                    "item": {"id": 1, "title": "live"},
                }
            ]
        }

        with (
            patch.object(backfill.bot, "_vinted_json", return_value=response),
            patch.object(backfill.time, "sleep"),
        ):
            result = backfill.fetch_items([("1", "Gym")], self.watches)

        self.assertEqual(result.checked_pairs, {("1", "Gym")})
        self.assertEqual(set(result.items), {"1"})


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
        self.assertEqual(complete["stuck"], 0)

    def test_completion_excludes_stuck_live_unscored_rows(self):
        progress = {"stuck_pairs": [["2", "Gym"]]}

        complete = backfill.legacy_completion(
            [("1", "Gym"), ("2", "Gym")],
            {"unavailable_pairs": [["1", "Gym"]], **progress},
        )

        self.assertEqual(complete["remaining"], 0)
        self.assertEqual(complete["stuck"], 1)
        self.assertEqual(complete["exit_code"], 0)

    def test_cli_exposes_explicit_legacy_mode(self):
        args = backfill.build_parser().parse_args(["--legacy-active-v2"])
        self.assertTrue(args.legacy_active_v2)

    def test_suppressed_rows_are_excluded_but_parked_rows_remain_selectable(self):
        store = FakeStore([legacy_row(1), legacy_row(2), legacy_row(3)])

        pairs = backfill.legacy_active_pairs(
            store,
            {"Gym": {"name": "Gym"}},
            suppress_ids={1, 2},
        )

        self.assertEqual(pairs, [("3", "Gym")])

    def test_default_pending_batches_rotate_and_retain_retry_counts(self):
        pairs = [(str(item_id), "Gym") for item_id in range(1, 5)]
        progress = {}

        first = backfill.bounded_default_batch(
            pairs, progress, limit=2, offset=0
        )
        backfill.record_default_batch(
            progress,
            selected=first,
            completed=set(),
            retryable=set(first),
        )
        second = backfill.bounded_default_batch(
            pairs, progress, limit=2, offset=0
        )

        self.assertEqual(first, [("1", "Gym"), ("2", "Gym")])
        self.assertEqual(second, [("3", "Gym"), ("4", "Gym")])
        self.assertEqual(
            progress["retry_counts"],
            {"1:Gym": 1, "2:Gym": 1},
        )


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
                unavailable_pairs={("2", "Gym")},
            )

        def score(_watch, items, _gateway, _gemini, config, taste_block=""):
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

    def test_live_unscored_rows_stick_after_three_attempts(self):
        store = FakeStore([legacy_row(1)])
        state = {}
        item = {
            "id": 1,
            "title": "live",
            "price": {"amount": "50", "currency_code": "RON"},
            "user": {"id": 8, "login": "seller"},
            "_profile": {"country_code": "ro"},
        }

        with (
            patch.object(
                backfill,
                "fetch_items",
                return_value=backfill.AvailabilityResult(
                    items={"1": item},
                    checked_pairs={("1", "Gym")},
                    available_pairs={("1", "Gym")},
                ),
            ),
            patch.object(backfill.bot, "attach_seller_profiles"),
            patch.object(backfill.bot, "score_listings", return_value=[]),
            patch.object(backfill.time, "sleep"),
        ):
            for _ in range(3):
                summary = backfill.run_legacy_active_v2(
                    store=store,
                    watch_by_name={"Gym": {"name": "Gym", "country": "ro"}},
                    config=CONFIG,
                    state=state,
                    gateway="gateway-key",
                    gemini_client=None,
                    limit=10,
                )

        self.assertEqual(summary["stuck"], 1)
        self.assertEqual(summary["remaining"], 0)
        self.assertEqual(summary["exit_code"], 0)
        self.assertEqual(state["legacy_active_v2"]["stuck_pairs"], [["1", "Gym"]])

    def test_rollout_passes_taste_block_and_persists_after_availability(self):
        store = FakeStore([legacy_row(1)])
        state = {}
        persisted = []
        item = {
            "id": 1,
            "title": "live",
            "price": {"amount": "50", "currency_code": "RON"},
            "user": {"id": 8, "login": "seller"},
            "_profile": {"country_code": "ro"},
        }

        def fetch(_pairs, _watches):
            return backfill.AvailabilityResult(
                items={"1": item},
                checked_pairs={("1", "Gym")},
                available_pairs={("1", "Gym")},
            )

        def persist(updated):
            persisted.append(
                [list(pair) for pair in updated.get("legacy_active_v2", {}).get("unavailable_pairs", [])]
            )

        def score(_watch, items, _gateway, _gemini, config, taste_block=""):
            self.assertEqual(taste_block, "TASTE")
            return [v2_score(items[0]["id"])]

        with (
            patch.object(backfill, "fetch_items", side_effect=fetch),
            patch.object(backfill.bot, "attach_seller_profiles"),
            patch.object(backfill, "taste_block_for", return_value="TASTE"),
            patch.object(backfill.bot, "score_listings", side_effect=score),
            patch.object(backfill.time, "sleep"),
        ):
            backfill.run_legacy_active_v2(
                store=store,
                watch_by_name={"Gym": {"name": "Gym", "country": "ro"}},
                config=CONFIG,
                state=state,
                gateway="gateway-key",
                gemini_client=None,
                limit=10,
                persist_progress=persist,
            )

        self.assertGreaterEqual(len(persisted), 2)

    def test_abandoned_default_retries_leave_the_pending_queue(self):
        progress = {"retry_counts": {"1:Gym": 2}}
        pairs = [("1", "Gym"), ("2", "Gym")]
        selected = backfill.bounded_default_batch(pairs, progress, limit=2)
        backfill.record_default_batch(
            progress,
            selected=selected,
            completed=set(),
            retryable={("1", "Gym")},
        )
        next_batch = backfill.bounded_default_batch(pairs, progress, limit=2)
        abandoned = backfill._abandoned_default_pairs(progress)

        self.assertEqual(progress["retry_counts"]["1:Gym"], 3)
        self.assertEqual(abandoned, {("1", "Gym")})
        self.assertEqual(next_batch, [("2", "Gym")])


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
        self.assertIn("if: ${{ !fromJSON(inputs.legacy_active_v2 || 'false') }}", self.source)
        self.assertIn("if: ${{ fromJSON(inputs.legacy_active_v2 || 'false') }}", self.source)
        self.assertIn("timeout-minutes: 90", self.source)
        self.assertIn(
            "uv run --project python python python/vinted_bot.py", self.source
        )
        self.assertIn(
            "uv run --project python python python/backfill_scored_listings.py",
            self.source,
        )
        self.assertIn("--legacy-active-v2 --limit 200 --export", self.source)

    def test_workflow_never_interpolates_secrets_inside_shell_source(self):
        import re

        leaked = []
        for match in re.finditer(
            r"^(\s*)run:\s*(\||>.*)?\s*(.*)$", self.source, re.MULTILINE
        ):
            indent = len(match.group(1))
            scalar = match.group(3).strip()
            if match.group(2) and match.group(2).startswith("|"):
                block = []
                for line in self.source[match.end():].splitlines():
                    if line.strip() and (len(line) - len(line.lstrip())) <= indent:
                        break
                    block.append(line)
                text = "\n".join(block)
            else:
                text = scalar
            if "${{ secrets." in text:
                leaked.append(text)
        self.assertEqual(leaked, [])

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
