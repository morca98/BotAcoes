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
logger = logging.getLogger("BacktestSupport")

class SupportBacktest:
    def __init__(self):
        self.config = Config()
        self.scanner = Scanner(self.config)
        self.results = []

    def run(self, tickers, days=30):
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        print(f"--- 🛡️ BACKTEST DE ZONAS DE COMPRA (Últimos {days} dias) ---")
        print(f"Regra: Toque em Suporte Virgem + Confirmação 15m | RR 1:3")
        print(f"Período: {start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}")
        
        for ticker in tickers:
            try:
                self.test_ticker(ticker, start_date, end_date)
            except Exception as e:
                pass

        self.summary()

    def test_ticker(self, ticker, start_date, end_date):
        tk = yf.Ticker(ticker)
        h15 = tk.history(start=start_date - timedelta(days=5), end=end_date, interval="15m")
        if h15.empty or len(h15) < 50: return
        daily = tk.history(period="2y", interval="1d").dropna()
        if daily.empty: return

        # Pré-calcular suportes para evitar chamadas pesadas no loop
        # Usamos o preço médio do período para pegar suportes relevantes
        avg_price = h15['Close'].mean()
        all_potential_supports = self.scanner.get_key_supports(ticker, avg_price, daily)
        if not all_potential_supports: return

        active_trade = None
        for i in range(20, len(h15)):
            current_candle = h15.iloc[i]
            current_time = h15.index[i]
            
            if active_trade:
                if current_candle['Low'] <= active_trade['sl']:
                    active_trade['status'] = 'WRONG (Loss)'
                    active_trade['exit_time'] = current_time
                    self.results.append(active_trade)
                    active_trade = None
                elif current_candle['High'] >= active_trade['tp']:
                    active_trade['status'] = 'CORRECT (Win)'
                    active_trade['exit_time'] = current_time
                    self.results.append(active_trade)
                    active_trade = None
                continue

            price = current_candle['Close']
            for sup in all_potential_supports:
                # Recalcular distância baseada no preço atual da vela
                sup_price = float(sup['price'].split(' - ')[0]) if ' - ' in sup['price'] else float(sup['price'])
                dist = abs(price - sup_price) / sup_price * 100
                
                if sup['virgin'] and dist <= 0.2:
                    if i + 1 >= len(h15): break
                    next_candle = h15.iloc[i+1]
                    if next_candle['Low'] > current_candle['Low'] and next_candle['High'] > current_candle['High']:
                        entry = next_candle['Close']
                        sl = min(current_candle['Low'], next_candle['Low']) * 0.998
                        risk = entry - sl
                        if risk > 0 and (risk / entry) < 0.05:
                            tp = entry + (risk * 3)
                            active_trade = {
                                'ticker': ticker, 'entry_time': h15.index[i+1],
                                'entry_price': entry, 'sl': sl, 'tp': tp,
                                'sup_type': sup['type'], 'status': 'UNRESOLVED'
                            }
                            break
        
        if active_trade:
            self.results.append(active_trade)

    def summary(self):
        if not self.results:
            print("\n❌ Nenhuma oportunidade de suporte detetada.")
            return

        df = pd.DataFrame(self.results)
        total = len(df)
        wins = len(df[df['status'] == 'CORRECT (Win)'])
        losses = len(df[df['status'] == 'WRONG (Loss)'])
        pending = len(df[df['status'] == 'UNRESOLVED'])
        
        win_rate = (wins / (wins + losses)) * 100 if (wins + losses) > 0 else 0
        profit_r = (wins * 3) - losses
        
        print("\n" + "="*45)
        print("📊 RESULTADOS DO BACKTEST: ZONAS DE COMPRA")
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
    # Reduzido para 10 ativos principais para velocidade
    test_assets = [
        "NVDA", "AAPL", "TSLA", "AMD", "META", 
        "ASML.AS", "SAP.DE", "MC.PA", "ITX.MC", "EDP.LS"
    ]
    bt = SupportBacktest()
    bt.run(test_assets, days=30)
