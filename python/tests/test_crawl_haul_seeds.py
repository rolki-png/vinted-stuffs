import path_setup  # noqa: F401
import unittest

import crawl_haul_seeds as chs


class HaulSeedSelectionTests(unittest.TestCase):
    def test_single_eligible_seller_becomes_a_crawl_seed(self):
        rows = [
            {
                "item_id": 1,
                "hunt_name": "Mamalicious maternity XL-L/XL",
                "seller_id": 10,
                "seller_login": "alpha",
                "seller_country": "pl",
                "score_version": 2,
                "buy_score": 66,
                "hunt_fit": True,
                "verification_concern": "none",
            },
            {
                "item_id": 2,
                "hunt_name": "Mamalicious maternity XL-L/XL",
                "seller_id": 20,
                "seller_login": "beta",
                "seller_country": "ro",
                "score_version": 2,
                "buy_score": 70,
                "hunt_fit": True,
                "verification_concern": "none",
            },
            {
                "item_id": 3,
                "hunt_name": "Mamalicious maternity XL-L/XL",
                "seller_id": 20,
                "seller_login": "beta",
                "seller_country": "ro",
                "score_version": 2,
                "buy_score": 62,
                "hunt_fit": True,
                "verification_concern": "none",
            },
            {
                "item_id": 4,
                "hunt_name": "Gym shorts",
                "seller_id": 30,
                "seller_login": "gym",
                "seller_country": "ro",
                "score_version": 2,
                "buy_score": 80,
                "hunt_fit": True,
                "verification_concern": "none",
            },
        ]
        seeds = chs.select_haul_seeds(rows, hunt_needle="Mamalicious")
        self.assertEqual(
            [(s["seller_id"], s["seller"], s["country"]) for s in seeds],
            [(10, "alpha", "pl")],
        )

    def test_seed_watch_is_preferred_when_ordering_matches(self):
        matches = [
            {"name": "Mamalicious leggings XL-L/XL"},
            {"name": "Mamalicious maternity XL-L/XL"},
        ]
        ordered = chs.order_watches_for_seed(
            matches, seed_watch="Mamalicious maternity XL-L/XL"
        )
        self.assertEqual(
            [w["name"] for w in ordered],
            [
                "Mamalicious maternity XL-L/XL",
                "Mamalicious leggings XL-L/XL",
            ],
        )


if __name__ == "__main__":
    unittest.main()
