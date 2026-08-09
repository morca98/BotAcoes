import logging
import yfinance as yf
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

class Scanner:
    def __init__(self, config):
        self.config = config

    def analyze(self, ticker: str):
        try:
            tk = yf.Ticker(ticker)
            daily = tk.history(period="1y", interval="1d")
            h4 = tk.history(period="60d", interval="60m") # aproximação de 4h via 1h ou diário
            
            if daily is None or len(daily) < 200:
                return None

            current_price = float(daily["Close"].iloc[-1])
            
            # 1. Filtro de Preço > 10 USD
            if current_price < self.config.MIN_PRICE:
                return None

            # 2. Volume médio > 1 milhão
            avg_volume = float(daily["Volume"].iloc[-30:].mean())
            if avg_volume < self.config.MIN_AVG_VOLUME:
                return None

            # 3. Volume em dólares > 20 milhões USD
            dollar_volume = current_price * avg_volume
            if dollar_volume < self.config.MIN_DOLLAR_VOLUME:
                return None

            # 4. Capitalização > 2B USD
            try:
                info = tk.info
                market_cap = info.get("marketCap", 0)
                if market_cap and market_cap < self.config.MIN_MARKET_CAP:
                    return None
            except:
                market_cap = 0

            # Indicadores técnicos
            ema20 = float(daily["Close"].ewm(span=20, adjust=False).mean().iloc[-1])
            ema70 = float(daily["Close"].ewm(span=70, adjust=False).mean().iloc[-1])
            ema200 = float(daily["Close"].ewm(span=200, adjust=False).mean().iloc[-1])

            rsi_daily = float(self._rsi(daily["Close"], 14).iloc[-1])
            
            # RSI 4H (usar h4 se disponível, senão diário)
            if h4 is not None and len(h4) > 14:
                rsi_4h = float(self._rsi(h4["Close"], 14).iloc[-1])
            else:
                rsi_4h = rsi_daily

            # ATR%
            atr = float(self._atr(daily, 14).iloc[-1])
            atr_pct = (atr / current_price) * 100

            # Distância EMA20 (%)
            dist_ema20 = ((current_price - ema20) / ema20) * 100

            # --- FILTROS DE ELIMINAÇÃO ---
            # Eliminar se RSI Diário > 70
            if rsi_daily > self.config.MAX_RSI_DAILY:
                return None

            # Eliminar se RSI 4H > 60
            if rsi_4h > self.config.MAX_RSI_4H:
                return None

            # Eliminar se EMA20 esticada a mais de 8% (Preço > EMA20 * 1.08)
            if dist_ema20 > self.config.MAX_EMA20_DIST_PCT:
                return None

            # Eliminar se Preço < EMA200
            if current_price < ema200:
                return None

            # Eliminar se EMA20 < EMA70 ou EMA70 < EMA200
            if ema20 < ema70 or ema70 < ema200:
                return None

            # Eliminar se ATR% < 2%
            if atr_pct < self.config.MIN_ATR_PCT:
                return None

            return {
                "ticker": ticker,
                "price": round(current_price, 2),
                "rsi_daily": round(rsi_daily, 2),
                "rsi_4h": round(rsi_4h, 2),
                "ema20": round(ema20, 2),
                "atr_pct": round(atr_pct, 2),
                "dollar_volume": round(dollar_volume / 1e6, 2),
                "market_cap": round(market_cap / 1e9, 2) if market_cap else 0
            }

        except Exception as e:
            logger.error(f"Erro ao analisar {ticker}: {e}")
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
