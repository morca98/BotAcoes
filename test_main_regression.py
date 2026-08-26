import asyncio
import logging
import unittest
from unittest.mock import patch

import pandas as pd

from main import LISBON_TZ, StockBot
from telegram.error import InvalidToken


class FakeTelegramBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, **kwargs):
        self.messages.append(kwargs)
        return object()


class FakeApp:
    def __init__(self):
        self.bot = FakeTelegramBot()

    def add_handler(self, _handler):
        return None

    def run_polling(self, **_kwargs):
        raise InvalidToken("secret-value-must-not-be-logged")


class MainRegressionTests(unittest.TestCase):
    def make_bot(self):
        bot = object.__new__(StockBot)
        bot.chat_id = "1"
        bot.app = FakeApp()
        return bot

    def test_stockbot_initialises_with_environment_configuration(self):
        with patch("main.Config.TELEGRAM_TOKEN", "test"), patch("main.Config.TELEGRAM_CHAT_ID", "1"):
            bot = StockBot()
        self.assertEqual(bot.token, "test")
        self.assertEqual(bot.chat_id, "1")

    def test_long_messages_are_split_without_loss(self):
        bot = self.make_bot()
        text = "".join(f"linha-{number:04d}\n" for number in range(900))
        asyncio.run(bot.send_direct_msg(text))
        sent = bot.app.bot.messages
        self.assertGreater(len(sent), 1)
        self.assertTrue(all(len(message["text"]) <= 3800 for message in sent))
        self.assertEqual("".join(message["text"] for message in sent), text)

    def test_invalid_token_is_redacted_from_log(self):
        bot = self.make_bot()
        with self.assertLogs("main", level=logging.CRITICAL) as logs:
            with self.assertRaises(SystemExit) as exit_error:
                bot.run()
        self.assertEqual(exit_error.exception.code, 1)
        output = "\n".join(logs.output)
        self.assertNotIn("secret-value-must-not-be-logged", output)
        self.assertIn("credencial Telegram foi rejeitada", output)

    def test_weak_support_signal_does_not_reference_uninitialised_time(self):
        bot = self.make_bot()
        bot.active_signals = {"TEST": {"div_bullish": False, "rs_sector": 1.1, "rsi_daily": 40.0}}
        bot.notified_touches = set()
        bot.recent_supports = {}
        bot.last_support_check_time = pd.Timestamp.now(tz=LISBON_TZ).to_pydatetime()
        bot._is_regular_market_open = lambda _ticker: True
        bot.signal_history = []

        class ScannerStub:
            def get_key_supports(self, *_args):
                return [{"virgin": True, "dist": 0.1, "type": "Diária", "price": "100.00", "conf_ema200": False, "conf_ema70": False, "conf_fib": False, "conf_avwap": False}]

            def check_reversal_15m(self, _ticker):
                return True

            def _check_pullback_leadership(self, *_args):
                return False

        bot.scanner = ScannerStub()

        class TickerStub:
            def history(self, **_kwargs):
                index = pd.date_range("2026-08-21 14:00", periods=25, freq="min")
                return pd.DataFrame({"Close": [100.0] * 25, "Volume": [10.0] * 25}, index=index)

        class YFStub:
            @staticmethod
            def Ticker(_ticker):
                return TickerStub()

        async def stop_after_cycle(_seconds):
            raise asyncio.CancelledError()

        with patch.dict("sys.modules", {"yfinance": YFStub()}), patch("main.asyncio.sleep", side_effect=stop_after_cycle):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(bot.support_monitor_loop())
        self.assertEqual(bot.recent_supports, {})


    def test_technical_confluence_can_alert_without_virgin_open(self):
        bot = self.make_bot()
        bot.active_signals = {"TEST": {"div_bullish": False, "rs_sector": 1.1, "rsi_daily": 40.0}}
        bot.notified_touches = set()
        bot.recent_supports = {}
        bot.signal_history = []
        bot.last_support_check_time = pd.Timestamp.now(tz=LISBON_TZ).to_pydatetime()
        bot._is_regular_market_open = lambda _ticker: True
        sent_alerts = []

        class ScannerStub:
            def get_key_supports(self, *_args):
                return [{
                    "virgin": False, "dist": 0.1, "type": "EMA 70", "price": "100.00",
                    "conf_ema200": False, "conf_ema70": True,
                    "conf_fib": False, "conf_avwap": False,
                }]

            def check_reversal_15m(self, _ticker):
                return True

            def _check_pullback_leadership(self, *_args):
                return False

        bot.scanner = ScannerStub()

        class TickerStub:
            def history(self, **kwargs):
                interval = kwargs.get("interval")
                if interval == "60m":
                    index = pd.date_range("2026-08-21 14:00", periods=20, freq="h")
                    return pd.DataFrame({
                        "Close": [100.0] * 20, "High": [101.0] * 20,
                        "Low": [99.0] * 20, "Volume": [10.0] * 20,
                    }, index=index)
                index = pd.date_range("2026-08-21 14:00", periods=25, freq="min")
                return pd.DataFrame({
                    "Close": [100.0] * 25,
                    "Volume": [10.0] * 24 + [20.0],
                }, index=index)

        class YFStub:
            @staticmethod
            def Ticker(_ticker):
                return TickerStub()

        async def capture_alert(text, ticker):
            sent_alerts.append((ticker, text))

        async def stop_after_cycle(_seconds):
            raise asyncio.CancelledError()

        bot.send_alert_with_buttons = capture_alert
        with patch.dict("sys.modules", {"yfinance": YFStub()}), patch("main.asyncio.sleep", side_effect=stop_after_cycle):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(bot.support_monitor_loop())

        self.assertEqual(len(sent_alerts), 1)
        self.assertEqual(sent_alerts[0][0], "TEST")
        self.assertIn("ZONA DE COMPRA", sent_alerts[0][1])
        self.assertEqual(len(bot.signal_history), 1)


    def test_virgin_support_adds_one_point_to_strength(self):
        bot = self.make_bot()
        bot.active_signals = {"TEST": {"div_bullish": False, "rs_sector": 1.1, "rsi_daily": 40.0}}
        bot.notified_touches = set()
        bot.recent_supports = {}
        bot.signal_history = []
        bot.last_support_check_time = pd.Timestamp.now(tz=LISBON_TZ).to_pydatetime()
        bot._is_regular_market_open = lambda _ticker: True
        sent_alerts = []

        class ScannerStub:
            def get_key_supports(self, *_args):
                return [{
                    "virgin": True, "dist": 0.1, "type": "Diária", "price": "100.00",
                    "conf_ema200": False, "conf_ema70": False,
                    "conf_fib": False, "conf_avwap": False,
                }]

            def check_reversal_15m(self, _ticker):
                return True

            def _check_pullback_leadership(self, *_args):
                return False

        bot.scanner = ScannerStub()

        class TickerStub:
            def history(self, **kwargs):
                interval = kwargs.get("interval")
                if interval == "60m":
                    index = pd.date_range("2026-08-21 14:00", periods=20, freq="h")
                    return pd.DataFrame({
                        "Close": [100.0] * 20, "High": [101.0] * 20,
                        "Low": [99.0] * 20, "Volume": [10.0] * 20,
                    }, index=index)
                index = pd.date_range("2026-08-21 14:00", periods=25, freq="min")
                return pd.DataFrame({
                    "Close": [100.0] * 25,
                    "Volume": [10.0] * 24 + [20.0],
                }, index=index)

        class YFStub:
            @staticmethod
            def Ticker(_ticker):
                return TickerStub()

        async def capture_alert(text, ticker):
            sent_alerts.append((ticker, text))

        async def stop_after_cycle(_seconds):
            raise asyncio.CancelledError()

        bot.send_alert_with_buttons = capture_alert
        with patch.dict("sys.modules", {"yfinance": YFStub()}), patch("main.asyncio.sleep", side_effect=stop_after_cycle):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(bot.support_monitor_loop())

        self.assertEqual(len(sent_alerts), 1)
        self.assertIn("(2/6)", sent_alerts[0][1])
        self.assertIn("Abertura Virgem", sent_alerts[0][1])


    def test_combo_breakout_includes_prior_support_confluence_details(self):
        bot = self.make_bot()
        bot.active_signals = {"TEST": {"rs_sector": 1.18, "rsi_daily": 46.2}}
        bot.notified_breakouts = set()
        bot.recent_breakouts = {}
        bot.signal_history = []
        bot._is_regular_market_open = lambda _ticker: True
        bot.recent_supports = {
            "TEST": {
                "time": (pd.Timestamp.now(tz=LISBON_TZ) - pd.Timedelta(hours=6)).to_pydatetime(),
                "type": "Zona (3 níveis)",
                "price": "207.80 - 208.15",
                "confluences": ["EMA 70", "Fib 61.8%", "Abertura Virgem 🆕"],
                "strength_score": 5,
                "strength_bar": "🟢🟢🟢🟢🟢⚪",
                "volume_spike": True,
                "div_bullish": True,
                "pullback_leadership": True,
                "virgin": True,
            }
        }
        sent_alerts = []

        class ScannerStub:
            def _check_breakout_2h(self, _data):
                return True

            def get_breakout_details(self, *_args):
                return {"vol_ratio": 1.6, "is_vcp": True, "dist_pct": 0.45, "target": 223.0}

            def _check_pullback_leadership(self, *_args):
                return True

        bot.scanner = ScannerStub()

        class TickerStub:
            def history(self, **_kwargs):
                index = pd.date_range("2026-08-21 14:00", periods=25, freq="h")
                return pd.DataFrame({
                    "Close": [212.4] * 25, "High": [213.0] * 25,
                    "Low": [211.0] * 25, "Volume": [100.0] * 25,
                }, index=index)

        class YFStub:
            @staticmethod
            def Ticker(_ticker):
                return TickerStub()

        async def capture_alert(text, ticker):
            sent_alerts.append((ticker, text))

        async def stop_after_alert(_seconds):
            raise asyncio.CancelledError()

        bot.send_alert_with_buttons = capture_alert
        with patch.dict("sys.modules", {"yfinance": YFStub()}), patch("main.asyncio.sleep", side_effect=stop_after_alert):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(bot.breakout_monitor_loop())

        self.assertEqual(len(sent_alerts), 1)
        text = sent_alerts[0][1]
        self.assertIn("CONFLUÊNCIA EXTREMA", text)
        self.assertIn("Zona (3 níveis)", text)
        self.assertIn("207.80 - 208.15", text)
        self.assertIn("Força no suporte", text)
        self.assertIn("(5/6)", text)
        self.assertIn("EMA 70 + Fib 61.8% + Abertura Virgem", text)
        self.assertIn("Reversão 15m confirmada + Pico de volume + Divergência bullish + Liderança no pullback", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
