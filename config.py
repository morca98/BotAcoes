import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Telegram (Railway env vars)
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8890309916:AAEkC2DPEtuyGJWDbtof-4s6YozCC9bvjGs")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1354621810")
    
    # Filtros de Seleção (Universo)
    MIN_PRICE = 10.0                   # > 10 USD
    MIN_MARKET_CAP = 2_000_000_000     # > 2B USD
    
    # Filtros de Eliminação
    MAX_RSI_DAILY = 50.0               # Eliminar se RSI Diário > 50
    MAX_RSI_4H = 50.0                  # Eliminar se RSI 4H > 50
    MAX_EMA20_DIST_PCT = 8.0           # Eliminar se Preço > EMA20 + 8%
    MIN_ATR_PCT = 2.0                  # Eliminar se ATR% < 2%
    MIN_ANNUAL_VOL = 0.5               # Eliminar se Volatilidade Anual < 50%
    
    # Lista de Ativos (S&P 500 / NASDAQ 100 principais)
    ASSETS = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AVGO", "JPM", "V",
        "UNH", "XOM", "LLY", "JNJ", "MA", "PG", "HD", "COST", "MRK", "ABBV",
        "PEP", "KO", "ADBE", "WMT", "BAC", "CRM", "MCD", "ACN", "NFLX", "AMD",
        "QCOM", "TXN", "NEE", "LIN", "ORCL", "HON", "PM", "AMGN", "IBM", "CAT",
        "GE", "SBUX", "BA", "GS", "MS", "BLK", "SPGI", "AXP", "RTX", "DE",
        "ISRG", "ADI", "NOW", "BKNG", "LRCX", "PANW", "SYK", "ADP", "VRTX", "MMC",
        "C", "USB", "WFC", "PFE", "T", "VZ", "CMCSA", "DIS", "INTC", "PYPL",
        "UBER", "SHOP", "SQ", "COIN", "PLTR", "ROKU", "SNOW", "NET", "CRWD", "MSTR"
    ]
