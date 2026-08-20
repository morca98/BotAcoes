import logging
import sys
from config import Config
from scanner import Scanner
import json

# Configurar logging para ver o que se passa
logging.basicConfig(level=logging.INFO)

def test_mu():
    config = Config()
    scanner = Scanner(config)
    ticker = "MU"
    
    print(f"--- Analisando {ticker} ---")
    result = scanner.analyze(ticker)
    
    if result:
        print("\nResultado da Análise:")
        print(json.dumps(result, indent=4))
    else:
        print("\nA análise não retornou resultados (ativo descartado pelos filtros).")

if __name__ == "__main__":
    test_mu()
