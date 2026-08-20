import requests
import pandas as pd
import yfinance as yf
import os
import json
import time
import logging

logger = logging.getLogger("data_provider")

class DataProvider:
    def __init__(self):
        # Chave Alpha Vantage padrão ou do ambiente (se disponível)
        self.av_keys = [os.environ.get("ALPHA_VANTAGE_KEY", "demo")]
        self.key_index = 0
        self.mapping_file = '/home/ubuntu/BotAcoes/ticker_mapping_av.json'
        self.av_mapping = {}
        if os.path.exists(self.mapping_file):
            with open(self.mapping_file, 'r') as f:
                self.av_mapping = json.load(f)

    def get_current_key(self):
        return self.av_keys[self.key_index]

    def rotate_key(self):
        self.key_index = (self.key_index + 1) % len(self.av_keys)
        logger.info(f"A rotacionar para a chave Alpha Vantage índice {self.key_index}")

    def fetch_daily(self, ticker):
        """
        Tenta buscar dados diários via Alpha Vantage. Se falhar ou atingir limite, faz fallback para yfinance.
        """
        # 1. Tentar Alpha Vantage (se tivermos chave válida)
        av_ticker = self.av_mapping.get(ticker, ticker)
        url = f"https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol={av_ticker}&outputsize=compact&apikey={self.get_current_key()}"
        
        try:
            r = requests.get(url, timeout=10)
            data = r.json()
            
            if "Time Series (Daily)" in data:
                ts = data["Time Series (Daily)"]
                df = pd.DataFrame.from_dict(ts, orient='index')
                df = df.rename(columns={
                    '1. open': 'Open',
                    '2. high': 'High',
                    '3. low': 'Low',
                    '4. close': 'Close',
                    '5. volume': 'Volume'
                })
                df = df.astype(float)
                df.index = pd.to_datetime(df.index)
                df = df.sort_index()
                return df
                
            elif "Note" in data or "Information" in data:
                # Rate limit atingido
                self.rotate_key()
        except Exception as e:
            logger.warning(f"Erro Alpha Vantage para {ticker}: {e}")

        # 2. Fallback para yfinance (robusto e testado)
        try:
            df = yf.download(ticker, period="1y", interval="1d", progress=False)
            if not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.droplevel(1)
                df = df.dropna(subset=['Close'])
                return df
        except Exception as e:
            logger.warning(f"Erro yfinance fallback para {ticker}: {e}")

        return pd.DataFrame()

    def fetch_intraday(self, ticker, interval="60min"):
        """
        Busca dados intraday com fallback para yfinance.
        """
        try:
            df = yf.download(ticker, period="60d", interval=interval, progress=False)
            if not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.droplevel(1)
                df = df.dropna(subset=['Close'])
                return df
        except Exception as e:
            logger.warning(f"Erro intraday yfinance para {ticker}: {e}")
        return pd.DataFrame()
