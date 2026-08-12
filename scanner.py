import logging
import yfinance as yf
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

class Scanner:
    SECTOR_ETFS = {
        "Technology": "XLK",
        "Financial Services": "XLF",
        "Healthcare": "XLV",
        "Consumer Cyclical": "XLY",
        "Energy": "XLE",
        "Industrials": "XLI",
        "Consumer Defensive": "XLP",
        "Utilities": "XLU",
        "Real Estate": "XLRE",
        "Basic Materials": "XLB",
        "Communication Services": "XLC"
    }

    def __init__(self, config):
        self.config = config
        self._sector_data_cache = {}

    def _get_sector_etf_data(self, sector_name: str):
        etf_ticker = self.SECTOR_ETFS.get(sector_name)
        if not etf_ticker:
            return None
        if etf_ticker not in self._sector_data_cache:
            try:
                etf = yf.Ticker(etf_ticker)
                self._sector_data_cache[etf_ticker] = etf.history(period="2y", interval="1d")
            except Exception as e:
                logger.error(f"Erro ao obter dados do ETF {etf_ticker}: {e}")
                return None
        return self._sector_data_cache.get(etf_ticker)

    def _check_divergence(self, prices, indicator):
        """Verifica se existe uma divergência bullish (Preço cai, Indicador sobe)."""
        if len(prices) < 20 or len(indicator) < 20:
            return False
        
        # Simplificação: comparar as duas últimas mínimas locais
        # Encontrar índices de mínimas no preço
        p_min1 = prices.iloc[-10:].min()
        p_min2 = prices.iloc[-20:-10].min()
        
        i_min1 = indicator.iloc[-10:].min()
        i_min2 = indicator.iloc[-20:-10].min()
        
        # Divergência Bullish: Preço fez mínima menor, mas indicador fez mínima maior
        if p_min1 < p_min2 and i_min1 > i_min2:
            return True
        return False

    def _check_vcp(self, df):
        """Verifica contração de volatilidade (VCP)."""
        if len(df) < 20:
            return False
        
        atr_short = self._atr(df, 5).iloc[-1]
        atr_long = self._atr(df, 20).iloc[-1]
        
        # Contração: Volatilidade recente é significativamente menor que a média
        if atr_short < (atr_long * 0.75):
            return True
        return False

    def analyze(self, ticker: str):
        try:
            tk = yf.Ticker(ticker)
            daily = tk.history(period="2y", interval="1d")
            h4 = tk.history(period="60d", interval="60m")
            
            if daily is None or len(daily) < 252:
                return None

            current_price = float(daily["Close"].iloc[-1])
            
            if current_price < self.config.MIN_PRICE:
                return None

            try:
                info = tk.info
                market_cap = info.get("marketCap", 0)
                if market_cap and market_cap < self.config.MIN_MARKET_CAP:
                    return None
                sector = info.get("sector")
            except:
                market_cap = 0
                sector = None

            # RS Setorial (1 ano)
            relative_strength = 0
            etf_ticker = "N/A"
            if sector:
                sector_daily = self._get_sector_etf_data(sector)
                etf_ticker = self.SECTOR_ETFS.get(sector, "N/A")
                if sector_daily is not None and len(sector_daily) >= 252:
                    combined = pd.DataFrame({'ticker': daily['Close'], 'sector': sector_daily['Close']}).dropna()
                    if len(combined) >= 252:
                        ticker_perf = combined['ticker'].iloc[-1] / combined['ticker'].iloc[-252]
                        sector_perf = combined['sector'].iloc[-1] / combined['sector'].iloc[-252]
                        relative_strength = ticker_perf / sector_perf
            
            if relative_strength <= 1.0:
                return None

            # Indicadores técnicos
            ema20 = float(daily["Close"].ewm(span=20, adjust=False).mean().iloc[-1])
            ema70 = float(daily["Close"].ewm(span=70, adjust=False).mean().iloc[-1])
            ema200 = float(daily["Close"].ewm(span=200, adjust=False).mean().iloc[-1])
            rsi_daily = float(self._rsi(daily["Close"], 14).iloc[-1])
            
            if h4 is not None and len(h4) > 14:
                rsi_4h_series = self._rsi(h4["Close"], 14)
                rsi_4h = float(rsi_4h_series.iloc[-1])
                
                # Cálculo MACD 4h
                exp1 = h4["Close"].ewm(span=12, adjust=False).mean()
                exp2 = h4["Close"].ewm(span=26, adjust=False).mean()
                macd_4h = exp1 - exp2
                
                # Deteção de Divergência Bullish (4h)
                has_div_rsi = self._check_divergence(h4["Close"], rsi_4h_series)
                has_div_macd = self._check_divergence(h4["Close"], macd_4h)
                div_bullish = has_div_rsi or has_div_macd
            else:
                rsi_4h = rsi_daily
                div_bullish = False

            # Contração de Volatilidade (VCP) no diário
            is_vcp = self._check_vcp(daily)

            atr = float(self._atr(daily, 14).iloc[-1])
            atr_pct = (atr / current_price) * 100
            dist_ema20 = ((current_price - ema20) / ema20) * 100

            # FILTROS DE EXCLUSÃO
            if rsi_daily > self.config.MAX_RSI_DAILY: return None
            if rsi_4h > self.config.MAX_RSI_4H: return None
            if dist_ema20 > self.config.MAX_EMA20_DIST_PCT: return None
            if current_price < ema200: return None
            if ema20 < ema70 or ema70 < ema200: return None
            if atr_pct < self.config.MIN_ATR_PCT: return None

            return {
                "ticker": ticker,
                "price": round(current_price, 2),
                "rsi_daily": round(rsi_daily, 2),
                "rsi_4h": round(rsi_4h, 2),
                "ema20": round(ema20, 2),
                "atr_pct": round(atr_pct, 2),
                "rs_sector": round(relative_strength, 2),
                "sector_etf": etf_ticker,
                "div_bullish": div_bullish,
                "is_vcp": is_vcp,
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
