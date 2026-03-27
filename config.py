"""
Configuration for Stock Signal Bot MTF V3
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Telegram
    TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # Risk Management
    CAPITAL: float = float(os.getenv("CAPITAL", "10000"))
    RISK_PERCENT: float = float(os.getenv("RISK_PERCENT", "1.0"))  # 1% per trade
    RR_RATIO: float = 3.0        # Risk:Reward 1:3


    # Strategy Filters
    RSI_WEEKLY_MAX: float = 50.0     # Weekly RSI < 50
    SMA_DAILY_PERIOD: int = 70       # Price > SMA70 daily
    RSI_4H_OVERSOLD: float = 40.0    # 4H RSI < 40 (pullback)
    MACD_FAST: int = 12
    MACD_SLOW: int = 26
    MACD_SIGNAL: int = 9
    RSI_PERIOD: int = 14

    # Confidence weights
    CONFIDENCE_WEIGHTS = {
        "rsi_weekly": 20,
        "sma_daily": 20,
        "rsi_4h": 20,
        "macd_divergence": 25,
        "candle_confirmation": 15,
    }

    # Assets: Loaded dynamically via AssetsManager
    _DEFAULT_ASSETS = [
        # === USA - S&P 500 Large Caps ===
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B",
        "JPM", "V", "UNH", "XOM", "LLY", "JNJ", "MA", "PG", "AVGO", "HD",
        "CVX", "MRK", "ABBV", "PEP", "KO", "COST", "ADBE", "WMT", "BAC",
        "CRM", "MCD", "ACN", "NFLX", "AMD", "QCOM", "TXN", "NEE", "LIN",
        "ORCL", "HON", "PM", "AMGN", "IBM", "CAT", "GE", "SBUX", "BA",
        "GS", "MS", "BLK", "SPGI", "AXP", "RTX", "DE", "ISRG", "ADI",
        "NOW", "BKNG", "LRCX", "PANW", "SYK", "ADP", "VRTX", "MMC",
        "C", "USB", "WFC", "PFE", "T", "VZ", "CMCSA", "DIS",
        # === USA - ETFs ===
        "SPY", "QQQ", "IWM", "DIA", "GLD", "SLV", "TLT", "XLF",
        "XLE", "XLK", "XLV", "ARKK",
        # === Portugal - Euronext Lisbon ===
        "EDP.LS", "EDPR.LS", "GALP.LS", "BCP.LS", "NOS.LS", "JMT.LS",
        "SON.LS", "CTT.LS", "ALTR.LS", "REN.LS", "MOTA.LS", "PHR.LS",
        # === Europe - Major Indices & Stocks ===
        "ASML", "SAP", "NOVO-B.CO", "MC.PA", "OR.PA", "SIE.DE", "ALV.DE",
        "BAS.DE", "BMW.DE", "VOW3.DE", "BAYN.DE", "MUV2.DE", "DTE.DE",
        "ADS.DE", "RWE.DE", "DBK.DE", "ENEL.MI", "ENI.MI", "ISP.MI",
        "UCG.MI", "TIT.MI", "SAN.MC", "BBVA.MC", "ITX.MC", "IBE.MC",
        "REP.MC", "AI.PA", "BN.PA", "SU.PA", "CAP.PA", "FP.PA",
        "AZN.L", "SHEL.L", "HSBA.L", "BP.L", "GSK.L", "ULVR.L",
        "NESN.SW", "ROG.SW", "NOVN.SW", "UBS",
        # === Brazil - B3 ===
        "PETR4.SA", "VALE3.SA", "ITUB4.SA", "BBDC4.SA", "ABEV3.SA",
        "B3SA3.SA", "WEGE3.SA", "RENT3.SA", "MGLU3.SA", "LREN3.SA",
        "BBAS3.SA", "RADL3.SA", "JBSS3.SA", "GGBR4.SA", "SUZB3.SA",
        "BRFS3.SA", "CSAN3.SA", "HAPV3.SA", "RDOR3.SA", "EMBR3.SA",
        # === Global Crypto ETFs & Commodities ===
        "BITO", "GDX", "GDXJ", "USO", "UNG",
    ]

    def __init__(self):
        from assets_manager import AssetsManager
        self.assets_manager = AssetsManager(default_assets=self._DEFAULT_ASSETS)

    @property
    def ASSETS(self):
        return self.assets_manager.get_assets()

    @property
    def risk_amount(self) -> float:
        return self.CAPITAL * (self.RISK_PERCENT / 100)
