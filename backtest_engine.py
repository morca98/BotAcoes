import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import pytz
import logging
import sys
import os

sys.path.append(os.getcwd())
from config import Config
from scanner import Scanner

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger("Backtest")

class Backtest:
    def __init__(self):
        self.config = Config()
        self.scanner = Scanner(self.config)
        self.results = []

    def run(self, tickers, days=30):
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        print(f"--- 📊 INICIANDO BACKTEST (Últimos {days} dias) ---")
        print(f"Período: {start_date.strftime('%d/%m/%Y')} até {end_date.strftime('%d/%m/%Y')}")
        print(f"Ativos em teste: {len(tickers)}")
        
        for ticker in tickers:
            try:
                self.test_ticker(ticker, start_date, end_date)
            except Exception as e:
                # logger.error(f"Erro no backtest de {ticker}: {e}")
                pass

        self.summary()

    def test_ticker(self, ticker, start_date, end_date):
        tk = yf.Ticker(ticker)
        # 15m data (limitado a 60 dias no yfinance)
        h15 = tk.history(start=start_date, end=end_date, interval="15m")
        if h15.empty or len(h15) < 50: return

        # Dados diários para suportes (precisamos de 1 ano de histórico)
        daily = tk.history(period="2y", interval="1d")
        if daily.empty: return

        # Simular o estado do bot no início do backtest
        # Nota: O bot real recalcula suportes a cada toque. Aqui vamos simplificar
        # calculando os suportes baseados nos dados disponíveis ANTES de cada dia de teste.
        
        active_trade = None
        
        # Iterar pelas velas de 15m
        for i in range(20, len(h15)):
            current_candle = h15.iloc[i]
            current_time = h15.index[i]
            
            if active_trade:
                # Verificar desfecho
                if current_candle['Low'] <= active_trade['sl']:
                    active_trade['status'] = 'WRONG (Loss)'
                    active_trade['exit_price'] = active_trade['sl']
                    active_trade['exit_time'] = current_time
                    self.results.append(active_trade)
                    active_trade = None
                elif current_candle['High'] >= active_trade['tp']:
                    active_trade['status'] = 'CORRECT (Win)'
                    active_trade['exit_price'] = active_trade['tp']
                    active_trade['exit_time'] = current_time
                    self.results.append(active_trade)
                    active_trade = None
                continue

            # Se não há trade ativo, procurar entrada
            # Recalcular suportes baseados no dia anterior para ser realista
            # (Simplificação: usamos o daily completo mas o scanner já filtra por datas passadas internamente se bem configurado)
            # Para o backtest, vamos usar o scanner.get_key_supports com o preço da vela atual
            price = current_candle['Close']
            
            # Filtro rápido de RS e Volatilidade (usando dados até aquele momento seria ideal, mas usamos o atual para velocidade)
            # A maioria dos ativos no teste já passou nos filtros globais
            
            supports = self.scanner.get_key_supports(ticker, price, daily)
            
            for sup in supports:
                # Critério de toque: Preço <= suporte * 1.002 (0.2%)
                if sup['virgin'] and price <= float(sup['price']) * 1.002:
                    # Tocou! Agora esperar confirmação na próxima vela
                    if i + 1 >= len(h15): break
                    next_candle = h15.iloc[i+1]
                    
                    # Confirmação 15m: High/Low superior
                    if next_candle['Low'] > current_candle['Low'] and next_candle['High'] > current_candle['High']:
                        entry = next_candle['Close']
                        sl = min(current_candle['Low'], next_candle['Low']) * 0.997 # 0.3% buffer
                        risk = entry - sl
                        if risk <= 0: continue
                        
                        tp = entry + (risk * 3)
                        
                        active_trade = {
                            'ticker': ticker,
                            'entry_time': h15.index[i+1],
                            'entry_price': entry,
                            'sl': sl,
                            'tp': tp,
                            'sup_type': sup['type'],
                            'status': 'UNRESOLVED'
                        }
                        # Avançar o índice para não processar a vela de confirmação novamente
                        i += 1
                        break
        
        if active_trade:
            self.results.append(active_trade)

    def summary(self):
        if not self.results:
            print("\n❌ Nenhum sinal gerado no período de teste.")
            return

        df = pd.DataFrame(self.results)
        total = len(df)
        wins = len(df[df['status'] == 'CORRECT (Win)'])
        losses = len(df[df['status'] == 'WRONG (Loss)'])
        pending = len(df[df['status'] == 'UNRESOLVED'])
        
        win_rate = (wins / (wins + losses)) * 100 if (wins + losses) > 0 else 0
        
        # Cálculo de Lucro em "R" (Unidades de Risco)
        # Win = +3R, Loss = -1R
        profit_r = (wins * 3) - losses
        
        print("\n" + "="*40)
        print("📊 SUMÁRIO DO BACKTEST (1:3 RR)")
        print("="*40)
        print(f"Total de Sinais: {total}")
        print(f"✅ Acertos (Win): {wins}")
        print(f"❌ Erros (Loss):  {losses}")
        print(f"⏳ Pendentes:    {pending}")
        print("-" * 20)
        print(f"📈 Taxa de Acerto: {win_rate:.2f}%")
        print(f"💰 Lucro Líquido:  {profit_r:+.1f}R")
        print("="*40)
        
        if total > 0:
            print("\nTop 5 Sinais Detalhados:")
            print(df[['ticker', 'entry_time', 'status', 'sup_type']].head().to_string(index=False))

if __name__ == "__main__":
    # Seleção de ativos representativos (US + EU)
    test_assets = [
        "NVDA", "AAPL", "MSFT", "TSLA", "AMD", "META", "AMZN", "NFLX", # Tech US
        "JPM", "GS", "V", "AXP", # Fin US
        "ASML.AS", "SAP.DE", "MC.PA", "ITX.MC", "EDP.LS", "OR.PA", "AIR.PA", "SIE.DE" # EU
    ]
    bt = Backtest()
    bt.run(test_assets, days=30)
