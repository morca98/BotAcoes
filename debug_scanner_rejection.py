import sys
import os
import pandas as pd
import numpy as np

sys.path.append(os.getcwd())
from config import Config
from scanner import Scanner

def debug_scan():
    config = Config()
    scanner = Scanner(config)
    
    test_tickers = ["NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "AMD", "PLTR", "GS"]
    
    print("--- 🔍 DEBUG DETALHADO DE ATIVOS ---")
    for ticker in test_tickers:
        print(f"\nTestando {ticker}...")
        try:
            tk = yf_ticker = ticker
            import yfinance as yf
            tk_obj = yf.Ticker(ticker)
            daily = tk_obj.history(period="2y", interval="1d")
            if daily is None or len(daily) < 50:
                print(f"  -> Rejeitado: Histórico diário insuficiente ({len(daily) if daily is not None else 0})")
                continue
            
            # Verificar Volatilidade Anual
            year_data = daily.iloc[-252:]
            y_high = year_data['High'].max()
            y_low = year_data['Low'].min()
            annual_vol = (y_high - y_low) / y_low
            print(f"  - Volatilidade Anual: {annual_vol:.2%}")
            if annual_vol < config.MIN_ANNUAL_VOL:
                print(f"    ❌ Reprovado na Volatilidade (< 40%)")
                
            # RSI Diário
            delta = daily["Close"].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            curr_rsi = rsi.iloc[-1]
            print(f"  - RSI Diário: {curr_rsi:.2f}")
            if curr_rsi >= config.MAX_RSI_DAILY:
                print(f"    ❌ Reprovado no RSI Diário (>= 50)")

            # EMA 200
            ema200 = daily["Close"].ewm(span=200, adjust=False).mean().iloc[-1]
            curr_price = daily["Close"].iloc[-1]
            print(f"  - Preço: {curr_price:.2f} | EMA 200: {ema200:.2f}")
            if curr_price < ema200:
                print(f"    ❌ Reprovado: Preço abaixo da EMA 200")

            res = scanner.analyze(ticker)
            if res:
                print(f"  ✅ PASSOU NO ANALYZE COMPLETO! Estrelas: {res.get('stars')}")
            else:
                print(f"  ❌ ANALYZE RETORNOU NONE")
        except Exception as e:
            print(f"  ⚠️ ERRO: {e}")

if __name__ == "__main__":
    debug_scan()
