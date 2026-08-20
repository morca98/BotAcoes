import json
import os

def map_tickers():
    stoxx_file = '/home/ubuntu/BotAcoes/stoxx600_tickers.json'
    if not os.path.exists(stoxx_file):
        print("Ficheiro STOXX não encontrado.")
        return

    with open(stoxx_file, 'r') as f:
        tickers = json.load(f)

    # Mapeamento de sufixos Yahoo -> Alpha Vantage
    # Yahoo: .AS (Amsterdam), .DE (Xetra), .PA (Paris), .MI (Milan), .MC (Madrid), .LS (Lisbon), .BR (Brussels), .HE (Helsinki), .OL (Oslo), .ST (Stockholm), .CO (Copenhagen), .SW (Swiss), .L (London)
    # AV: .AMS, .DEX, .PAR, .MIL, .MAD, .LIS, .BRU, .HEL, .OSL, .STO, .CPH, .SWI, .LON
    
    mapping = {
        ".AS": ".AMS",
        ".DE": ".DEX",
        ".PA": ".PAR",
        ".MI": ".MIL",
        ".MC": ".MAD",
        ".LS": ".LIS",
        ".BR": ".BRU",
        ".HE": ".HEL",
        ".OL": ".OSL",
        ".ST": ".STO",
        ".CO": ".CPH",
        ".SW": ".SWI",
        ".L": ".LON",
        ".AT": ".ATH",
        ".VI": ".VIE",
        ".PR": ".PRG"
    }

    av_tickers = {}
    for ticker in tickers:
        av_ticker = ticker
        for y_suf, av_suf in mapping.items():
            if ticker.endswith(y_suf):
                av_ticker = ticker.replace(y_suf, av_suf)
                break
        av_tickers[ticker] = av_ticker

    with open('/home/ubuntu/BotAcoes/ticker_mapping_av.json', 'w') as f:
        json.dump(av_tickers, f, indent=4)
    
    print(f"Mapeamento concluído. {len(av_tickers)} tickers processados.")

if __name__ == "__main__":
    map_tickers()
