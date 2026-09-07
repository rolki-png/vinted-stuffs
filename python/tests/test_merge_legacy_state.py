import path_setup  # noqa: F401
import unittest

from merge_legacy_state import merge_legacy_progress, merge_pair_lists


class MergeLegacyStateTests(unittest.TestCase):
    def test_union_unavailable_and_keeps_incoming_last_run(self):
        main = {
            "run_count": 10,
            "legacy_active_v2": {
                "cursor": ["1", "old"],
                "unavailable_pairs": [["1", "A"]],
                "stuck_pairs": [],
                "live_unscored_counts": {"9:A": 1},
                "last_run": {"remaining": 20, "status": "partial"},
            },
        }
        incoming = {
            "run_count": 9,
            "legacy_active_v2": {
                "cursor": ["2", "new"],
                "unavailable_pairs": [["1", "A"], ["3", "B"]],
                "stuck_pairs": [["4", "C"]],
                "live_unscored_counts": {"9:A": 2, "8:B": 1},
                "last_run": {"remaining": 15, "status": "partial"},
            },
        }
        merged = merge_legacy_progress(main, incoming)
        self.assertEqual(merged["run_count"], 10)
        progress = merged["legacy_active_v2"]
        self.assertEqual(progress["cursor"], ["2", "new"])
        self.assertEqual(progress["last_run"]["remaining"], 15)
        self.assertEqual(
            merge_pair_lists(progress["unavailable_pairs"]),
            [["1", "A"], ["3", "B"]],
        )
        self.assertEqual(progress["stuck_pairs"], [["4", "C"]])
        self.assertEqual(progress["live_unscored_counts"]["9:A"], 2)
        self.assertEqual(progress["live_unscored_counts"]["8:B"], 1)


if __name__ == "__main__":
    unittest.main()
