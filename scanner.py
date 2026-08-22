import logging
import os
import json
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import io

logger = logging.getLogger(__name__)

class Scanner:
    SECTOR_ETFS = {
        # Mapeamento Wikipedia (GICS)
        "Information Technology": "XLK",
        "Financials": "XLF",
        "Health Care": "XLV",
        "Consumer Discretionary": "XLY",
        "Consumer Staples": "XLP",
        "Materials": "XLB",
        # Mapeamento alternativo/yfinance
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

    THEMATIC_ETFS = ["SMH", "XBI", "IBIT", "IWM", "QQQ", "SPY", "EXSA.DE"]

    def __init__(self, config):
        self.config = config
        self._sector_data_cache = {}
        self._ticker_sectors = {} # Cache de setores: Ticker -> Sector Name
        self._universe_cache = None

    def get_dynamic_universe(self):
        """Obtém componentes do S&P 500, Nasdaq 100 e mapeia setores para evitar chamadas lentas."""
        tickers = set(self.THEMATIC_ETFS)
        tickers.update(self.config.ASSETS)
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        
        try:
            # 1. S&P 500 + Setores
            url_sp500 = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
            response = requests.get(url_sp500, headers=headers, timeout=10)
            sp500 = pd.read_html(io.StringIO(response.text))[0]
            for _, row in sp500.iterrows():
                symbol = str(row['Symbol']).replace('.', '-')
                tickers.add(symbol)
                self._ticker_sectors[symbol] = row['GICS Sector']
            
            # 2. Nasdaq 100 + Setores
            url_nasdaq = 'https://en.wikipedia.org/wiki/Nasdaq-100'
            response = requests.get(url_nasdaq, headers=headers, timeout=10)
            tables = pd.read_html(io.StringIO(response.text))
            for df in tables:
                symbol_col = next((c for c in df.columns if str(c) in ['Ticker', 'Symbol']), None)
                sector_col = next((c for c in df.columns if isinstance(c, str) and ('Sector' in c or 'Industry' in c)), None)
                if symbol_col:
                    for _, row in df.iterrows():
                        symbol = str(row[symbol_col]).replace('.', '-')
                        tickers.add(symbol)
                        if sector_col:
                            self._ticker_sectors[symbol] = row[sector_col]
                    break
        except Exception as e:
            logger.error(f"Erro ao obter índices da Wikipedia: {e}")

        final_list = list(set([t for t in tickers if isinstance(t, str) and t != 'nan']))
        
        # 3. Adicionar STOXX 600 (Europa)
        try:
            if os.path.exists("stoxx600_tickers.json"):
                with open("stoxx600_tickers.json", "r") as f:
                    stoxx_list = json.load(f)
                    final_list.extend(stoxx_list)
                    logger.info(f"Adicionados {len(stoxx_list)} ativos do STOXX 600.")
        except Exception as e:
            logger.error(f"Erro ao carregar STOXX 600: {e}")

        final_list = list(set(final_list))
        
        # De-duplicação: Manter apenas GOOGL (Alphabet)
        if "GOOGL" in final_list and "GOOG" in final_list:
            final_list.remove("GOOG")
            
        logger.info(f"Universo dinâmico final: {len(final_list)} ativos. Setores mapeados: {len(self._ticker_sectors)}")
        return final_list

    def filter_by_liquidity(self, tickers, limit=500):
        """Filtra os top ativos por volume financeiro (Dollar Volume)."""
        logger.info(f"Iniciando filtro de liquidez para {len(tickers)} ativos (Alvo: {limit})")
        
        if len(tickers) <= limit:
            return tickers

        data = []
        # Chunk menor para evitar timeouts e rate limits
        chunk_size = 50
        import time
        for i in range(0, len(tickers), chunk_size):
            chunk = tickers[i:i + chunk_size]
            retries = 3
            while retries > 0:
                try:
                    # Usar 5d para garantir dados mesmo em feriados ou mercados fechados
                    batch = yf.download(chunk, period="5d", group_by='ticker', threads=True, progress=False, timeout=30)
                    
                    for t in chunk:
                        try:
                            if isinstance(batch.columns, pd.MultiIndex):
                                ticker_data = batch[t]
                            else:
                                ticker_data = batch
                                
                            if ticker_data is not None and not ticker_data.empty:
                                valid_data = ticker_data.dropna(subset=['Close', 'Volume'])
                                if not valid_data.empty:
                                    # Média dos últimos 5 dias para volume mais estável
                                    avg_vol = valid_data['Volume'].mean()
                                    last_close = valid_data['Close'].iloc[-1]
                                    dollar_vol = last_close * avg_vol
                                    if dollar_vol > 0:
                                        data.append({'ticker': t, 'dollar_vol': dollar_vol})
                        except:
                            continue
                    
                    time.sleep(1) # Pequena pausa entre chunks
                    break # Sucesso, sai do loop de retries
                except Exception as e:
                    if "429" in str(e) or "Too Many Requests" in str(e):
                        logger.warning(f"Rate limit no filtro de liquidez. A aguardar 20s... (Tentativas restantes: {retries})")
                        time.sleep(20)
                        retries -= 1
                    else:
                        logger.error(f"Erro no download do chunk: {e}")
                        break

        df = pd.DataFrame(data)
        logger.info(f"Dados de liquidez obtidos para {len(df)} ativos.")
        
        if len(df) < (limit / 2):
            logger.warning("Poucos dados de liquidez obtidos. Retornando universo original limitado.")
            return tickers[:limit]
            
        top_tickers = df.sort_values(by='dollar_vol', ascending=False).head(limit)['ticker'].tolist()
        logger.info(f"Filtro concluído. {len(top_tickers)} ativos selecionados.")
        return top_tickers

    def _get_sector_etf_data(self, etf_ticker: str):
        if not etf_ticker:
            return None
        if etf_ticker not in self._sector_data_cache:
            try:
                from data_provider import DataProvider
                dp = DataProvider()
                logger.info(f"A descarregar benchmark: {etf_ticker}")
                data = dp.fetch_daily(etf_ticker)
                if data is not None and not data.empty:
                    self._sector_data_cache[etf_ticker] = data.dropna(subset=['Close'])
                else:
                    # Guardar None para evitar tentativas repetidas se falhar
                    self._sector_data_cache[etf_ticker] = None
            except Exception as e:
                logger.error(f"Erro ao obter dados do ETF {etf_ticker}: {e}")
                self._sector_data_cache[etf_ticker] = None
        return self._sector_data_cache.get(etf_ticker)

    def preload_benchmarks(self):
        """Pré-carrega os principais benchmarks para evitar concorrência no início do scan."""
        logger.info("A pré-carregar benchmarks (SPY, EXSA.DE e setores)...")
        self._get_sector_etf_data("SPY")
        self._get_sector_etf_data("EXSA.DE")
        # Pre-carregar setores comuns
        for etf in set(self.SECTOR_ETFS.values()):
            self._get_sector_etf_data(etf)

    @staticmethod
    def _closed_daily_bars(df):
        if df is None or df.empty:
            return pd.DataFrame()
        frame = df.copy().sort_index()
        now = pd.Timestamp.now(tz=getattr(frame.index, "tz", None))
        if getattr(now, "tzinfo", None) is not None and getattr(frame.index, "tz", None) is None:
            now = now.tz_localize(None)
        if frame.index[-1].date() == now.date():
            frame = frame.iloc[:-1]
        return frame

    @staticmethod
    def _closed_hourly_bars(df):
        if df is None or df.empty:
            return pd.DataFrame()
        frame = df.copy().sort_index()
        now = pd.Timestamp.now(tz=getattr(frame.index, "tz", None))
        last_start = frame.index[-1]
        if getattr(last_start, "tzinfo", None) is None and getattr(now, "tzinfo", None) is not None:
            now = now.tz_localize(None)
        if now < last_start + pd.Timedelta(hours=1):
            frame = frame.iloc[:-1]
        return frame

    def _aggregate_complete_4h(self, h1_df):
        h1_df = self._closed_hourly_bars(h1_df)
        if h1_df.empty:
            return pd.DataFrame()
        counts = h1_df["Close"].resample("4h").count()
        h4_df = h1_df.resample("4h").agg({
            "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"
        }).dropna()
        return h4_df.loc[counts.reindex(h4_df.index).fillna(0) >= 4]

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
        h1_df = self._closed_hourly_bars(h1_df)
        if len(h1_df) < 22:
            return False
        h2_df = h1_df.resample('2h').agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        }).dropna()
        if len(h2_df) < 11:
            return False
        return bool(h2_df['Close'].iloc[-1] > h2_df['High'].iloc[-11:-1].max())

    def get_breakout_details(self, h1_df, daily_df):
        """Retorna detalhes ricos para o alerta de rompimento (Volume ratio, VCP, Distância, Alvo)."""
        try:
            if len(h1_df) < 20 or len(daily_df) < 20:
                return {"vol_ratio": 1.0, "is_vcp": False, "dist_pct": 0.0, "target": 0.0}
            
            h1_df = self._closed_hourly_bars(h1_df)
            h2_df = h1_df.resample('2h').agg({
                'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
            }).dropna()

            if len(h2_df) < 11:
                return {"vol_ratio": 1.0, "is_vcp": False, "dist_pct": 0.0, "target": 0.0}
            
            current_close = h2_df['Close'].iloc[-1]
            prev_high = h2_df['High'].iloc[-11:-1].max()
            
            # 1. Distância do breakout
            dist_pct = ((current_close - prev_high) / prev_high) * 100
            
            # 2. Volume ratio (Volume da última vela 2h vs média das últimas 10 velas 2h)
            last_vol = h2_df['Volume'].iloc[-1]
            avg_vol = h2_df['Volume'].iloc[-11:-1].mean()
            vol_ratio = last_vol / avg_vol if avg_vol > 0 else 1.0
            
            # 3. VCP Check
            is_vcp = self._check_vcp(daily_df)
            
            # 4. Próximo alvo (Máxima de 5 dias ou resistência estimada)
            target = float(daily_df['High'].iloc[-5:].max())
            if target <= current_close:
                target = current_close * 1.05 # 5% acima se já renovou máximas
                
            return {
                "vol_ratio": round(vol_ratio, 2),
                "is_vcp": is_vcp,
                "dist_pct": round(dist_pct, 2),
                "target": round(target, 2)
            }
        except Exception as e:
            logger.error(f"Erro ao obter detalhes de rompimento: {e}")
            return {"vol_ratio": 1.0, "is_vcp": False, "dist_pct": 0.0, "target": 0.0}

    def _check_pullback_leadership(self, asset_h1, benchmark_h1):
        """Verifica se o ativo demonstrou resiliência/liderança durante a última perna de queda (pullback)."""
        try:
            if asset_h1 is None or benchmark_h1 is None or len(asset_h1) < 15 or len(benchmark_h1) < 15:
                return False
            
            # Olhar para as últimas 15 velas de 1h (perna recente)
            recent_asset = asset_h1.iloc[-15:]
            recent_bench = benchmark_h1.iloc[-15:]
            
            asset_high = recent_asset['High'].max()
            asset_current = recent_asset['Close'].iloc[-1]
            asset_drawdown = (asset_current - asset_high) / asset_high
            
            bench_high = recent_bench['High'].max()
            bench_current = recent_bench['Close'].iloc[-1]
            bench_drawdown = (bench_current - bench_high) / bench_high
            
            # Se o benchmark caiu mais do que o ativo (ex: bench caiu 2% e ativo caiu 0.5%), há liderança/resiliência
            # Nota: drawdowns são negativos (ex: -0.02 vs -0.005)
            if asset_drawdown > bench_drawdown and bench_drawdown < -0.005:
                return True
        except Exception as e:
            logger.error(f"Erro ao calcular pullback leadership: {e}")
        return False

    def check_reversal_15m(self, ticker):
        """Verifica se a última vela de 15min tem Mínima e Máxima superiores à anterior."""
        try:
            tk = yf.Ticker(ticker)
            # Obter dados de 15 minutos (último dia para garantir dados suficientes)
            df = tk.history(period="1d", interval="15m")
            if df is None or df.empty:
                return False
            now = pd.Timestamp.now(tz=getattr(df.index, "tz", None))
            last_start = df.index[-1]
            if getattr(last_start, "tzinfo", None) is None and getattr(now, "tzinfo", None) is not None:
                now = now.tz_localize(None)
            if now < last_start + pd.Timedelta(minutes=15):
                df = df.iloc[:-1]
            if len(df) < 2:
                return False

            last_candle = df.iloc[-1]
            prev_candle = df.iloc[-2]
            
            # Critério: Mínima Superior E Máxima Superior
            if last_candle['Low'] > prev_candle['Low'] and last_candle['High'] > prev_candle['High']:
                return True
            return False
        except Exception as e:
            logger.error(f"Erro ao verificar reversão 15m para {ticker}: {e}")
            return False

    def _calculate_avwap(self, df, anchor_type="low"):
        """Calcula o Anchored VWAP a partir do topo ou fundo das últimas 4 semanas."""
        if len(df) < 20: return None
        # Últimas 4 semanas (aprox 20 dias úteis)
        recent = df.iloc[-20:]
        if anchor_type == "low":
            anchor_idx = recent['Low'].idxmin()
        else:
            anchor_idx = recent['High'].idxmax()
            
        anchor_df = df.loc[anchor_idx:]
        if anchor_df.empty: return None
        
        # Fórmula VWAP: Sum(Price * Volume) / Sum(Volume)
        # Usamos o preço médio (Typical Price)
        tp = (anchor_df['High'] + anchor_df['Low'] + anchor_df['Close']) / 3
        vwap = (tp * anchor_df['Volume']).cumsum() / anchor_df['Volume'].cumsum()
        return float(vwap.iloc[-1])

    def get_key_supports(self, ticker, current_price, daily_data):
        """Calcula zonas abaixo do preço usando sessões diária e semanal fechadas."""
        all_levels = []
        try:
            daily_data = self._closed_daily_bars(daily_data)
            if daily_data is None or len(daily_data) < 200:
                return []

            ema200 = float(daily_data["Close"].ewm(span=200, adjust=False).mean().iloc[-1])
            ema70 = float(daily_data["Close"].ewm(span=70, adjust=False).mean().iloc[-1])

            last_year = daily_data.iloc[-252:]
            high_52w = float(last_year['High'].max())
            low_52w = float(last_year['Low'].min())
            
            # Golden Pocket (61.8% - 66.6%)
            fib_618 = high_52w - (high_52w - low_52w) * 0.618
            fib_666 = high_52w - (high_52w - low_52w) * 0.666
            
            # AVWAP
            avwap_low = self._calculate_avwap(daily_data, "low")
            avwap_high = self._calculate_avwap(daily_data, "high")

            # Adicionar níveis técnicos à lista de candidatos
            tech_candidates = [
                ("EMA 200", ema200), ("EMA 70", ema70), 
                ("Fib 61.8%", fib_618), ("Fib 66.6%", fib_666)
            ]
            if avwap_low: tech_candidates.append(("AVWAP Fundo", avwap_low))
            if avwap_high: tech_candidates.append(("AVWAP Topo", avwap_high))
            
            for label, price in tech_candidates:
                if price < current_price:
                    dist = ((current_price - price) / price) * 100
                    if dist <= self.config.MAX_SUPPORT_DISTANCE_PCT:
                        all_levels.append({"type": label, "price": price, "is_tech": True})

            # 2. Aberturas Virgens (Diárias e Semanais)
            rev_low_min = daily_data['Low'][::-1].cummin()[::-1]
            daily_opens = daily_data.iloc[-252:]
            for i in range(1, len(daily_opens) + 1):
                row = daily_opens.iloc[-i]
                d_open, d_time = float(row['Open']), row.name
                if d_open < current_price:
                    dist = ((current_price - d_open) / d_open) * 100
                    if dist <= self.config.MAX_SUPPORT_DISTANCE_PCT:
                        is_virgin = True
                        if i > 1:
                            min_after = rev_low_min.iloc[-i+1:].min()
                            if min_after < (d_open * 0.999): is_virgin = False
                        if is_virgin:
                            label = f"Diária ({d_time.strftime('%d/%m')})"
                            all_levels.append({"type": label, "price": d_open, "is_tech": False})

            weekly_data = daily_data.resample('W-FRI').agg({'Open': 'first', 'Low': 'min'}).dropna()
            weekly_data = weekly_data[weekly_data.index.date <= daily_data.index[-1].date()]
            weekly_opens = weekly_data.iloc[-53:]
            for i in range(len(weekly_opens)):
                w_row = weekly_opens.iloc[i]
                w_open, w_time = float(w_row['Open']), w_row.name
                if w_open < current_price:
                    dist = ((current_price - w_open) / w_open) * 100
                    if dist <= self.config.MAX_SUPPORT_DISTANCE_PCT:
                        after_w = daily_data[daily_data.index > w_time]
                        is_virgin = True
                        if not after_w.empty and float(after_w['Low'].min()) < (w_open * 0.999): is_virgin = False
                        if is_virgin:
                            all_levels.append({"type": f"Semanal ({w_time.strftime('%d/%m')})", "price": w_open, "is_tech": False})

            # 3. Lógica de Clustering (Agrupar níveis a menos de 0.3%)
            if not all_levels: return []
            
            all_levels.sort(key=lambda x: x['price'], reverse=True) # Do mais alto para o mais baixo
            clusters = []
            if all_levels:
                current_cluster = [all_levels[0]]
                for i in range(1, len(all_levels)):
                    prev_price = current_cluster[-1]['price']
                    curr_price = all_levels[i]['price']
                    # Se a diferença for < 0.3% do preço mais alto do cluster
                    if (prev_price - curr_price) / prev_price <= 0.003:
                        current_cluster.append(all_levels[i])
                    else:
                        clusters.append(current_cluster)
                        current_cluster = [all_levels[i]]
                clusters.append(current_cluster)

            # 4. Formatar Clusters em Zonas
            final_zones = []
            for cluster in clusters:
                prices = [c['price'] for c in cluster]
                min_p, max_p = min(prices), max(prices)
                avg_p = sum(prices) / len(prices)
                dist = ((current_price - avg_p) / avg_p) * 100
                
                # Identificar componentes e confluências
                types = [c['type'] for c in cluster]
                has_ema200 = any("EMA 200" in t for t in types)
                has_ema70 = any("EMA 70" in t for t in types)
                has_fib = any("Fib" in t for t in types)
                has_avwap = any("AVWAP" in t for t in types)
                
                # Nome da Zona
                if len(cluster) > 1:
                    zone_label = f"Zona ({len(cluster)} níveis)"
                else:
                    zone_label = cluster[0]['type']

                final_zones.append({
                    "type": zone_label,
                    "price": f"{min_p:.2f} - {max_p:.2f}" if min_p != max_p else f"{min_p:.2f}",
                    "avg_price": avg_p,
                    "dist": round(dist, 2),
                    "conf_ema200": has_ema200,
                    "conf_ema70": has_ema70,
                    "conf_fib": has_fib,
                    "conf_avwap": has_avwap,
                    "is_zone": len(cluster) > 1,
                    "virgin": any(not c['is_tech'] for c in cluster)
                })

            return sorted(final_zones, key=lambda x: x['dist'])[:5]
        except Exception as e:
            logger.error(f"Erro ao calcular suportes para {ticker}: {e}")
        return []

    def analyze(self, ticker: str):
        import time
        retries = 2
        while retries >= 0:
            try:
                # OTIMIZAÇÃO EXTREMA: Usar mapeamento de setores da Wikipedia e fast_info
                tk = yf.Ticker(ticker)
                
                # 1. Tentar obter preço e market cap
                try:
                    f_info = tk.fast_info
                    market_cap = f_info.get("market_cap")
                    currency = f_info.get("currency", "USD")
                    current_price = f_info.get("last_price")
                    
                    # Fallback para European stocks onde fast_info falha frequentemente
                    if market_cap is None or current_price is None:
                        # Tentar obter do tk.info apenas se necessário (lento)
                        # Ou assumir que se está no STOXX 600, cumpre o critério
                        pass
                except:
                    market_cap = None
                    current_price = None
                    currency = "USD"

                # 2. Obter histórico (essencial para indicadores)
                daily = tk.history(period="2y", interval="1d")
                if daily is None or len(daily) < 50: return None
                
                # Limpeza de NaNs no final (comum em mercados fechados ou erros de dados)
                daily = daily.dropna(subset=['Close', 'High', 'Low', 'Open'])
                daily = self._closed_daily_bars(daily)
                if len(daily) < 252:
                    return None

                # Se o preço falhou no fast_info, pegamos do histórico
                if current_price is None or np.isnan(current_price):
                    current_price = float(daily["Close"].iloc[-1])
                
                # Se o market_cap falhou, mas é STOXX 600, permitimos passar
                # (A maioria das STOXX 600 tem > 500M€)
                is_stoxx = any(ticker.endswith(s) for s in [".DE", ".PA", ".L", ".LS", ".MC", ".MI", ".AS", ".SW", ".ST", ".CO", ".OL", ".HE", ".VI", ".BR", ".IR", ".WA", ".LU", ".AT", ".TA"])
                
                if market_cap is not None:
                    # Se for europeu (pelo sufixo ou moeda), usamos 500M
                    min_mc = 500_000_000 if (currency == "EUR" or is_stoxx) else self.config.MIN_MARKET_CAP
                    if market_cap < min_mc: return None
                
                # Dados 1h (para 4h e rompimentos) - Otimizado para 30 dias
                h1 = tk.history(period="30d", interval="60m")
                if h1 is not None:
                    h1 = h1.dropna(subset=['Close'])
                break # Sucesso
            except Exception as e:
                if "429" in str(e) or "Too Many Requests" in str(e):
                    if retries > 0:
                        logger.warning(f"Rate limit em {ticker}. A aguardar 10s... ({retries} restam)")
                        time.sleep(10)
                        retries -= 1
                        continue
                    else:
                        raise e # Propagar para o loop principal
                else:
                    logger.error(f"Erro ao obter dados para {ticker}: {e}")
                    return None

        try:
            
            if current_price is None:
                current_price = float(daily["Close"].dropna().iloc[-1])
            
            if current_price < self.config.MIN_PRICE: return None

            # --- NOVOS FILTROS OBRIGATÓRIOS ---
            # 1. Filtro de Volatilidade Anual (High-Low range > 50%)
            year_data = daily.iloc[-252:]
            if len(year_data) >= 100:
                y_high = year_data['High'].max()
                y_low = year_data['Low'].min()
                annual_vol = (y_high - y_low) / y_low
                if annual_vol < self.config.MIN_ANNUAL_VOL: 
                    logger.debug(f"Rejeitado {ticker}: Volatilidade {annual_vol:.2%} < {self.config.MIN_ANNUAL_VOL:.0%}")
                    return None
            
            # 2. RSI Diário < 50
            rsi_daily_series = self._rsi(daily["Close"], 14)
            if rsi_daily_series.empty: return None
            rsi_daily = float(rsi_daily_series.iloc[-1])
            if rsi_daily >= self.config.MAX_RSI_DAILY:
                logger.debug(f"Rejeitado {ticker}: RSI Diário {rsi_daily:.2f} >= {self.config.MAX_RSI_DAILY}")
                return None
            
            # 3. Obter Setor (Prioridade: Wikipedia Cache -> yfinance fast_info se disponível -> Skip)
            sector = self._ticker_sectors.get(ticker)
            if not sector:
                # Se não estiver no cache, tentamos o info mas apenas se for estritamente necessário
                # Para evitar lentidão, ativos fora do S&P500/Nasdaq100 podem ser analisados sem setor
                pass

            relative_strength = 0
            # Fallback inteligente: SPY para EUA, EXSA.DE para Europa
            default_etf = "EXSA.DE" if currency == "EUR" or any(ticker.endswith(s) for s in [".DE", ".PA", ".L", ".LS", ".MC", ".MI", ".AS", ".SW", ".ST", ".CO", ".OL", ".HE", ".VI", ".BR", ".IR", ".WA", ".LU", ".AT", ".TA"]) else "SPY"
            
            etf_ticker = self.SECTOR_ETFS.get(sector, default_etf) if sector else default_etf
            
            # Tentar obter dados do setor ou fallback
            sector_daily = self._get_sector_etf_data(etf_ticker)
            if sector_daily is None:
                sector_daily = self._get_sector_etf_data(default_etf)
                etf_ticker = default_etf

            if sector_daily is not None and len(sector_daily) >= 252:
                # Normalizar índices temporais antes de combinar Yahoo/Alpha Vantage.
                # Alguns feeds devolvem DatetimeIndex com timezone e outros sem timezone.
                ticker_close = daily['Close'].copy()
                sector_close = sector_daily['Close'].copy()
                if getattr(ticker_close.index, 'tz', None) is not None:
                    ticker_close.index = ticker_close.index.tz_localize(None)
                if getattr(sector_close.index, 'tz', None) is not None:
                    sector_close.index = sector_close.index.tz_localize(None)
                combined = pd.DataFrame({'ticker': ticker_close, 'sector': sector_close}).dropna()
                if len(combined) >= 252:
                    ticker_perf = combined['ticker'].iloc[-1] / combined['ticker'].iloc[-252]
                    sector_perf = combined['sector'].iloc[-1] / combined['sector'].iloc[-252]
                    relative_strength = ticker_perf / sector_perf
            
            # Filtro Estrito de Força Relativa: RS > 1.0
            # Só aceitamos ativos que estejam a superar o seu setor ou o mercado (SPY)
            if relative_strength <= 1.0:
                return None

            ema20 = float(daily["Close"].ewm(span=20, adjust=False).mean().iloc[-1])
            # Auditoria: Garantir que EMA 200 existe (mínimo 200 dias de dados)
            ema200_series = daily["Close"].ewm(span=200, adjust=False).mean()
            if len(ema200_series) < 200: return None
            ema200 = float(ema200_series.iloc[-1])
            
            h4 = self._aggregate_complete_4h(h1) if h1 is not None else pd.DataFrame()
            if len(h4) < 15:
                return None

            rsi_4h_series = self._rsi(h4["Close"], 14)
            rsi_4h = float(rsi_4h_series.iloc[-1])
            if rsi_4h >= self.config.MAX_RSI_4H:
                logger.debug(f"Rejeitado {ticker}: RSI 4h {rsi_4h:.2f} >= {self.config.MAX_RSI_4H}")
                return None

            macd_4h = h4["Close"].ewm(span=12, adjust=False).mean() - h4["Close"].ewm(span=26, adjust=False).mean()
            div_bullish = self._check_divergence(h4["Close"], rsi_4h_series) or self._check_divergence(h4["Close"], macd_4h)
            breakout_2h = self._check_breakout_2h(h1)

            is_vcp = self._check_vcp(daily)
            atr_series = self._atr(daily, 14)
            if atr_series.empty or np.isnan(atr_series.iloc[-1]):
                return None
            
            atr = float(atr_series.iloc[-1])
            atr_pct = (atr / current_price) * 100
            dist_ema20 = ((current_price - ema20) / ema20) * 100

            # Calcular suportes virgens usando os dados já carregados
            supports = self.get_key_supports(ticker, current_price, daily)
            
            # 5. Sistema de Estrelas (Scoring)
            score = 1 # Base por passar nos filtros
            if relative_strength > 1.2: score += 1
            if is_vcp: score += 1
            if div_bullish: score += 1
            if breakout_2h: score += 1
            
            # Confluência de suportes aumenta estrelas
            has_confluence = any(
                s.get('conf_ema200') or s.get('conf_ema70') or 
                s.get('conf_fib') or s.get('conf_avwap') 
                for s in supports if s['dist'] < 2.0
            )
            if has_confluence: score += 1
            
            stars = min(5, score)

            # 6. Filtro de Exaustão
            is_stretched = dist_ema20 > 6.0 # Mais de 6% longe da EMA 20
            
            # Validação final para evitar NaN no relatório
            metrics = [current_price, rsi_daily, rsi_4h, atr_pct, relative_strength, dist_ema20]
            if any(np.isnan(m) or np.isinf(m) for m in metrics):
                return None

            if rsi_daily > self.config.MAX_RSI_DAILY: return None
            if rsi_4h > self.config.MAX_RSI_4H:
                return None
            # O preço deve estar acima da EMA 200 para garantir tendência de longo prazo
            if current_price < ema200: return None
            if atr_pct < self.config.MIN_ATR_PCT: return None

            earnings_days = self._get_earnings_days(ticker)
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
                "breakout_2h": breakout_2h,
                "key_supports": supports,
                "stars": stars,
                "is_stretched": is_stretched,
                "market_cap": round(market_cap / 1e9, 2) if market_cap else 0,
                "earnings_days": earnings_days
            }
        except Exception as e:
            logger.error(f"Erro ao analisar {ticker}: {e}")
            return None

    def _get_earnings_days(self, ticker: str):
        """Calcula dias até aos próximos resultados para formatos DataFrame ou dicionário."""
        try:
            calendar = yf.Ticker(ticker).calendar
            dates = []
            if isinstance(calendar, pd.DataFrame):
                for column in calendar.columns:
                    if "earnings" in str(column).lower() or "date" in str(column).lower():
                        dates.extend(pd.to_datetime(calendar[column], errors="coerce").dropna().tolist())
            elif isinstance(calendar, dict):
                for key, value in calendar.items():
                    if "earnings" in str(key).lower() or "date" in str(key).lower():
                        values = value if isinstance(value, (list, tuple, pd.Series)) else [value]
                        dates.extend(pd.to_datetime(values, errors="coerce").dropna().tolist())

            now = pd.Timestamp.now(tz="UTC")
            future_days = []
            for date in dates:
                timestamp = pd.Timestamp(date)
                if timestamp.tzinfo is None:
                    timestamp = timestamp.tz_localize("UTC")
                else:
                    timestamp = timestamp.tz_convert("UTC")
                if timestamp >= now:
                    future_days.append((timestamp - now).days)
            return max(0, min(future_days)) if future_days else None
        except Exception as exc:
            logger.debug("Não foi possível obter earnings para %s: %s", ticker, exc)
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
