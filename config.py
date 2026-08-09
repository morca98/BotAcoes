"""
Configuration for Stock Signal Bot
"""

import os
from dotenv import load_dotenv

# Carrega o .env se existir (útil para desenvolvimento local)
load_dotenv()


class Config:
    # Telegram - Usando as chaves exatas da imagem do Railway
    TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID")

    # Filtros de Universo (Volume e Capitalização)
    MIN_AVG_VOLUME: int = 1_000_000         # Volume médio > 1 milhão de ações/dia
    MIN_DOLLAR_VOLUME: float = 20_000_000   # Volume em dólares > 20 milhões USD
    MIN_PRICE: float = 10.0                 # Preço > 10 USD
    MIN_MARKET_CAP: float = 2_000_000_000   # Capitalização > 2 B USD

    # Critérios Técnicos de Eliminação
    RSI_DAILY_MAX: float = 70.0
    RSI_4H_MAX: float = 60.0
    EMA20_MAX_DISTANCE_PCT: float = 8.0  # Eliminar se preço estiver a mais de 8% acima da EMA20
    ATR_MIN_PCT: float = 2.0             # Eliminar se ATR% < 2%

    @property
    def ASSETS(self):
        # Lista dinâmica de ações líquidas do S&P 500 / NASDAQ 100 para escanear
        return [
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AVGO", "JPM", "V",
            "UNH", "XOM", "LLY", "JNJ", "MA", "PG", "HD", "COST", "MRK", "ABBV",
            "PEP", "KO", "ADBE", "WMT", "BAC", "CRM", "MCD", "ACN", "NFLX", "AMD",
            "QCOM", "TXN", "NEE", "LIN", "ORCL", "HON", "PM", "AMGN", "IBM", "CAT",
            "GE", "SBUX", "BA", "GS", "MS", "BLK", "SPGI", "AXP", "RTX", "DE",
            "ISRG", "ADI", "NOW", "BKNG", "LRCX", "PANW", "SYK", "ADP", "VRTX", "MMC",
            "C", "USB", "WFC", "PFE", "T", "VZ", "CMCSA", "DIS", "INTC", "PYPL", 
            "UBER", "SHOP", "SQ", "COIN", "PLTR", "ROKU", "SNOW", "NET", "CRWD"
        ]
