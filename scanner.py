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
        """Obtém dados do ETF correspondente ao setor para comparação de força relativa."""
        etf_ticker = self.SECTOR_ETFS.get(sector_name)
        if not etf_ticker:
            return None
            
        if etf_ticker not in self._sector_data_cache:
            try:
                etf = yf.Ticker(etf_ticker)
                # Obter dados de 1 ano para performance anual
                self._sector_data_cache[etf_ticker] = etf.history(period="2y", interval="1d")
            except Exception as e:
                logger.error(f"Erro ao obter dados do ETF {etf_ticker}: {e}")
                return None
        return self._sector_data_cache.get(etf_ticker)

    def analyze(self, ticker: str):
        try:
            tk = yf.Ticker(ticker)
            # Aumentar para 2 anos para garantir que temos 1 ano completo de dados após alinhamento
            daily = tk.history(period="2y", interval="1d")
            h4 = tk.history(period="60d", interval="60m")
            
            if daily is None or len(daily) < 252:
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

            # 4. Capitalização e Setor
            try:
                info = tk.info
                market_cap = info.get("marketCap", 0)
                if market_cap and market_cap < self.config.MIN_MARKET_CAP:
                    return None
                sector = info.get("sector")
            except:
                market_cap = 0
                sector = None

            # --- CÁLCULO DE FORÇA RELATIVA (RS) VS SETOR (1 ANO) ---
            relative_strength = 0
            etf_ticker = "N/A"
            
            if sector:
                sector_daily = self._get_sector_etf_data(sector)
                etf_ticker = self.SECTOR_ETFS.get(sector, "N/A")
                
                if sector_daily is not None and len(sector_daily) >= 252:
                    # Alinhamos os dados para garantir que comparamos as mesmas datas
                    combined = pd.DataFrame({
                        'ticker': daily['Close'],
                        'sector': sector_daily['Close']
                    }).dropna()
                    
                    if len(combined) >= 252:
                        # Performance 1 ano (aprox 252 dias úteis)
                        # RS = (Preço_Atual / Preço_1ano_atrás) / (Setor_Atual / Setor_1ano_atrás)
                        ticker_perf = combined['ticker'].iloc[-1] / combined['ticker'].iloc[-252]
                        sector_perf = combined['sector'].iloc[-1] / combined['sector'].iloc[-252]
                        relative_strength = ticker_perf / sector_perf
            
            # Filtro: RS vs Setor > 1 (Performance do último ano)
            if relative_strength <= 1.0:
                return None

            # Indicadores técnicos
            ema20 = float(daily["Close"].ewm(span=20, adjust=False).mean().iloc[-1])
            ema70 = float(daily["Close"].ewm(span=70, adjust=False).mean().iloc[-1])
            ema200 = float(daily["Close"].ewm(span=200, adjust=False).mean().iloc[-1])

            rsi_daily = float(self._rsi(daily["Close"], 14).iloc[-1])
            
            if h4 is not None and len(h4) > 14:
                rsi_4h = float(self._rsi(h4["Close"], 14).iloc[-1])
            else:
                rsi_4h = rsi_daily

            atr = float(self._atr(daily, 14).iloc[-1])
            atr_pct = (atr / current_price) * 100
            dist_ema20 = ((current_price - ema20) / ema20) * 100

            # --- FILTROS DE ELIMINAÇÃO ---
            if rsi_daily > self.config.MAX_RSI_DAILY:
                return None
            if rsi_4h > self.config.MAX_RSI_4H:
                return None
            if dist_ema20 > self.config.MAX_EMA20_DIST_PCT:
                return None
            if current_price < ema200:
                return None
            if ema20 < ema70 or ema70 < ema200:
                return None
            if atr_pct < self.config.MIN_ATR_PCT:
                return None

            return {
                "ticker": ticker,
                "price": round(current_price, 2),
                "rsi_daily": round(rsi_daily, 2),
                "rsi_4h": round(rsi_4h, 2),
                "ema20": round(ema20, 2),
                "atr_pct": round(atr_pct, 2),
                "rs_sector": round(relative_strength, 2),
                "sector_etf": etf_ticker,
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
