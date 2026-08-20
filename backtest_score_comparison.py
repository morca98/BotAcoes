import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import logging
import sys
import os

sys.path.append(os.getcwd())
from config import Config
from scanner import Scanner

logging.basicConfig(level=logging.ERROR)

class ScoreComparisonBacktest:
    def __init__(self):
        self.config = Config()
        self.scanner = Scanner(self.config)
        self.trades = []

    def run(self, tickers, days=30):
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        print(f"--- 📊 COMPARATIVO DE PERFORMANCE POR FORÇA (Últimos {days} dias) ---")
        
        for ticker in tickers:
            try:
                self.test_ticker(ticker, start_date, end_date)
            except:
                pass

        self.summary()

    def test_ticker(self, ticker, start_date, end_date):
        tk = yf.Ticker(ticker)
        h15 = tk.history(start=start_date - timedelta(days=5), end=end_date, interval="15m")
        h1 = tk.history(start=start_date - timedelta(days=5), end=end_date, interval="60m")
        if h15.empty or len(h15) < 50: return
        
        daily = tk.history(period="2y", interval="1d").dropna()
        if daily.empty: return

        # Benchmark para RS Momentum
        bench_symbol = "EXSA.DE" if any(ticker.endswith(x) for x in [".DE", ".PA", ".L", ".LS", ".MC", ".MI", ".AS", ".SW", ".ST", ".CO", ".OL", ".HE", ".VI", ".BR", ".IR", ".WA", ".LU", ".AT", ".TA"]) else "SPY"
        bench_h1 = yf.Ticker(bench_symbol).history(start=start_date - timedelta(days=5), end=end_date, interval="60m")

        # Pré-calcular suportes
        avg_p = h15['Close'].mean()
        all_potential_supports = self.scanner.get_key_supports(ticker, avg_p, daily)
        if not all_potential_supports: return

        active_trade = None
        for i in range(20, len(h15)):
            current_candle = h15.iloc[i]
            current_time = h15.index[i]
            
            if active_trade:
                if current_candle['Low'] <= active_trade['sl']:
                    active_trade['status'] = 'Loss'
                    active_trade['result'] = -1.0
                    self.trades.append(active_trade)
                    active_trade = None
                elif current_candle['High'] >= active_trade['tp']:
                    active_trade['status'] = 'Win'
                    active_trade['result'] = 3.0
                    self.trades.append(active_trade)
                    active_trade = None
                continue

            price = current_candle['Close']
            for sup in all_potential_supports:
                sup_price = float(sup['price'].split(' - ')[0]) if ' - ' in sup['price'] else float(sup['price'])
                dist = abs(price - sup_price) / sup_price * 100
                
                if sup['virgin'] and dist <= 0.2:
                    if i + 1 >= len(h15): break
                    next_candle = h15.iloc[i+1]
                    
                    # Confirmação 15m
                    if next_candle['Low'] > current_candle['Low'] and next_candle['High'] > current_candle['High']:
                        # --- CÁLCULO DO SCORE REAL ---
                        conf_count = 0
                        if sup.get('conf_ema200'): conf_count += 1
                        if sup.get('conf_ema70'): conf_count += 1
                        if sup.get('conf_fib'): conf_count += 1
                        if sup.get('conf_avwap'): conf_count += 1
                        
                        # Volume Spike
                        avg_vol = h15['Volume'].iloc[i-20:i].mean()
                        vol_spike = current_candle['Volume'] > (avg_vol * 1.5)
                        
                        # RS Momentum
                        try:
                            t_h1 = h1[h1.index <= current_time].iloc[-15:]
                            b_h1 = bench_h1[bench_h1.index <= current_time].iloc[-15:]
                            pullback_leadership = self.scanner._check_pullback_leadership(t_h1, b_h1)
                        except: pullback_leadership = False
                        
                        total_score = conf_count + (1 if vol_spike else 0) + (1 if pullback_leadership else 0)
                        # Nota: Divergência omitida por simplicidade de cálculo no backtest massivo, 
                        # mas compensada pelos outros 5 fatores.
                        
                        strength_score = max(1, total_score)
                        
                        entry = next_candle['Close']
                        sl = min(current_candle['Low'], next_candle['Low']) * 0.998
                        risk = entry - sl
                        if risk > 0 and (risk/entry) < 0.05:
                            active_trade = {
                                'ticker': ticker, 'score': strength_score,
                                'entry_price': entry, 'sl': sl, 'tp': entry + (risk * 3),
                                'result': 0, 'status': 'UNRESOLVED'
                            }
                            break

    def summary(self):
        if not self.trades:
            print("Nenhum sinal gerado.")
            return
            
        df = pd.DataFrame(self.trades)
        df = df[df['status'] != 'UNRESOLVED']
        
        # Grupo 1: Força == 1
        g1 = df[df['score'] == 1]
        # Grupo 2: Força > 1
        g2 = df[df['score'] > 1]
        
        def get_metrics(group):
            if group.empty: return "N/A"
            total = len(group)
            wins = len(group[group['result'] > 0])
            wr = wins / total * 100
            profit = group['result'].sum()
            return f"Trades: {total} | WR: {wr:.1f}% | Lucro: {profit:+.1f}R"

        print("\n" + "="*50)
        print("📊 RESULTADO COMPARATIVO: FORÇA 1 vs FORÇA > 1")
        print("="*50)
        print(f"🔹 GRUPO A (Força 1):   {get_metrics(g1)}")
        print(f"🚀 GRUPO B (Força > 1): {get_metrics(g2)}")
        print("="*50)
        print("\n💡 Conclusão: Se o Lucro do Grupo B for proporcionalmente maior, a filtragem é correta.")

if __name__ == "__main__":
    tickers = [
        "NVDA", "AAPL", "MSFT", "TSLA", "AMD", "META", "AMZN", "NFLX", "GOOGL", "AVGO",
        "ASML.AS", "SAP.DE", "MC.PA", "ITX.MC", "EDP.LS", "OR.PA", "AIR.PA", "SIE.DE", "BNP.PA", "DAI.DE",
        "JPM", "GS", "V", "AXP", "COST", "CAT", "GE", "UBER", "PLTR", "MSTR",
        "SHOP", "COIN", "CRWD", "NOW", "SNOW", "PANW", "MRVL", "MU", "LRCX", "QCOM",
        "ADBE", "INTU", "PYPL", "SQ", "ABNB", "MELI", "BKNG", "MAR", "HLT", "LVMH.PA"
    ]
    bt = ScoreComparisonBacktest()
    bt.run(tickers, days=30)
