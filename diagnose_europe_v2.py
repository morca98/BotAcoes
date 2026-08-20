import sys
import os
import pandas as pd
import numpy as np
import yfinance as yf

sys.path.append(os.getcwd())
from config import Config
from scanner import Scanner

def diagnose():
    config = Config()
    scanner = Scanner(config)
    
    print("--- 🔍 DIAGNÓSTICO DE ATIVOS EUROPEUS ---")
    
    # 1. Verificar se o benchmark europeu está acessível
    print("\n1. Testando Benchmark Europeu (EXSA.DE)...")
    bench_data = scanner._get_sector_etf_data("EXSA.DE")
    if bench_data is not None and not bench_data.empty:
        print(f"   ✅ SUCESSO: {len(bench_data)} dias de dados obtidos.")
    else:
        print("   ❌ FALHA: Não foi possível obter dados do EXSA.DE.")

    # 2. Testar ativos europeus específicos
    test_tickers = ["ASML.AS", "SAP.DE", "MC.PA", "ITX.MC", "EDP.LS"]
    
    for ticker in test_tickers:
        print(f"\nAnalisando {ticker}...")
        try:
            # Teste manual de passos críticos
            tk = yf.Ticker(ticker)
            daily = tk.history(period="2y", interval="1d")
            if daily.empty:
                print(f"   ❌ Erro: Histórico vazio via yfinance.")
                continue
            
            # Verificar Volatilidade
            y_high = daily['High'].iloc[-252:].max()
            y_low = daily['Low'].iloc[-252:].min()
            vol = (y_high - y_low) / y_low
            print(f"   - Volatilidade Anual: {vol:.2%}")
            
            # Verificar RSI
            rsi_series = scanner._rsi(daily['Close'], 14)
            rsi = rsi_series.iloc[-1]
            print(f"   - RSI Diário: {rsi:.2f}")
            
            # Verificar Analyze completo
            res = scanner.analyze(ticker)
            if res:
                print(f"   ✅ PASSOU! Score: {res['stars']}")
            else:
                print(f"   ❌ REJEITADO pelo Analyze.")
                
        except Exception as e:
            print(f"   ⚠️ Erro em {ticker}: {e}")

if __name__ == "__main__":
    diagnose()
