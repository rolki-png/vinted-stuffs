import path_setup  # noqa: F401
"""Regression: one CLI process per listing batch, not per seller.

The live failure was Vinted bootstrap 429 after ~11 new `node dist/cli.js seller`
processes per hunt. attach_seller_profiles must issue a single seller argv.
Also backfill usernames from profile payloads so dashboard/bundles can match sellers.
"""
import unittest
from unittest.mock import patch

import vinted_bot as bot


class ProfileBatchTests(unittest.TestCase):
    def setUp(self):
        bot._profile_consecutive_failures = 0
        bot._profile_endpoint_disabled = False
        bot._profile_debug_printed = True

    def test_attach_issues_one_comma_separated_seller_call(self):
        items = [
            {"id": i, "user": {"id": 1000 + i}}
            for i in range(10)
        ]
        calls = []

        def fake_vinted(args, timeout=60, stdin_payload=None):
            calls.append((list(args), stdin_payload))
            return {
                "sellers": [
                    {
                        "id": 1000 + i,
                        "username": f"user{i}",
                        "feedbackCount": 1,
                        "feedbackReputation": 1,
                        "itemCount": 2,
                        "countryCode": "RO",
                    }
                    for i in range(10)
                ]
            }

        with patch.object(bot, "_vinted_json", side_effect=fake_vinted):
            bot.attach_seller_profiles(items, "ro")

        self.assertEqual(len(calls), 1, calls)
        self.assertEqual(calls[0][0], ["batch"])
        self.assertEqual(len(calls[0][1]["sellers"]["ids"]), 10)
        self.assertEqual(items[0]["_profile"]["feedback_count"], 1)
        self.assertEqual(items[9]["_profile"]["country_code"], "ro")
        self.assertEqual(items[0]["user"]["login"], "user0")
        self.assertEqual(bot.seller_login(items[3]), "user3")

    def test_normalize_reads_seller_username(self):
        item = bot._normalize_item({
            "id": 1,
            "title": "tee",
            "price": {"amount": "10", "currency_code": "RON"},
            "seller": {"id": 42, "username": "alice"},
        })
        self.assertEqual(item["user"]["id"], 42)
        self.assertEqual(item["user"]["login"], "alice")

    def test_closet_stamps_owner_id_when_item_omits_seller(self):
        def fake_vinted(args, timeout=60, stdin_payload=None):
            return {
                "closets": [
                    {
                        "sellerId": 99,
                        "items": [
                            {
                                "id": 7,
                                "title": "shorts",
                                "price": {"amount": "20", "currency_code": "RON"},
                            }
                        ],
                        "error": None,
                    }
                ]
            }

        with patch.object(bot, "_vinted_json", side_effect=fake_vinted):
            closets = bot.get_seller_closets([99], "ro", 12)
        self.assertEqual(closets["99"][0]["user"]["id"], 99)

    def test_ensure_seller_fields_fetches_item_detail(self):
        item = {"id": 42, "title": "tee", "user": {}}

        def fake_vinted(args, **kwargs):
            self.assertEqual(args[0], "item")
            return {
                "id": 42,
                "title": "tee",
                "price": "10",
                "currency": "RON",
                "seller": {"id": 7, "username": "alice"},
            }

        with patch.object(bot, "_vinted_json", side_effect=fake_vinted):
            bot.ensure_seller_fields(item, "ro")
        self.assertEqual(item["user"]["id"], 7)
        self.assertEqual(item["user"]["login"], "alice")
        self.assertEqual(bot.seller_login(item), "alice")


if __name__ == "__main__":
    unittest.main()
