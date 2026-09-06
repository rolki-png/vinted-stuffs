import path_setup  # noqa: F401
import unittest
from unittest.mock import patch

import vinted_bot as bot


class ClosetCrawlTests(unittest.TestCase):
    def test_closet_chunks_split_sellers(self):
        chunks = bot._closet_chunks(list(range(1, 13)), chunk_size=5)
        self.assertEqual(chunks, [[1, 2, 3, 4, 5], [6, 7, 8, 9, 10], [11, 12]])

    def test_get_seller_closets_issues_chunked_batch_calls(self):
        calls = []

        def fake_vinted(args, timeout=60, stdin_payload=None):
            calls.append((list(args), stdin_payload, timeout))
            ids = stdin_payload["closets"]["ids"]
            return {
                "closets": [
                    {"sellerId": sid, "items": [{"id": sid * 10, "title": "x"}], "error": None}
                    for sid in ids
                ]
            }

        with patch.object(bot, "_vinted_json", side_effect=fake_vinted):
            out = bot.get_seller_closets(list(range(1, 12)), "ro", 12)

        self.assertEqual(len(calls), 3)
        self.assertEqual(len(calls[0][1]["closets"]["ids"]), 5)
        self.assertEqual(len(calls[1][1]["closets"]["ids"]), 5)
        self.assertEqual(len(calls[2][1]["closets"]["ids"]), 1)
        self.assertIn("1", out)
        self.assertEqual(out["11"][0]["id"], 110)

    def test_select_closet_crawl_prefers_keeps_and_caps(self):
        candidates = [
            {"sid": 1, "is_keep": False, "score": {"deal_score": 9}},
            {"sid": 2, "is_keep": True, "score": {"deal_score": 9}},
            {"sid": 3, "is_keep": False, "score": {"deal_score": 8}},
            {"sid": 2, "is_keep": True, "score": {"deal_score": 10}},
        ]
        picked = bot.select_closet_crawl_sellers(
            candidates, {"closet_crawl_max_sellers": 2},
        )
        self.assertEqual([p["sid"] for p in picked], [2, 1])


if __name__ == "__main__":
    unittest.main()
