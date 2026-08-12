import logging
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import io

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

    THEMATIC_ETFS = ["SMH", "XBI", "IBIT", "IWM", "QQQ", "SPY"]

    def __init__(self, config):
        self.config = config
        self._sector_data_cache = {}
        self._universe_cache = None

    def get_dynamic_universe(self):
        """Obtém componentes do S&P 500, Nasdaq 100 e ETFs temáticos com User-Agent para evitar 403."""
        tickers = set(self.THEMATIC_ETFS)
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        
        try:
            # S&P 500
            url_sp500 = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
            response = requests.get(url_sp500, headers=headers, timeout=10)
            sp500 = pd.read_html(io.StringIO(response.text))[0]
            tickers.update(sp500['Symbol'].tolist())
            logger.info(f"S&P 500 obtido: {len(sp500)} ativos")
            
            # Nasdaq 100
            url_nasdaq = 'https://en.wikipedia.org/wiki/Nasdaq-100'
            response = requests.get(url_nasdaq, headers=headers, timeout=10)
            tables = pd.read_html(io.StringIO(response.text))
            for df in tables:
                if 'Ticker' in df.columns:
                    tickers.update(df['Ticker'].tolist())
                    break
                elif 'Symbol' in df.columns:
                    tickers.update(df['Symbol'].tolist())
                    break
            logger.info("Nasdaq 100 obtido")
        except Exception as e:
            logger.error(f"Erro ao obter índices da Wikipedia: {e}")
            tickers.update(self.config.ASSETS)

        clean_tickers = [str(t).replace('.', '-') for t in tickers if isinstance(t, (str, float)) and str(t) != 'nan']
        return list(set(clean_tickers))

    def filter_by_liquidity(self, tickers, limit=500):
        """Filtra os top ativos por volume financeiro (Dollar Volume)."""
        logger.info(f"A filtrar liquidez para {len(tickers)} ativos...")
        if len(tickers) <= limit:
            return tickers

        data = []
        chunk_size = 100
        for i in range(0, len(tickers), chunk_size):
            chunk = tickers[i:i + chunk_size]
            try:
                tickers_str = " ".join(chunk)
                # Obter dados rápidos de 1 dia
                batch = yf.download(tickers_str, period="1d", group_by='ticker', threads=True, progress=False)
                
                for t in chunk:
                    try:
                        ticker_data = batch[t] if len(chunk) > 1 else batch
                        if not ticker_data.empty:
                            last_close = ticker_data['Close'].iloc[-1]
                            last_vol = ticker_data['Volume'].iloc[-1]
                            dollar_vol = last_close * last_vol
                            if not np.isnan(dollar_vol) and dollar_vol > 0:
                                data.append({'ticker': t, 'dollar_vol': dollar_vol})
                    except:
                        continue
            except Exception as e:
                logger.error(f"Erro no lote de liquidez: {e}")
                continue

        df = pd.DataFrame(data)
        if df.empty:
            logger.warning("Filtro de liquidez vazio, a usar fallback.")
            return tickers[:limit]
            
        top_tickers = df.sort_values(by='dollar_vol', ascending=False).head(limit)['ticker'].tolist()
        logger.info(f"Liquidez filtrada: {len(top_tickers)} ativos selecionados.")
        return top_tickers

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
        if len(prices) < 20 or len(indicator) < 20:
            return False
        p_min1 = prices.iloc[-10:].min()
        p_min2 = prices.iloc[-20:-10].min()
        i_min1 = indicator.iloc[-10:].min()
        i_min2 = indicator.iloc[-20:-10].min()
        if p_min1 < p_min2 and i_min1 > i_min2:
            return True
        return False

    def _check_vcp(self, df):
        if len(df) < 20:
            return False
        atr_short = self._atr(df, 5).iloc[-1]
        atr_long = self._atr(df, 20).iloc[-1]
        if atr_short < (atr_long * 0.75):
            return True
        return False

    def _check_breakout_2h(self, h1_df):
        if len(h1_df) < 20:
            return False
        h2_df = h1_df.resample('2h').agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        }).dropna()
        if len(h2_df) < 10:
            return False
        current_close = h2_df['Close'].iloc[-1]
        previous_highs_max = h2_df['High'].iloc[-11:-1].max()
        if current_close > previous_highs_max:
            return True
        return False

    def analyze(self, ticker: str):
        try:
            tk = yf.Ticker(ticker)
            daily = tk.history(period="2y", interval="1d")
            h1 = tk.history(period="60d", interval="60m")
            
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

            ema20 = float(daily["Close"].ewm(span=20, adjust=False).mean().iloc[-1])
            ema70 = float(daily["Close"].ewm(span=70, adjust=False).mean().iloc[-1])
            ema200 = float(daily["Close"].ewm(span=200, adjust=False).mean().iloc[-1])
            rsi_daily = float(self._rsi(daily["Close"], 14).iloc[-1])
            
            if h1 is not None and len(h1) > 14:
                rsi_h1_series = self._rsi(h1["Close"], 14)
                rsi_h1 = float(rsi_h1_series.iloc[-1])
                exp1 = h1["Close"].ewm(span=12, adjust=False).mean()
                exp2 = h1["Close"].ewm(span=26, adjust=False).mean()
                macd_h1 = exp1 - exp2
                has_div_rsi = self._check_divergence(h1["Close"], rsi_h1_series)
                has_div_macd = self._check_divergence(h1["Close"], macd_h1)
                div_bullish = has_div_rsi or has_div_macd
                breakout_2h = self._check_breakout_2h(h1)
            else:
                rsi_h1 = rsi_daily
                div_bullish = False
                breakout_2h = False

            is_vcp = self._check_vcp(daily)
            atr = float(self._atr(daily, 14).iloc[-1])
            atr_pct = (atr / current_price) * 100
            dist_ema20 = ((current_price - ema20) / ema20) * 100

            if rsi_daily > self.config.MAX_RSI_DAILY: return None
            if rsi_h1 > self.config.MAX_RSI_4H: return None
            if dist_ema20 > self.config.MAX_EMA20_DIST_PCT: return None
            if current_price < ema200: return None
            if ema20 < ema70 or ema70 < ema200: return None
            if atr_pct < self.config.MIN_ATR_PCT: return None

            return {
                "ticker": ticker,
                "price": round(current_price, 2),
                "rsi_daily": round(rsi_daily, 2),
                "rsi_4h": round(rsi_h1, 2),
                "ema20": round(ema20, 2),
                "atr_pct": round(atr_pct, 2),
                "rs_sector": round(relative_strength, 2),
                "sector_etf": etf_ticker,
                "div_bullish": div_bullish,
                "is_vcp": is_vcp,
                "breakout_2h": breakout_2h,
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
