import sys
import os
import yfinance as yf
sys.path.append(os.getcwd())
from config import Config
from scanner import Scanner

config = Config()
scanner = Scanner(config)
res = scanner.analyze("AMZN")
print("Resultado AMZN:", res)
