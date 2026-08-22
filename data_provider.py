import json
import logging
import os
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

logger = logging.getLogger("data_provider")


class DataProvider:
    """Camada única de OHLCV normalizado com Alpha Vantage opcional e fallback Yahoo."""

    REQUIRED_COLUMNS = ("Open", "High", "Low", "Close", "Volume")

    def __init__(self):
        raw_keys = (
            os.getenv("ALPHA_VANTAGE_KEYS")
            or os.getenv("ALPHA_VANTAGE_KEY")
            or os.getenv("ALPHA_VANTAGE_API_KEY")
            or ""
        )
        self.av_keys = [key.strip() for key in raw_keys.split(",") if key.strip()]
        self.key_index = 0
        mapping_file = Path(__file__).resolve().parent / "ticker_mapping_av.json"
        try:
            self.av_mapping = json.loads(mapping_file.read_text(encoding="utf-8")) if mapping_file.exists() else {}
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Não foi possível carregar o mapeamento Alpha Vantage: %s", exc)
            self.av_mapping = {}

    def _current_key(self):
        return self.av_keys[self.key_index] if self.av_keys else None

    def _rotate_key(self):
        if len(self.av_keys) > 1:
            self.key_index = (self.key_index + 1) % len(self.av_keys)

    @classmethod
    def _normalise(cls, frame: pd.DataFrame) -> pd.DataFrame:
        if frame is None or frame.empty:
            return pd.DataFrame()
        result = frame.copy()
        if isinstance(result.columns, pd.MultiIndex):
            result.columns = result.columns.get_level_values(0)
        if any(column not in result.columns for column in cls.REQUIRED_COLUMNS):
            return pd.DataFrame()
        result = result.loc[:, list(cls.REQUIRED_COLUMNS)].apply(pd.to_numeric, errors="coerce")
        result.index = pd.to_datetime(result.index)
        if getattr(result.index, "tz", None) is not None:
            result.index = result.index.tz_localize(None)
        return result.dropna(subset=["Open", "High", "Low", "Close"]).sort_index()

    def _fetch_alpha_daily(self, ticker: str) -> pd.DataFrame:
        if not self.av_keys:
            return pd.DataFrame()
        symbol = self.av_mapping.get(ticker, ticker)
        for _ in range(len(self.av_keys)):
            try:
                response = requests.get(
                    "https://www.alphavantage.co/query",
                    params={
                        "function": "TIME_SERIES_DAILY",
                        "symbol": symbol,
                        "outputsize": "full",
                        "apikey": self._current_key(),
                    },
                    timeout=15,
                )
                response.raise_for_status()
                series = response.json().get("Time Series (Daily)")
                if series:
                    frame = pd.DataFrame.from_dict(series, orient="index").rename(columns={
                        "1. open": "Open", "2. high": "High", "3. low": "Low",
                        "4. close": "Close", "5. volume": "Volume",
                    })
                    frame = self._normalise(frame)
                    if len(frame) >= 252:
                        return frame
                    logger.warning("Histórico Alpha Vantage insuficiente para %s.", ticker)
                else:
                    logger.warning("Alpha Vantage não devolveu série diária para %s.", ticker)
            except (requests.RequestException, ValueError) as exc:
                logger.warning("Falha Alpha Vantage para %s: %s", ticker, exc)
            self._rotate_key()
        return pd.DataFrame()

    def _fetch_yahoo(self, ticker: str, period: str, interval: str) -> pd.DataFrame:
        try:
            frame = yf.download(
                ticker,
                period=period,
                interval=interval,
                progress=False,
                auto_adjust=False,
                threads=False,
                timeout=20,
            )
            normalised = self._normalise(frame)
            if not normalised.empty:
                return normalised
        except Exception as exc:
            logger.warning("Falha no download Yahoo para %s: %s", ticker, exc)

        try:
            return self._normalise(
                yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=False)
            )
        except Exception as exc:
            logger.warning("Falha no histórico Yahoo para %s: %s", ticker, exc)
            return pd.DataFrame()

    def fetch_daily(self, ticker: str) -> pd.DataFrame:
        frame = self._fetch_alpha_daily(ticker)
        return frame if not frame.empty else self._fetch_yahoo(ticker, "2y", "1d")

    def fetch_intraday(self, ticker: str, interval: str = "60m") -> pd.DataFrame:
        periods = {
            "1m": "7d", "2m": "60d", "5m": "60d", "15m": "60d",
            "30m": "60d", "60m": "60d", "90m": "60d",
        }
        return self._fetch_yahoo(ticker, periods.get(interval, "60d"), interval)
