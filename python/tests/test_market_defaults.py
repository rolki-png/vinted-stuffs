import os
import unittest

import path_setup  # noqa: F401
import market_defaults as md


class TestMarketDefaults(unittest.TestCase):
    def setUp(self):
        self._saved = {
            key: os.environ.get(key)
            for key in ("VINTED_COUNTRY", "VINTED_FORCE_COUNTRY", "VINTED_CURRENCY", "VINTED_SITE_HOST")
        }
        for key in self._saved:
            os.environ.pop(key, None)

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_uk_defaults(self):
        self.assertEqual(md.default_country(), "uk")
        self.assertEqual(md.default_currency(), "GBP")
        self.assertEqual(md.site_host(), "www.vinted.co.uk")
        self.assertEqual(md.member_url(12), "https://www.vinted.co.uk/member/12")
        self.assertEqual(md.watch_country({"country": "pl"}), "pl")
        self.assertEqual(md.watch_country({}), "uk")

    def test_force_country_overrides_watch(self):
        os.environ["VINTED_FORCE_COUNTRY"] = "FR"
        os.environ["VINTED_CURRENCY"] = "eur"
        os.environ["VINTED_SITE_HOST"] = "https://www.vinted.fr/catalog"
        self.assertEqual(md.watch_country({"country": "uk"}), "fr")
        self.assertEqual(md.default_currency(), "EUR")
        self.assertEqual(md.site_host(), "www.vinted.fr")
