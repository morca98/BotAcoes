"""
Scanner de Ações - Pontos de Compra e Filtros Técnicos
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
            daily, h4 = data

            # 1. Volume médio > 1 milhão de ações/dia (últimos 30 dias)
            avg_volume = daily["Volume"].iloc[-30:].mean()
            if avg_volume < self.config.MIN_AVG_VOLUME:
                return None

            # 2. Preço > 10 USD
            current_price = daily["Close"].iloc[-1]
            if current_price < self.config.MIN_PRICE:
                return None

            # 3. Volume em dólares > 20 milhões USD (Preço * Volume diário médio)
            dollar_volume = current_price * avg_volume
            if dollar_volume < self.config.MIN_DOLLAR_VOLUME:
                return None

            # 4. Capitalização > 2 B USD
            market_cap = self._get_market_cap(ticker)
            if market_cap is not None and market_cap < self.config.MIN_MARKET_CAP:
                return None

            # --- Cálculos de Indicadores Técnicos ---
            # Médias Móveis Exponenciais (EMA)
            ema20 = daily["Close"].ewm(span=20, adjust=False).mean().iloc[-1]
            ema70 = daily["Close"].ewm(span=70, adjust=False).mean().iloc[-1]
            ema200 = daily["Close"].ewm(span=200, adjust=False).mean().iloc[-1]

            # RSI Diário e 4H
            rsi_daily = self._rsi(daily["Close"], 14).iloc[-1]
            rsi_4h = self._rsi(h4["Close"], 14).iloc[-1]

            # ATR% (Average True Range em percentagem do preço)
            atr = self._atr(daily, 14).iloc[-1]
            atr_pct = (atr / current_price) * 100

            # --- Aplicação dos Filtros de Eliminação ---
            # - Eliminar se RSI Diário > 70
            if rsi_daily > self.config.RSI_DAILY_MAX:
                return None

            # - Eliminar se RSI 4h > 60
            if rsi_4h > self.config.RSI_4H_MAX:
                return None

            # - Eliminar se EMA20 esticada a mais de 8% (Preço > EMA20 * 1.08)
            # Ou seja, manter se a distância estiver entre a EMA20 e 8% acima. Se preço < EMA20 também pode ser ponto de compra (pullback),
            # mas o utilizador especificou: "Eliminar se EMA20 < 8%" (significando afastar se estiver a mais de 8% acima da EMA20, ou seja, esticado).
            # Vamos verificar a distância percentual: (current_price - ema20) / ema20 * 100
            distance_ema20 = ((current_price - ema20) / ema20) * 100
            if distance_ema20 > self.config.EMA20_MAX_DISTANCE_PCT:
                return None

            # - Eliminar se Preço < EMA200
            if current_price < ema200:
                return None

            # - Eliminar se EMA20 < EMA70
            if ema20 < ema70:
                return None

            # - Eliminar se EMA70 < EMA200
            if ema70 < ema200:
                return None

            # - Eliminar se ATR% < 2%
            if atr_pct < self.config.ATR_MIN_PCT:
                return None

            return {
                "ticker": ticker,
                "price": round(float(current_price), 2),
                "rsi_daily": round(float(rsi_daily), 2),
                "rsi_4h": round(float(rsi_4h), 2),
                "ema20": round(float(ema20), 2),
                "ema70": round(float(ema70), 2),
                "ema200": round(float(ema200), 2),
                "atr_pct": round(float(atr_pct), 2),
                "dollar_volume": round(float(dollar_volume / 1e6), 2), # em milhões
                "market_cap": round(float(market_cap / 1e9), 2) if market_cap else 0, # em bilhões
            }

        except Exception as e:
            logger.error(f"[{ticker}] Erro no scanner: {e}")
            return None

    def _fetch_data(self, ticker: str):
        try:
            tk = yf.Ticker(ticker)
            daily = tk.history(period="1y", interval="1d")
            h4 = tk.history(period="60d", interval="60m") # yfinance 4h pode usar 60m agrupado ou 1h
            if daily is None or len(daily) < 200 or h4 is None or len(h4) < 30:
                return None
            return daily, h4
        except Exception as e:
            logger.warning(f"[{ticker}] Falha ao descarregar dados: {e}")
            return None

    def _get_market_cap(self, ticker: str) -> Optional[float]:
        try:
            tk = yf.Ticker(ticker)
            info = tk.info
            return info.get("marketCap", None)
        except Exception:
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
    def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        high = df["High"]
        low = df["Low"]
        close = df["Close"]
        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(period).mean()
