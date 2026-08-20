import requests
import time

# A Alpha Vantage usa sufixos como .AMS, .DEX, .PAR, etc.
# Vamos tentar buscar tickers específicos com a chave demo (que funciona para alguns tickers como IBM)
# mas aqui queremos ver se a busca funciona para keywords.

def test_search(keyword):
    url = f"https://www.alphavantage.co/query?function=SYMBOL_SEARCH&keywords={keyword}&apikey=demo"
    r = requests.get(url)
    print(f"Search '{keyword}': {r.json()}")

if __name__ == "__main__":
    test_search("ASML")
    time.sleep(1)
    test_search("SAP")
    time.sleep(1)
    test_search("Adidas")
