import sys
import os
import yfinance as yf
import pandas as pd
import numpy as np

sys.path.append(os.getcwd())
from config import Config
from scanner import Scanner

config = Config()
scanner = Scanner(config)

ticker = "AMZN"
tk = yf.Ticker(ticker)
daily = tk.history(period="2y", interval="1d").dropna(subset=['Close', 'High', 'Low', 'Open'])
h1 = tk.history(period="30d", interval="60m").dropna(subset=['Close'])

# RS vs SPY
spy = yf.Ticker("SPY").history(period="2y", interval="1d").dropna(subset=['Close'])
ticker_close = daily['Close'].copy()
sector_close = spy['Close'].copy()
if getattr(ticker_close.index, 'tz', None) is not None: ticker_close.index = ticker_close.index.tz_localize(None)
if getattr(sector_close.index, 'tz', None) is not None: sector_close.index = sector_close.index.tz_localize(None)
combined = pd.DataFrame({'ticker': ticker_close, 'sector': sector_close}).dropna()
ticker_perf = combined['ticker'].iloc[-1] / combined['ticker'].iloc[-252]
sector_perf = combined['sector'].iloc[-1] / combined['sector'].iloc[-252]
rs = ticker_perf / sector_perf
print("RS vs SPY:", rs)

# RSI 4h
rsi_h1_series = scanner._rsi(h1["Close"], 14)
print("RSI 4h (H1):", rsi_h1_series.iloc[-1])

# ATR%
atr_series = scanner._atr(daily, 14)
atr_pct = (atr_series.iloc[-1] / daily["Close"].iloc[-1]) * 100
print("ATR%:", atr_pct)
