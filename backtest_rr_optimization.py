import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import logging
import sys
import os
import time

sys.path.append(os.getcwd())
from config import Config
from scanner import Scanner

logging.basicConfig(level=logging.ERROR)

class RROptimizationBacktest:
    def __init__(self):
        self.config = Config()
        self.scanner = Scanner(self.config)
        self.results = []

    def run(self, tickers, months=2):
        print(f"--- 🚀 INICIANDO BACKTEST DE OTIMIZAÇÃO RR (1:3, 1:4, 1:5) ---")
        print(f"Período: {months} meses | Ativos: {len(tickers)}")
        
        # Testar apenas os 10 mais líquidos para rapidez e dados densos
        test_tickers = tickers[:10]
        
        for ticker in test_tickers:
            print(f"A processar {ticker}...")
            try:
                self.analyze_ticker(ticker, months)
            except Exception as e:
                print(f"Erro em {ticker}: {e}")

        self.report()

    def analyze_ticker(self, ticker, months):
        # Obter dados
        import pytz
        end_date = datetime.now(pytz.UTC)
        start_date = end_date - timedelta(days=months*30)
        
        # yfinance v0.2.40+ returns a multi-index columns if download() is called for one ticker
        # We force single index by selecting the ticker if it exists in columns
        h1 = yf.download(ticker, start=start_date - timedelta(days=20), end=end_date, interval="1h", progress=False)
        if h1.empty or len(h1) < 100: return
        
        if isinstance(h1.columns, pd.MultiIndex):
            h1.columns = h1.columns.droplevel(1)
            
        daily = yf.download(ticker, period="2y", interval="1d", progress=False)
        if daily.empty: return
        
        if isinstance(daily.columns, pd.MultiIndex):
            daily.columns = daily.columns.droplevel(1)
        
        daily = daily.dropna(subset=['Close'])

        h2 = h1.resample('2h').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}).dropna()

        # 1. Encontrar Sinais de Suporte (Score > 1)
        for i in range(20, len(h1)):
            t = h1.index[i]
            if t < start_date: continue
            
            curr = h1.iloc[i]
            supports = self.scanner.get_key_supports(ticker, curr['Close'], daily[daily.index.date < t.date()])
            
            for sup in supports:
                sup_price = float(sup['price'].split(' - ')[0]) if ' - ' in sup['price'] else float(sup['price'])
                dist = abs(curr['Close'] - sup_price) / sup_price * 100
                
                if sup['virgin'] and dist <= 0.2:
                    # Confirmação 15m (simulada com H1 HH/HL para backtest longo)
                    if i + 1 < len(h1):
                        next_c = h1.iloc[i+1]
                        if next_c['Low'] > curr['Low'] and next_c['High'] > curr['High']:
                            # Calcular Score Simplificado
                            conf_count = (1 if sup.get('conf_ema200') else 0) + (1 if sup.get('conf_ema70') else 0) + \
                                         (1 if sup.get('conf_fib') else 0) + (1 if sup.get('conf_avwap') else 0)
                            
                            if conf_count >= 1: # Score > 1
                                entry = next_c['Close']
                                sl = min(curr['Low'], next_c['Low']) * 0.998
                                self.simulate_rr(ticker, entry, sl, h1.iloc[i+1:], "Support")

        # 2. Encontrar Sinais de Rompimento (Score > 1)
        for i in range(15, len(h2)):
            t = h2.index[i]
            if t < start_date: continue
            
            row = h2.iloc[i]
            prev_high = h2['High'].iloc[i-10:i].max()
            
            if row['Close'] > prev_high:
                # Score > 1 (Volume ou VCP ou RS)
                avg_vol = h2['Volume'].iloc[i-11:i-1].mean()
                vol_spike = row['Volume'] > (avg_vol * 1.2)
                is_vcp = self.scanner._check_vcp(daily[daily.index.date < t.date()])
                
                if vol_spike or is_vcp:
                    entry = row['Close']
                    # SL na mínima da vela 4h anterior (aproximadamente 2 velas de 2h)
                    sl = h2['Low'].iloc[i-2:i].min() * 0.998
                    self.simulate_rr(ticker, entry, sl, h1[h1.index > t], "Breakout")

    def simulate_rr(self, ticker, entry, sl, future_data, sig_type):
        risk = entry - sl
        if risk <= 0: return
        
        for rr in [3, 4, 5]:
            tp = entry + (risk * rr)
            status = 'LOSS'
            
            for _, candle in future_data.iterrows():
                if candle['Low'] <= sl:
                    status = 'LOSS'
                    break
                elif candle['High'] >= tp:
                    status = 'WIN'
                    break
            else:
                status = 'OPEN'
            
            self.results.append({
                'ticker': ticker,
                'type': sig_type,
                'rr_ratio': f"1:{rr}",
                'status': status,
                'profit': rr if status == 'WIN' else (-1 if status == 'LOSS' else 0)
            })

    def report(self):
        if not self.results:
            print("Nenhum resultado gerado.")
            return
            
        df = pd.DataFrame(self.results)
        
        summary = []
        for rr in ["1:3", "1:4", "1:5"]:
            for stype in ["Support", "Breakout"]:
                subset = df[(df['rr_ratio'] == rr) & (df['type'] == stype)]
                total = len(subset)
                wins = len(subset[subset['status'] == 'WIN'])
                losses = len(subset[subset['status'] == 'LOSS'])
                wr = (wins / (wins + losses)) * 100 if (wins + losses) > 0 else 0
                profit = subset['profit'].sum()
                
                summary.append({
                    'RR': rr,
                    'Estratégia': stype,
                    'Sinais': total,
                    'Win Rate': f"{wr:.1f}%",
                    'Lucro (R)': f"{profit:+.1f}R"
                })
        
        report_df = pd.DataFrame(summary)
        print("\n" + "="*80)
        print("📊 RELATÓRIO DE OTIMIZAÇÃO DE RISCO/RETORNO (RR)")
        print("="*80)
        print(report_df.to_string(index=False))
        print("="*80)
        
        # Guardar para processamento posterior
        df.to_csv("rr_optimization_results.csv", index=False)

if __name__ == "__main__":
    # Top 30 ativos para um teste profundo e rápido
    tickers = [
        "NVDA", "AAPL", "MSFT", "TSLA", "AMD", "META", "AMZN", "NFLX", "GOOGL", "AVGO",
        "ASML.AS", "SAP.DE", "MC.PA", "ITX.MC", "EDP.LS", "OR.PA", "AIR.PA", "SIE.DE",
        "JPM", "GS", "V", "AXP", "COST", "CAT", "GE", "UBER", "PLTR", "MSTR", "SHOP", "COIN"
    ]
    bt = RROptimizationBacktest()
    bt.run(tickers, months=3)
