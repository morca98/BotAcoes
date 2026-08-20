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

class BreakoutScoreBacktest:
    def __init__(self):
        self.config = Config()
        self.scanner = Scanner(self.config)
        self.trades = []

    def run(self, tickers, days=30):
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        print(f"--- 🚀 BACKTEST DE ROMPIMENTOS POR SCORE (Últimos {days} dias) ---")
        
        for ticker in tickers:
            try:
                self.test_ticker(ticker, start_date, end_date)
            except:
                pass
        self.summary()

    def test_ticker(self, ticker, start_date, end_date):
        tk = yf.Ticker(ticker)
        h1 = tk.history(start=start_date - timedelta(days=5), end=end_date, interval="1h")
        if h1.empty or len(h1) < 40: return
        daily = tk.history(period="2y", interval="1d").dropna()
        if daily.empty: return

        h2 = h1.resample('2h').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}).dropna()
        h4 = h1.resample('4h').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}).dropna()
        
        active_trade = None
        for i in range(15, len(h2)):
            row = h2.iloc[i]
            t = h2.index[i]
            
            if active_trade:
                relevant_h1 = h1[h1.index > active_trade['entry_time']]
                for _, candle in relevant_h1.iterrows():
                    if candle['Low'] <= active_trade['sl']:
                        active_trade['status'] = 'Loss'; active_trade['result'] = -1.0
                        self.trades.append(active_trade); active_trade = None; break
                    elif candle['High'] >= active_trade['tp']:
                        active_trade['status'] = 'Win'; active_trade['result'] = 3.0
                        self.trades.append(active_trade); active_trade = None; break
                if active_trade is None: continue
                break

            # Rompimento da máxima das últimas 20 horas (10 velas de 2h)
            prev_high = h2['High'].iloc[i-10:i].max()
            if row['Close'] > prev_high:
                # Usar a mínima da vela de 4h que engloba o período anterior
                h4_before = h4[h4.index <= t].iloc[-2:]
                if h4_before.empty: continue
                
                sl = h4_before['Low'].min() * 0.995 # SL mais conservador
                entry = row['Close']
                risk = entry - sl
                
                if risk > 0:
                    # Score Simplificado para Backtest
                    avg_vol = h2['Volume'].iloc[i-10:i].mean()
                    vol_spike = row['Volume'] > (avg_vol * 1.1)
                    score = 2 if vol_spike else 1
                    
                    active_trade = {
                        'ticker': ticker, 'score': score, 'entry_time': t,
                        'entry_price': entry, 'sl': sl, 'tp': entry + (risk * 3),
                        'status': 'UNRESOLVED', 'result': 0
                    }

    def summary(self):
        if not self.trades:
            print("Nenhum rompimento detetado.")
            return
        df = pd.DataFrame(self.trades)
        df = df[df['status'] != 'UNRESOLVED']
        
        g1 = df[df['score'] == 1]
        g_plus = df[df['score'] > 1]
        
        def get_metrics(group):
            if group.empty: return "N/A"
            total = len(group); wins = len(group[group['result'] > 0])
            wr = wins / total * 100; profit = group['result'].sum()
            return f"Trades: {total} | WR: {wr:.1f}% | Lucro: {profit:+.1f}R"

        print("\n" + "="*50)
        print("📊 COMPARATIVO ROMPIMENTOS: SCORE 1 vs SCORE > 1")
        print("="*50)
        print(f"🔹 SCORE 1 (Base):    {get_metrics(g1)}")
        print(f"🚀 SCORE > 1 (Sniper): {get_metrics(g_plus)}")
        print("="*50)

if __name__ == "__main__":
    tickers = [
        "NVDA", "AAPL", "MSFT", "TSLA", "AMD", "META", "AMZN", "NFLX", "GOOGL", "AVGO",
        "ASML.AS", "SAP.DE", "MC.PA", "ITX.MC", "EDP.LS", "OR.PA", "AIR.PA", "SIE.DE",
        "JPM", "GS", "V", "AXP", "COST", "CAT", "GE", "UBER", "PLTR", "MSTR",
        "SHOP", "COIN", "CRWD", "NOW", "SNOW", "PANW", "MRVL", "MU", "LRCX", "QCOM",
        "ADBE", "INTU", "PYPL", "SQ", "ABNB", "MELI", "BKNG", "MAR", "HLT", "LVMH.PA"
    ]
    bt = BreakoutScoreBacktest()
    bt.run(tickers, days=30)
