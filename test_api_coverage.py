import requests
import time

# Nota: O utilizador precisará de colocar as suas próprias chaves. 
# Para o teste, vamos apenas verificar a estrutura e se os tickers europeus são reconhecidos.

TICKERS_US = ["AAPL", "NVDA", "TSLA"]
TICKERS_EU = ["ASML.AS", "SAP.DE", "MC.PA"] # Formato Yahoo
TICKERS_EU_AV = ["ASML.AMS", "SAP.DEX", "MC.PAR"] # Formato provável Alpha Vantage

def test_alpha_vantage_search(symbol):
    # Endpoint de busca para ver como eles tratam tickers europeus
    url = f"https://www.alphavantage.co/query?function=SYMBOL_SEARCH&keywords={symbol}&apikey=demo"
    try:
        r = requests.get(url)
        data = r.json()
        print(f"Alpha Vantage Search for {symbol}: {data.get('bestMatches', [])[:2]}")
    except Exception as e:
        print(f"Error AV: {e}")

def test_finnhub_search(symbol):
    # Finnhub Symbol Search
    url = f"https://finnhub.io/api/v1/search?q={symbol}&token=sandbox_c8mthq2ad3i9m7ed9aag" # Token de sandbox se disponível ou dummy
    try:
        r = requests.get(url)
        data = r.json()
        print(f"Finnhub Search for {symbol}: {data.get('result', [])[:2]}")
    except Exception as e:
        print(f"Error Finnhub: {e}")

if __name__ == "__main__":
    print("Testando reconhecimento de tickers...")
    for t in ["ASML", "SAP", "LVMH"]:
        test_alpha_vantage_search(t)
        # test_finnhub_search(t)
        time.sleep(1)
