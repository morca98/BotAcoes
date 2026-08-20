import asyncio
import logging
import sys
import os

sys.path.append(os.getcwd())

from config import Config
from scanner import Scanner
import pandas as pd
import yfinance as yf
import numpy as np

# Aumentar nível de log para ver os DEBUG do scanner
logging.basicConfig(level=logging.DEBUG)

async def main():
    config = Config()
    scanner = Scanner(config)
    
    test_tickers = ["ASML.AS", "SAP.DE", "MC.PA", "ITX.MC", "EDP.LS"]
    print(f"\n--- Diagnóstico Detalhado V3 ---")
    
    for ticker in test_tickers:
        print(f"\n>>> Analisando {ticker}")
        try:
            res = scanner.analyze(ticker)
            if res:
                print(f"✅ Scanner.analyze: APROVADO! Estrelas: {res['stars']}")
            else:
                print(f"❌ Scanner.analyze: REPROVADO.")
        except Exception as e:
            print(f"💥 Erro: {e}")

if __name__ == "__main__":
    asyncio.run(main())
