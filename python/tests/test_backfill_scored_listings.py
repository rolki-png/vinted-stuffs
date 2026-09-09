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

    def load_legacy_scored(self, limit=100000):
        rows = [
            dict(row)
            for row in self.rows
            if backfill.ss.is_legacy_scored_row(row)
        ]
        return rows[: max(0, int(limit))]

    def load_legacy_scored(self, limit=100000):
        rows = [
            dict(row)
            for row in self.rows
            if backfill.ss.is_legacy_scored_row(row)
        ]
        return rows[: max(0, int(limit))]

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


class DefaultBackfillQueueTests(unittest.TestCase):
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

    def test_workflow_runs_the_standard_hunt(self):
        self.assertIn("uses: actions/checkout@v7", self.source)
        self.assertIn("uses: actions/setup-python@v7", self.source)
        self.assertIn("python-version: '3.13'", self.source)
        self.assertIn("uses: astral-sh/setup-uv@v10.0.1", self.source)
        self.assertIn("uses: actions/setup-node@v7", self.source)
        self.assertIn("node-version: '24'", self.source)
        self.assertNotIn("pip install", self.source)
        self.assertNotIn("legacy_active_v2", self.source)
        self.assertIn(
            "uv run --project python python python/vinted_bot.py", self.source
        )
        self.assertNotIn(
            "uv run --project python python python/backfill_scored_listings.py",
            self.source,
        )

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

    def test_hunt_state_is_committed_after_the_bot_run(self):
        bot = self.source.index(
            "uv run --project python python python/vinted_bot.py"
        )
        commit = self.source.index("- name: Commit updated state")
        self.assertLess(bot, commit)
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
