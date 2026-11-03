import datetime as dt
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from neuraldeep_claude import pricing
from neuraldeep_claude.config import atomic_json

XML = b'<ValCurs Date="03.11.2026"><Valute><CharCode>USD</CharCode><Nominal>10</Nominal><Value>809,734</Value></Valute></ValCurs>'


class PricingTests(unittest.TestCase):
    def test_official_quote_normalizes_nominal_and_decimal_separator(self):
        quote = pricing.parse_cbr(XML)
        self.assertEqual(quote["usd_rub_rate"], "80.9734")
        self.assertEqual(quote["effective_date"], "2026-11-03")
        for value in ("NaN", "Infinity", "0", "-2", "bad"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                pricing.positive_rate(value)

    def test_cached_quote_is_not_refetched_and_stale_outage_is_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / ".local/pricing-fx.json"
            now = dt.datetime.now(dt.timezone.utc)
            cached = {"usd_rub_rate": "80.9734", "source": pricing.CBR_URL,
                      "fetched_at": now.isoformat(), "stale": False}
            atomic_json(path, cached)
            with patch.object(pricing, "open_request") as request:
                self.assertFalse(pricing.fx_quote(root)["stale"])
                request.assert_not_called()
            old = cached | {"fetched_at": (now - dt.timedelta(days=2)).isoformat()}
            atomic_json(path, old)
            with patch.object(pricing, "open_request", side_effect=OSError("offline")):
                result = pricing.fx_quote(root)
            self.assertTrue(result["stale"])
            self.assertEqual(result["fetched_at"], old["fetched_at"])
            self.assertEqual(result["refresh_error"], "OSError")

    def test_quote_fetch_is_direct_without_neuraldeep_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(pricing, "open_request", return_value=io.BytesIO(XML)) as request:
                result = pricing.fx_quote(root)
            self.assertEqual(result["usd_rub_rate"], "80.9734")
            request.assert_called_once_with("GET", "/scripts/XML_daily.asp", base="https://www.cbr.ru", timeout=20)
            self.assertTrue((root / ".local/pricing-fx.json").exists())

    def test_user_quote_is_explicit_and_bad_quote_does_not_become_zero(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".env").write_text("NEURALDEEP_USD_RUB_RATE=81.25\n")
            self.assertEqual(pricing.fx_quote(root)["source"], "NEURALDEEP_USD_RUB_RATE")
            (root / ".env").write_text("NEURALDEEP_USD_RUB_RATE=NaN\n")
            with self.assertRaises(ValueError):
                pricing.fx_quote(root)


if __name__ == "__main__":
    unittest.main()
