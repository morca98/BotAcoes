import logging
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import io
from datetime import datetime
import pytz

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
        tickers.update(self.config.ASSETS) # Garantir que a lista base está sempre presente
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
            nasdaq_count = 0
            for df in tables:
                if 'Ticker' in df.columns:
                    t_list = df['Ticker'].tolist()
                    tickers.update(t_list)
                    nasdaq_count = len(t_list)
                    break
                elif 'Symbol' in df.columns:
                    t_list = df['Symbol'].tolist()
                    tickers.update(t_list)
                    nasdaq_count = len(t_list)
                    break
            logger.info(f"Nasdaq 100 obtido: {nasdaq_count} ativos")
        except Exception as e:
            logger.error(f"Erro ao obter índices da Wikipedia: {e}")
            tickers.update(self.config.ASSETS)

        clean_tickers = [str(t).replace('.', '-') for t in tickers if isinstance(t, (str, float)) and str(t) != 'nan']
        final_list = list(set(clean_tickers))
        logger.info(f"Universo dinâmico final: {len(final_list)} ativos")
        return final_list

    def filter_by_liquidity(self, tickers, limit=500):
        """Filtra os top ativos por volume financeiro (Dollar Volume)."""
        logger.info(f"Iniciando filtro de liquidez para {len(tickers)} ativos (Alvo: {limit})")
        
        if len(tickers) <= limit:
            return tickers

        data = []
        # Chunk menor para evitar timeouts de rede
        chunk_size = 100
        for i in range(0, len(tickers), chunk_size):
            chunk = tickers[i:i + chunk_size]
            try:
                # Período de 1d é suficiente e muito mais rápido
                batch = yf.download(chunk, period="1d", group_by='ticker', threads=True, progress=False, timeout=20)
                
                for t in chunk:
                    try:
                        # Lidar com diferentes formatos de retorno do yfinance
                        if isinstance(batch.columns, pd.MultiIndex):
                            ticker_data = batch[t]
                        else:
                            ticker_data = batch
                            
                        if not ticker_data.empty:
                            # Tentar obter o valor mais recente não nulo
                            valid_data = ticker_data.dropna(subset=['Close', 'Volume'])
                            if not valid_data.empty:
                                last_close = valid_data['Close'].iloc[-1]
                                last_vol = valid_data['Volume'].iloc[-1]
                                dollar_vol = last_close * last_vol
                                if dollar_vol > 0:
                                    data.append({'ticker': t, 'dollar_vol': dollar_vol})
                    except:
                        continue
            except Exception as e:
                logger.error(f"Erro ao processar lote de liquidez: {e}")
                continue

        df = pd.DataFrame(data)
        logger.info(f"Dados de liquidez obtidos para {len(df)} ativos.")
        
        if len(df) < (limit / 2):
            logger.warning("Poucos dados de liquidez obtidos. Retornando universo original limitado.")
            return tickers[:limit]
            
        top_tickers = df.sort_values(by='dollar_vol', ascending=False).head(limit)['ticker'].tolist()
        logger.info(f"Filtro concluído. {len(top_tickers)} ativos selecionados.")
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
        if len(h1_df) < 20: return False
        h2_df = h1_df.resample('2h').agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        }).dropna()
        if len(h2_df) < 10: return False
        current_close = h2_df['Close'].iloc[-1]
        previous_highs_max = h2_df['High'].iloc[-11:-1].max()
        if current_close > previous_highs_max:
            return True
        return False

    def get_key_supports(self, ticker, current_price, h1_df=None):
        """Calcula suportes virgens de aberturas diárias e semanais (até 1 ano atrás)."""
        supports = []
        try:
            tk = yf.Ticker(ticker)
            daily_data = tk.history(period="18mo", interval="1d")
            if len(daily_data) < 20: return supports
            daily_data.index = pd.to_datetime(daily_data.index)
            
            # 1. Abertura Diária (Hoje e Ontem)
            # Verificar os últimos 2 dias úteis
            for i in range(1, 3):
                row = daily_data.iloc[-i]
                d_open, d_time = float(row['Open']), row.name
                
                # Virgindade: Mínima desde a abertura (com tolerância de 0.1%)
                # Para o dia atual, verificamos o intraday se possível
                after_d = daily_data[daily_data.index >= d_time]
                min_since_d = float(after_d['Low'].min())
                
                if min_since_d >= (d_open * 0.999) and current_price > d_open:
                    dist = ((current_price - d_open) / d_open) * 100
                    if dist <= 10.0:
                        label = "Diária (Hoje)" if i == 1 else "Diária (Ant.)"
                        supports.append({"type": label, "price": round(d_open, 2), "dist": round(dist, 2), "virgin": True})

            # 2. Aberturas Semanais (Esta semana + 52 semanas atrás)
            last_monday = daily_data.index[-1] - pd.Timedelta(days=daily_data.index[-1].weekday())
            
            for i in range(0, 53): # 0 é esta semana, 1-52 são semanas passadas
                target_monday = last_monday - pd.Timedelta(days=7 * i)
                week_df = daily_data[daily_data.index.date >= target_monday.date()]
                if week_df.empty: continue
                
                w_row = week_df.iloc[0]
                w_open, w_time = float(w_row['Open']), w_row.name
                
                # Virgindade: A regra de ouro é ignorar a mínima do PRÓPRIO dia da abertura
                # se o preço fechou acima e nunca mais voltou lá nos dias seguintes.
                after_w_days = daily_data[daily_data.index > w_time] # Dias POSTERIORES
                
                is_virgin = True
                if not after_w_days.empty:
                    min_after = float(after_w_days['Low'].min())
                    if min_after < (w_open * 0.999):
                        is_virgin = False
                
                # Também checamos se o próprio dia da abertura não "atropelou" o nível demais
                if float(w_row['Low']) < (w_open * 0.995): # Tolerância maior no dia da abertura (0.5%)
                    is_virgin = False

                if is_virgin and current_price > w_open:
                    dist = ((current_price - w_open) / w_open) * 100
                    if dist <= 10.0:
                        date_str = w_time.strftime("%d/%m")
                        label = "Semanal (Atual)" if i == 0 else f"Semanal ({date_str})"
                        supports.append({"type": label, "price": round(w_open, 2), "dist": round(dist, 2), "virgin": True})
            
            # Remover duplicados (ex: se o Diário de Hoje for igual ao Semanal Atual)
            unique_supports = {}
            for s in supports:
                if s['price'] not in unique_supports or len(s['type']) < len(unique_supports[s['price']]['type']):
                    unique_supports[s['price']] = s
            
            # Ordenar por proximidade e limitar aos 5 mais relevantes
            sorted_supports = sorted(unique_supports.values(), key=lambda x: x['dist'])[:5]
            return sorted_supports
                            
        except Exception as e:
            logger.error(f"Erro ao calcular suportes para {ticker}: {e}")
            
        return supports

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
            atr_series = self._atr(daily, 14)
            if atr_series.empty or np.isnan(atr_series.iloc[-1]):
                return None
            
            atr = float(atr_series.iloc[-1])
            atr_pct = (atr / current_price) * 100
            dist_ema20 = ((current_price - ema20) / ema20) * 100

            # Obter suportes usando o h1 já carregado
            supports = self.get_key_supports(ticker, current_price, h1)

            # Validação final para evitar NaN no relatório
            metrics = [current_price, rsi_daily, rsi_h1, atr_pct, relative_strength, dist_ema20]
            if any(np.isnan(m) or np.isinf(m) for m in metrics):
                return None

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
                "key_supports": supports,
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
