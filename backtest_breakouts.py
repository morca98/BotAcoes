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
logger = logging.getLogger("BacktestBreakout")

class BreakoutBacktest:
    def __init__(self):
        self.config = Config()
        self.scanner = Scanner(self.config)
        self.results = []

    def run(self, tickers, days=30):
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        print(f"--- 🚀 BACKTEST DE ROMPIMENTOS (Últimos {days} dias) ---")
        print(f"Regra: SL na Mínima da Vela 4h Anterior | RR 1:3")
        print(f"Período: {start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}")
        
        for ticker in tickers:
            try:
                self.test_ticker(ticker, start_date, end_date)
            except Exception as e:
                pass

        self.summary()

    def test_ticker(self, ticker, start_date, end_date):
        tk = yf.Ticker(ticker)
        # Dados de 1h para simular o monitor de 2h do bot
        h1 = tk.history(start=start_date - timedelta(days=5), end=end_date, interval="1h")
        if h1.empty or len(h1) < 40: return

        # Resample para 2h (detecção) e 4h (Stop Loss)
        h2 = h1.resample('2h').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}).dropna()
        h4 = h1.resample('4h').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}).dropna()
        
        active_trade = None
        
        for i in range(15, len(h2)):
            current_h2 = h2.iloc[i]
            current_time = h2.index[i]
            
            if active_trade:
                # Verificar desfecho no H1 (mais preciso)
                relevant_h1 = h1[h1.index > active_trade['entry_time']]
                for _, candle in relevant_h1.iterrows():
                    if candle['Low'] <= active_trade['sl']:
                        active_trade['status'] = 'WRONG (Loss)'
                        active_trade['exit_time'] = candle.name
                        self.results.append(active_trade)
                        active_trade = None
                        break
                    elif candle['High'] >= active_trade['tp']:
                        active_trade['status'] = 'CORRECT (Win)'
                        active_trade['exit_time'] = candle.name
                        self.results.append(active_trade)
                        active_trade = None
                        break
                if active_trade is None: continue # Trade fechou
                break # Se ainda está aberto, sai do loop do ticker para não abrir novos

            # Detecção de Rompimento 2h (Simplificado conforme scanner.py)
            current_close = current_h2['Close']
            prev_highs_max = h2['High'].iloc[i-11:i].max()
            
            if current_close > prev_highs_max:
                # Encontrar a vela de 4h anterior ao rompimento
                # A vela de 4h que terminou antes do início desta vela de 2h
                h4_before = h4[h4.index < current_time]
                if h4_before.empty: continue
                
                sl = h4_before['Low'].iloc[-1] * 0.998 # Pequeno respiro
                entry = current_close
                risk = entry - sl
                
                if risk > 0 and (risk / entry) < 0.10: # Filtro de risco sanidade (<10%)
                    tp = entry + (risk * 3)
                    
                    active_trade = {
                        'ticker': ticker,
                        'entry_time': current_time,
                        'entry_price': entry,
                        'sl': sl,
                        'tp': tp,
                        'status': 'UNRESOLVED'
                    }
        
        if active_trade:
            self.results.append(active_trade)

    def summary(self):
        if not self.results:
            print("\n❌ Nenhum rompimento detetado com estes critérios.")
            return

        df = pd.DataFrame(self.results)
        total = len(df)
        wins = len(df[df['status'] == 'CORRECT (Win)'])
        losses = len(df[df['status'] == 'WRONG (Loss)'])
        pending = len(df[df['status'] == 'UNRESOLVED'])
        
        win_rate = (wins / (wins + losses)) * 100 if (wins + losses) > 0 else 0
        profit_r = (wins * 3) - losses
        
        print("\n" + "="*45)
        print("📊 RESULTADOS DO BACKTEST: ESTRATÉGIA SNIPER")
        print("="*45)
        print(f"Total de Sinais: {total}")
        print(f"✅ Sinais Certos (Win):  {wins}")
        print(f"❌ Sinais Errados (Loss): {losses}")
        print(f"⏳ Por Resolver:         {pending}")
        print("-" * 25)
        print(f"📈 Taxa de Acerto:      {win_rate:.2f}%")
        print(f"💰 Lucro Líquido (RR):  {profit_r:+.1f}R")
        print("="*45)

if __name__ == "__main__":
    # Universo diversificado para o teste
    test_assets = [
        "NVDA", "AAPL", "MSFT", "TSLA", "AMD", "META", "AMZN", "NFLX", "GOOGL", "AVGO",
        "ASML.AS", "SAP.DE", "MC.PA", "ITX.MC", "EDP.LS", "OR.PA", "AIR.PA", "SIE.DE",
        "PLTR", "MSTR", "UBER", "SHOP", "COIN", "CRWD", "NOW"
    ]
    bt = BreakoutBacktest()
    bt.run(test_assets, days=30)
