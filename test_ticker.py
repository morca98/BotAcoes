import asyncio
import sys
from scanner import Scanner
from config import Config

async def test_single_ticker(ticker):
    config = Config()
    scanner = Scanner(config)
    
    print(f"--- Analisando {ticker} ---")
    res = scanner.analyze(ticker)
    
    if res:
        print(f"✅ O ativo PASSOU nos filtros!")
        print(f"Preço: ${res['price']}")
        print(f"RS/Setor ({res['sector_etf']}): {res['rs_sector']}")
        print(f"Rompimento 2h: {'SIM 🚀' if res['breakout_2h'] else 'Não'}")
        print(f"Divergência 4h: {'SIM ✅' if res['div_bullish'] else 'Não'}")
        print(f"VCP: {'SIM ✅' if res['is_vcp'] else 'Não'}")
        print(f"RSI Diário: {res['rsi_daily']}")
    else:
        print(f"❌ O ativo FOI EXCLUÍDO pelos filtros.")
        print("Motivos possíveis: RS/Setor < 1, RSI > 50, ou tendência de baixa (abaixo da EMA 200).")

if __name__ == "__main__":
    ticker = sys.argv[1] if len(sys.argv) > 1 else "NVDA"
    asyncio.run(test_single_ticker(ticker))
