import os
from dotenv import load_dotenv

load_dotenv()


def _read_chat_ids() -> frozenset[int]:
    raw = os.getenv("TELEGRAM_AUTHORIZED_CHAT_IDS") or os.getenv("TELEGRAM_CHAT_ID") or ""
    chat_ids = set()
    for value in raw.split(","):
        try:
            if value.strip():
                chat_ids.add(int(value.strip()))
        except ValueError:
            continue
    return frozenset(chat_ids)


class Config:
    # Credenciais apenas pelo ambiente. O nome legado continua compatível.
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
    AUTHORIZED_CHAT_IDS = _read_chat_ids()

    # Filtros de Seleção (Universo)
    MIN_PRICE = 10.0
    MIN_MARKET_CAP = 2_000_000_000

    # Filtros de Eliminação
    MAX_RSI_DAILY = 50.0
    MAX_RSI_4H = 55.0
    MAX_EMA20_DIST_PCT = 8.0
    MIN_ATR_PCT = 2.0
    MIN_ANNUAL_VOL = 0.4
    MAX_SUPPORT_DISTANCE_PCT = 10.0

    # Proteção do fornecedor de dados: mantém o universo amplo, mas analisa os 500 mais líquidos.
    MAX_SCAN_ASSETS = 500
    LIQUIDITY_CHUNK_SIZE = 25

    # Lista de Ativos (S&P 500 / NASDAQ 100 principais)
    ASSETS = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AVGO", "JPM", "V",
        "UNH", "XOM", "LLY", "JNJ", "MA", "PG", "HD", "COST", "MRK", "ABBV",
        "PEP", "KO", "ADBE", "WMT", "BAC", "CRM", "MCD", "ACN", "NFLX", "AMD",
        "QCOM", "TXN", "NEE", "LIN", "ORCL", "HON", "PM", "AMGN", "IBM", "CAT",
        "GE", "SBUX", "BA", "GS", "MS", "BLK", "SPGI", "AXP", "RTX", "DE",
        "ISRG", "ADI", "NOW", "BKNG", "LRCX", "PANW", "SYK", "ADP", "VRTX", "MMC",
        "C", "USB", "WFC", "PFE", "T", "VZ", "CMCSA", "DIS", "INTC", "PYPL",
        "UBER", "SHOP", "SQ", "COIN", "PLTR", "ROKU", "SNOW", "NET", "CRWD", "MSTR",
    ]
