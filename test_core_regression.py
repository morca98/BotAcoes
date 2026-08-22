import os
import unittest
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd

from config import Config
from data_provider import DataProvider
from scanner import Scanner


class ScannerRegressionTests(unittest.TestCase):
    def setUp(self):
        self.scanner = Scanner(Config())

    @staticmethod
    def make_ohlcv(index):
        values = np.arange(len(index), dtype=float) + 100
        return pd.DataFrame(
            {
                "Open": values - 0.2,
                "High": values + 0.5,
                "Low": values - 0.7,
                "Close": values,
                "Volume": np.full(len(index), 1_000.0),
            },
            index=index,
        )

    def test_current_daily_bar_is_excluded(self):
        frame = self.make_ohlcv(pd.bdate_range("2026-08-19", periods=3))
        with patch("scanner.pd.Timestamp.now", return_value=pd.Timestamp("2026-08-21 12:00")):
            closed = self.scanner._closed_daily_bars(frame)
        self.assertEqual(list(closed.index.date), [pd.Timestamp("2026-08-19").date(), pd.Timestamp("2026-08-20").date()])

    def test_current_hourly_bar_is_excluded(self):
        frame = self.make_ohlcv(pd.date_range("2026-08-21 14:00", periods=3, freq="h"))
        with patch("scanner.pd.Timestamp.now", return_value=pd.Timestamp("2026-08-21 16:30")):
            closed = self.scanner._closed_hourly_bars(frame)
        self.assertEqual(len(closed), 2)

    def test_only_complete_four_hour_blocks_are_used(self):
        frame = self.make_ohlcv(pd.date_range("2026-08-21 08:00", periods=5, freq="h"))
        with patch("scanner.pd.Timestamp.now", return_value=pd.Timestamp("2026-08-21 20:00")):
            h4 = self.scanner._aggregate_complete_4h(frame)
        self.assertEqual(len(h4), 1)
        self.assertEqual(h4.iloc[0]["Close"], frame.iloc[3]["Close"])

    def test_financials_use_xlf(self):
        self.assertEqual(self.scanner.SECTOR_ETFS["Financials"], "XLF")

    def test_support_failure_returns_empty_list(self):
        self.assertEqual(self.scanner.get_key_supports("TEST", 100.0, pd.DataFrame()), [])

    def test_earnings_dictionary_format(self):
        class TickerStub:
            calendar = {"Earnings Date": [pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=4)]}

        with patch("scanner.yf.Ticker", return_value=TickerStub()):
            days = self.scanner._get_earnings_days("TEST")
        self.assertIsNotNone(days)
        self.assertGreaterEqual(days, 3)
        self.assertLessEqual(days, 4)


class DataProviderRegressionTests(unittest.TestCase):
    def test_multiple_alpha_keys_are_loaded(self):
        with patch.dict(os.environ, {"ALPHA_VANTAGE_KEYS": "one,two"}, clear=False):
            provider = DataProvider()
        self.assertEqual(provider.av_keys, ["one", "two"])

    def test_alpha_request_uses_full_history(self):
        with patch.dict(os.environ, {"ALPHA_VANTAGE_KEYS": "one"}, clear=False):
            provider = DataProvider()
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"Time Series (Daily)": {}}
        with patch("data_provider.requests.get", return_value=response) as request:
            provider._fetch_alpha_daily("TEST")
        self.assertEqual(request.call_args.kwargs["params"]["outputsize"], "full")


if __name__ == "__main__":
    unittest.main(verbosity=2)
