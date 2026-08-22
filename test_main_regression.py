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


if __name__ == "__main__":
    unittest.main(verbosity=2)
