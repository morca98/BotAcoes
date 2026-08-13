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
        """Deteção de divergência bullish profissional: Preço faz nova mínima, mas indicador não."""
        if len(prices) < 30 or len(indicator) < 30: return False
        
        # Encontrar as duas últimas mínimas significativas no preço
        # Simplificação robusta: comparar as mínimas de dois blocos de 15 dias
        p_min1 = float(prices.iloc[-15:].min())
        p_min2 = float(prices.iloc[-30:-15].min())
        
        # Encontrar os valores do indicador nos mesmos pontos (ou as mínimas do indicador nos blocos)
        i_min1 = float(indicator.iloc[-15:].min())
        i_min2 = float(indicator.iloc[-30:-15].min())
        
        # Divergência Bullish: Preço fez mínima menor, Indicador fez mínima maior
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

    def get_key_supports(self, ticker, current_price, daily_data):
        """Calcula suportes virgens de aberturas diárias e semanais (até 1 ano atrás) com otimização profissional."""
        supports = []
        try:
            if daily_data is None or len(daily_data) < 20: return supports
            
            # Calcular confluências: EMA 200 e Fibonacci 61.8%
            ema200 = float(daily_data["Close"].ewm(span=200, adjust=False).mean().iloc[-1])
            
            # Fibonacci 61.8% (baseado no High/Low do último ano)
            last_year = daily_data.iloc[-252:] if len(daily_data) >= 252 else daily_data
            high_52w = float(last_year['High'].max())
            low_52w = float(last_year['Low'].min())
            fib_618 = high_52w - (high_52w - low_52w) * 0.618
            
            # OTIMIZAÇÃO: Calcular o Low acumulado reverso para verificar virgindade instantaneamente
            rev_low_min = daily_data['Low'][::-1].cummin()[::-1]

            # 1. Abertura Diária (Últimos 252 dias úteis - 1 ano)
            daily_opens = daily_data.iloc[-252:]
            for i in range(1, len(daily_opens) + 1):
                row = daily_opens.iloc[-i]
                d_open, d_time = float(row['Open']), row.name
                
                # Filtro rápido de distância (apenas suportes abaixo do preço atual e dentro de 12%)
                if d_open >= current_price: continue
                dist = ((current_price - d_open) / d_open) * 100
                if dist > 12.0: continue

                # Virgindade: O menor Low desde a abertura até hoje foi maior que a abertura?
                is_virgin = True
                if i > 1:
                    min_after = rev_low_min.iloc[-i+1:].min()
                    if min_after < (d_open * 0.999):
                        is_virgin = False
                
                if is_virgin:
                    conf_ema = abs(d_open - ema200) / ema200 <= 0.01
                    conf_fib = abs(d_open - fib_618) / fib_618 <= 0.01
                    label = "Diária (Hoje)" if i == 1 else f"Diária ({d_time.strftime('%d/%m')})"
                    supports.append({
                        "type": label, "price": round(d_open, 2), "dist": round(dist, 2), 
                        "virgin": True, "conf_ema": conf_ema, "conf_fib": conf_fib
                    })

            # 2. Aberturas Semanais (52 semanas atrás)
            # Agrupar por semana para obter aberturas reais
            weekly_data = daily_data.resample('W-MON').agg({'Open': 'first', 'Low': 'min'}).dropna()
            weekly_opens = weekly_data.iloc[-53:]
            
            for i in range(len(weekly_opens)):
                w_row = weekly_opens.iloc[i]
                w_open, w_time = float(w_row['Open']), w_row.name
                
                if w_open >= current_price: continue
                dist = ((current_price - w_open) / w_open) * 100
                if dist > 12.0: continue

                # Virgindade semanal: Menor Low diário desde aquela semana
                after_w = daily_data[daily_data.index > w_time]
                is_virgin = True
                if not after_w.empty:
                    if float(after_w['Low'].min()) < (w_open * 0.999):
                        is_virgin = False
                
                if is_virgin:
                    conf_ema = abs(w_open - ema200) / ema200 <= 0.01
                    conf_fib = abs(w_open - fib_618) / fib_618 <= 0.01
                    label = f"Semanal ({w_time.strftime('%d/%m')})"
                    supports.append({
                        "type": label, "price": round(w_open, 2), "dist": round(dist, 2), 
                        "virgin": True, "conf_ema": conf_ema, "conf_fib": conf_fib
                    })
            
            unique_supports = {}
            for s in supports:
                if s['price'] not in unique_supports:
                    unique_supports[s['price']] = s
            return sorted(unique_supports.values(), key=lambda x: x['dist'])[:5]
        except Exception as e:
            logger.error(f"Erro ao calcular suportes para {ticker}: {e}")
        return supports

    def analyze(self, ticker: str):
        try:
            # OTIMIZAÇÃO: Usar Ticker.fast_info para dados básicos e evitar tk.info
            tk = yf.Ticker(ticker)
            try:
                f_info = tk.fast_info
                market_cap = f_info.get("market_cap", 0)
                if market_cap and market_cap < self.config.MIN_MARKET_CAP: return None
                current_price = f_info.get("last_price")
            except:
                current_price = None

            daily = tk.history(period="2y", interval="1d")
            if daily is None or len(daily) < 100: return None
            
            # Se fast_info falhou, usar o último fecho do histórico
            if current_price is None:
                current_price = float(daily["Close"].dropna().iloc[-1])
            
            if current_price < self.config.MIN_PRICE: return None

            # Obter setor apenas se necessário para RS (tentar cache primeiro)
            sector = None
            # Nota: yfinance não tem setor no fast_info. Como trader, prefiro 
            # saltar o filtro de setor se o yfinance estiver lento, mas manter o bot fluido.
            # Por agora, tentamos tk.info com um timeout implícito curto (não nativo, mas via thread)
            # Para simplificar, assumimos que se falhar, o RS será 0 e o ativo filtrado.
            try:
                info = tk.info
                sector = info.get("sector")
            except: pass

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

            # Calcular suportes virgens usando os dados já carregados
            supports = self.get_key_supports(ticker, current_price, daily)

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
        """Cálculo de RSI profissional com tratamento de divisão por zero."""
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
        avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
        
        # Se não houver perdas, o RSI é 100
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(100) # Se avg_loss era 0, rs é nan, fillna(100) resolve

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
