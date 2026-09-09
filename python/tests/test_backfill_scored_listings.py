import path_setup  # noqa: F401
import unittest
from decimal import Decimal
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


class PendingPairTests(unittest.TestCase):
    watches = {
        "Mamalicious maternity XL-L/XL": {"name": "Mamalicious maternity XL-L/XL"},
    }

    def test_renamed_l_xl_hunt_is_queued_under_current_name(self):
        pending = backfill.select_pending_pairs(
            [("9572667753", "Mamalicious maternity L-XL")],
            self.watches,
            scored_v2_keys=set(),
        )
        self.assertEqual(
            pending,
            [("9572667753", "Mamalicious maternity XL-L/XL")],
        )

    def test_legacy_has_score_does_not_count_as_already_scored(self):
        store = FakeStore(
            [legacy_row(1, hunt="Mamalicious maternity XL-L/XL")]
        )
        self.assertEqual(backfill.already_scored_keys(store), set())

    def test_unavailable_tombstone_still_counts_as_already_scored(self):
        store = FakeStore(
            [
                legacy_row(
                    2,
                    hunt="Mamalicious maternity XL-L/XL",
                    reason=backfill.ss.UNAVAILABLE_TOMBSTONE_REASON,
                )
            ]
        )
        self.assertEqual(
            backfill.already_scored_keys(store),
            {"2:Mamalicious maternity XL-L/XL"},
        )

    def test_v2_row_counts_as_already_scored(self):
        store = FakeStore(
            [
                {
                    "item_id": 1,
                    "hunt_name": "Mamalicious maternity XL-L/XL",
                    "has_score": True,
                    "score_version": 2,
                    "buy_score": 0,
                }
            ]
        )
        self.assertEqual(
            backfill.already_scored_keys(store),
            {"1:Mamalicious maternity XL-L/XL"},
        )

    def test_already_v2_scored_under_new_name_is_not_queued_again(self):
        pending = backfill.select_pending_pairs(
            [("1", "Mamalicious maternity L-XL")],
            self.watches,
            scored_v2_keys={"1:Mamalicious maternity XL-L/XL"},
        )
        self.assertEqual(pending, [])

    def test_hunt_filter_keeps_mamalicious_after_rename(self):
        pending = backfill.select_pending_pairs(
            [
                ("1", "Mamalicious maternity L-XL"),
                ("2", "Seraphine maternity XL-L/XL"),
            ],
            {
                **self.watches,
                "Seraphine maternity XL-L/XL": {
                    "name": "Seraphine maternity XL-L/XL"
                },
            },
            scored_v2_keys=set(),
        )
        self.assertEqual(
            backfill.filter_pending_by_hunt(pending, "Mamalicious"),
            [("1", "Mamalicious maternity XL-L/XL")],
        )

    def test_multi_seller_closet_pairs_are_scored_before_singletons(self):
        pending = [
            ("10", "Mamalicious maternity XL-L/XL"),
            ("20", "Mamalicious maternity XL-L/XL"),
            ("30", "Mamalicious maternity XL-L/XL"),
            ("40", "Mamalicious maternity XL-L/XL"),
        ]
        seller_by_item = {
            "10": "seller-a",
            "20": "seller-a",
            "30": "seller-b",
            # 40 unknown / singleton
        }
        ordered = backfill.prioritize_multi_seller_pairs(pending, seller_by_item)
        self.assertEqual(
            [item_id for item_id, _hunt in ordered[:2]],
            ["10", "20"],
        )
        self.assertEqual(
            {item_id for item_id, _hunt in ordered[2:]},
            {"30", "40"},
        )

    def test_desk_bundle_pairs_remap_l_xl_and_skip_already_v2(self):
        watches = {
            "H&M Mama bundle seed XL-L/XL": {"name": "H&M Mama bundle seed XL-L/XL"},
            "Noppies maternity XL-L/XL": {"name": "Noppies maternity XL-L/XL"},
        }
        bundles = [
            {
                "kind": "value_haul",
                "items": [
                    {"id": 1, "watch": "H&M Mama bundle seed L-XL"},
                    {"id": 2, "watch": "H&M Mama bundle seed XL-L/XL", "buy_score": 70, "score_version": 2},
                ],
            },
            {
                "kind": "near_haul",
                "items": [
                    {"id": 9, "watch": "H&M Mama bundle seed XL-L/XL"},
                ],
            },
            {
                "kind": "keep_bundle",
                "items": [
                    {"id": 3, "watch": "Noppies maternity L-XL"},
                ],
            },
        ]
        pairs = backfill.pairs_from_desk_bundles(
            bundles,
            watches,
            scored_v2_keys={"2:H&M Mama bundle seed XL-L/XL"},
        )
        self.assertEqual(
            pairs,
            [
                ("1", "H&M Mama bundle seed XL-L/XL"),
                ("3", "Noppies maternity XL-L/XL"),
            ],
        )

    def test_cached_payloads_rebuild_items_and_skip_tombstones(self):
        watch = {"name": "Mamalicious maternity XL-L/XL", "country": "ro"}
        items = backfill.items_from_cached_rows(
            [
                ("2", "Mamalicious maternity XL-L/XL"),
                ("3", "Mamalicious maternity XL-L/XL"),
            ],
            {"Mamalicious maternity XL-L/XL": watch},
            [
                legacy_row(
                    3,
                    hunt="Mamalicious maternity L-XL",
                    reason=backfill.ss.UNAVAILABLE_TOMBSTONE_REASON,
                    title="",
                ),
                legacy_row(
                    2,
                    hunt="Mamalicious maternity L-XL",
                    title="Rochie lungă de vară alăptat L",
                    price=Decimal("15.00"),
                    currency="RON",
                    brand="Mamalicious",
                    seller_id=1,
                    seller_login="cosinna29",
                    seller_country="ro",
                ),
            ],
        )
        rebuilt = items["Mamalicious maternity XL-L/XL"]
        self.assertEqual(len(rebuilt), 1)
        self.assertEqual(rebuilt[0]["title"], "Rochie lungă de vară alăptat L")
        self.assertEqual(rebuilt[0]["id"], 2)
        self.assertEqual(rebuilt[0]["price"]["amount"], 15.0)


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
