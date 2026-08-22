import ast
import unittest
from pathlib import Path

from config import Config
from scanner import Scanner


PROJECT_DIR = Path(__file__).resolve().parent


class LogRemediationTests(unittest.TestCase):
    def setUp(self):
        self.scanner = Scanner(Config())

    def test_all_space_separated_european_symbols_are_normalised(self):
        original_symbols = [
            "ASSA B.ST", "BALD B.ST", "HUSQ B.ST", "MAERSK B.CO", "NIBE B.ST", "NDA FI.HE",
            "NOV N.SW", "NOVO B.CO", "SECU B.ST", "SKA B.ST", "SWED A.ST", "SHB B.ST",
            "VOLV B.ST", "SWECO B.ST", "TREL B.ST", "VPLAY B.ST",
        ]
        normalised = [self.scanner._normalise_ticker(symbol) for symbol in original_symbols]
        self.assertTrue(all(symbol and " " not in symbol for symbol in normalised))
        self.assertEqual(self.scanner._normalise_ticker("NDA FI.HE"), "NDA-FI.HE")
        self.assertEqual(self.scanner._normalise_ticker("ASSA B.ST"), "ASSA-B.ST")
        self.assertIsNone(self.scanner._normalise_ticker("INVALID SYMBOL!"))

    def test_confirmed_stale_stoxx_symbols_are_excluded_before_download(self):
        self.assertIn("GWI.MI", self.scanner.STOXX_EXCLUDED_TICKERS)
        self.assertIn("PERP.PA", self.scanner.STOXX_EXCLUDED_TICKERS)
        self.assertNotIn("GWI.MI", set(["GWI.MI"]) - self.scanner.STOXX_EXCLUDED_TICKERS)

    def test_failed_symbol_is_skipped_only_after_three_failures(self):
        ticker = "INVALID.DE"
        for _ in range(2):
            self.scanner._data_failures[ticker] = self.scanner._data_failures.get(ticker, 0) + 1
        self.assertNotIn(ticker, self.scanner._unavailable_tickers)
        self.scanner._data_failures[ticker] += 1
        if self.scanner._data_failures[ticker] >= 3:
            self.scanner._unavailable_tickers.add(ticker)
        self.assertIn(ticker, self.scanner._unavailable_tickers)

    def test_market_breadth_uses_valid_yahoo_period_and_batch(self):
        source = (PROJECT_DIR / "main.py").read_text(encoding="utf-8")
        self.assertIn('period="3mo", interval="1d", group_by="ticker"', source)
        self.assertNotIn('period="3m"', source)
        self.assertIn('threads=False, progress=False, auto_adjust=False', source)

    def test_breadth_without_coverage_is_unavailable_not_artificially_neutral(self):
        source = (PROJECT_DIR / "main.py").read_text(encoding="utf-8")
        self.assertIn("if total_checked >= 15:", source)
        self.assertIn("breadth_pct = None", source)
        self.assertIn("breadth_pct is not None and breadth_pct < 45", source)

    def test_scan_has_conservative_concurrency_cooldown_and_cap(self):
        main_source = (PROJECT_DIR / "main.py").read_text(encoding="utf-8")
        scanner_source = (PROJECT_DIR / "scanner.py").read_text(encoding="utf-8")
        config_source = (PROJECT_DIR / "config.py").read_text(encoding="utf-8")
        self.assertIn("asyncio.Semaphore(2)", main_source)
        self.assertIn("rate_limit_until", main_source)
        self.assertIn("Pausa global de 60s", main_source)
        self.assertIn("self.config.MAX_SCAN_ASSETS", main_source)
        self.assertIn("MAX_SCAN_ASSETS = 500", config_source)
        self.assertIn("threads=False", scanner_source)
        self.assertNotIn("threads=True", scanner_source)

    def test_main_module_is_syntax_valid(self):
        ast.parse((PROJECT_DIR / "main.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
