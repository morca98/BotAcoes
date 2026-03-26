"""
Scanner — Stock Signal Bot MTF V3
5-filter Multi-Timeframe strategy implementation.
"""

import logging
from typing import Optional, Dict, Any
import yfinance as yf
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class MarketScanner:
    def __init__(self, config):
        self.config = config

    def analyze(self, ticker: str) -> Optional[Dict[str, Any]]:
        try:
            data = self._fetch_data(ticker)
            if data is None:
                return None
            weekly, daily, h4 = data

            # Filter 1 — RSI Weekly < 50
            rsi_w = self._rsi(weekly["Close"], self.config.RSI_PERIOD)
            if rsi_w.iloc[-1] >= self.config.RSI_WEEKLY_MAX:
                return None

            # Filter 2 — Price > SMA70 Daily
            sma_d = daily["Close"].rolling(self.config.SMA_PERIOD).mean()
            current_price = daily["Close"].iloc[-1]
            if current_price <= sma_d.iloc[-1]:
                return None

            # Filter 3 — RSI 4H < 40
            rsi_4h = self._rsi(h4["Close"], self.config.RSI_PERIOD)
            if rsi_4h.iloc[-1] >= self.config.RSI_4H_MAX:
                return None

            # Filter 4 — Bullish MACD Divergence on 4H
            if not self._detect_bullish_divergence(h4):
                return None

            # Filter 5 — 4H HH + HL confirmation
            if not self._confirm_hh_hl(h4):
                return None

            confidence = self._calculate_confidence(rsi_w.iloc[-1], rsi_4h.iloc[-1])
            return {
                "ticker": ticker,
                "signal": True,
                "price": round(float(current_price), 4),
                "rsi_weekly": round(float(rsi_w.iloc[-1]), 2),
                "rsi_4h": round(float(rsi_4h.iloc[-1]), 2),
                "sma70": round(float(sma_d.iloc[-1]), 4),
                "confidence": confidence,
                "h4_low": round(float(h4["Low"].iloc[-5:].min()), 4),
                "h4_high": round(float(h4["High"].iloc[-1]), 4),
            }
        except Exception as e:
            logger.error(f"[{ticker}] Error: {e}")
            return None

    def _fetch_data(self, ticker: str):
        try:
            tk = yf.Ticker(ticker)
            weekly = tk.history(period="2y", interval="1wk")
            daily  = tk.history(period="6mo", interval="1d")
            h4     = tk.history(period="60d", interval="4h")
            for df in [weekly, daily, h4]:
                if df is None or len(df) < 30:
                    return None
            return weekly, daily, h4
        except Exception as e:
            logger.warning(f"[{ticker}] Fetch failed: {e}")
            return None

    @staticmethod
    def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
        avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _macd(series: pd.Series, fast=12, slow=26, signal=9):
        ema_fast = series.ewm(span=fast, adjust=False).mean()
        ema_slow = series.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        return macd_line, signal_line, macd_line - signal_line

    def _detect_bullish_divergence(self, h4: pd.DataFrame, lookback: int = 20) -> bool:
        try:
            lows = h4["Low"].iloc[-lookback:]
            macd_line, _, _ = self._macd(
                h4["Close"],
                self.config.MACD_FAST,
                self.config.MACD_SLOW,
                self.config.MACD_SIGNAL
            )
            macd_w = macd_line.iloc[-lookback:]
            price_mins = self._local_minima(lows.values)
            macd_mins  = self._local_minima(macd_w.values)
            if len(price_mins) < 2 or len(macd_mins) < 2:
                return False
            price_ll = lows.iloc[price_mins[-1]] < lows.iloc[price_mins[-2]]
            macd_hl  = macd_w.iloc[macd_mins[-1]] > macd_w.iloc[macd_mins[-2]]
            return bool(price_ll and macd_hl)
        except Exception:
            return False

    def _confirm_hh_hl(self, h4: pd.DataFrame) -> bool:
        try:
            last, prev = h4.iloc[-1], h4.iloc[-2]
            return bool(last["High"] > prev["High"] and last["Low"] > prev["Low"])
        except Exception:
            return False

    @staticmethod
    def _local_minima(arr: np.ndarray) -> list:
        return [i for i in range(1, len(arr) - 1)
                if arr[i] < arr[i - 1] and arr[i] < arr[i + 1]]

    def _calculate_confidence(self, rsi_weekly: float, rsi_4h: float) -> int:
        score = 60
        score += max(0, (self.config.RSI_WEEKLY_MAX - rsi_weekly) / self.config.RSI_WEEKLY_MAX * 20)
        score += max(0, (self.config.RSI_4H_MAX - rsi_4h) / self.config.RSI_4H_MAX * 20)
        return min(100, round(score))
