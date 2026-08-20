import asyncio
import logging
import sys
import os
import pandas as pd
import numpy as np
import yfinance as yf

sys.path.append(os.getcwd())

from config import Config
from scanner import Scanner

logging.basicConfig(level=logging.INFO)

async def test_strength_calculation():
    config = Config()
    scanner = Scanner(config)
    
    ticker = "NVDA"
    print(f"\n--- 🧪 TESTE PRÁTICO: BARRA DE FORÇA 6 PONTOS ({ticker}) ---")
    
    tk = yf.Ticker(ticker)
    # Obter dados diários e horários
    daily = tk.history(period="2y", interval="1d").dropna()
    h1 = tk.history(period="5d", interval="60m").dropna()
    
    if daily.empty or h1.empty:
        print("❌ Falha ao obter dados para o teste.")
        return

    current_price = float(daily['Close'].iloc[-1])
    
    # 1. Simular cálculo de suportes e confluências
    print(f"\n1. Verificando Confluências Técnicas no Suporte:")
    supports = scanner.get_key_supports(ticker, current_price, daily)
    
    # Vamos pegar no suporte mais próximo para o teste
    if not supports:
        print("⚠️ Nenhum suporte próximo encontrado. Usando simulação para demonstração.")
        test_sup = {
            'conf_ema200': True, 'conf_ema70': True, 
            'conf_fib': True, 'conf_avwap': True,
            'type': 'Simulado', 'price': current_price * 0.99, 'dist': 1.0
        }
    else:
        test_sup = supports[0]
        
    conf_count = 0
    if test_sup.get('conf_ema200'): conf_count += 1
    if test_sup.get('conf_ema70'): conf_count += 1
    if test_sup.get('conf_fib'): conf_count += 1
    if test_sup.get('conf_avwap'): conf_count += 1
    
    print(f"   - EMA 200: {'✅' if test_sup.get('conf_ema200') else '❌'}")
    print(f"   - EMA 70: {'✅' if test_sup.get('conf_ema70') else '❌'}")
    print(f"   - Fibonacci GP: {'✅' if test_sup.get('conf_fib') else '❌'}")
    print(f"   - Anchored VWAP: {'✅' if test_sup.get('conf_avwap') else '❌'}")
    print(f"   > Total Confluências: {conf_count}")

    # 2. Simular Volume Spike e Divergência
    print(f"\n2. Verificando Sinais de Confirmação:")
    # Para o teste, vamos verificar os dados reais
    vol_spike = True # Simulado para o teste prático
    div_bullish = scanner._check_divergence(h1['Close'], scanner._rsi(h1['Close'], 14))
    
    print(f"   - Volume Spike (Institucional): {'✅ (Simulado)' if vol_spike else '❌'}")
    print(f"   - Divergência Bullish (RSI/MACD): {'✅' if div_bullish else '❌'}")

    # 3. Testar o NOVO Critério: Liderança no Pullback (RS Momentum)
    print(f"\n3. Verificando RS Momentum (6º Ponto):")
    bench_symbol = "SPY"
    bench_h1 = yf.Ticker(bench_symbol).history(period="5d", interval="60m").dropna()
    
    pullback_leadership = scanner._check_pullback_leadership(h1, bench_h1)
    print(f"   - Liderança no Pullback: {'✅' if pullback_leadership else '❌'}")
    
    if not pullback_leadership:
        # Explicar o porquê
        asset_drawdown = (h1['Close'].iloc[-1] - h1['High'].max()) / h1['High'].max()
        bench_drawdown = (bench_h1['Close'].iloc[-1] - bench_h1['High'].max()) / bench_h1['High'].max()
        print(f"     (Ativo DD: {asset_drawdown:.2%}, Benchmark DD: {bench_drawdown:.2%})")

    # 4. Cálculo Final da Barra de Força
    total_points = conf_count + (1 if vol_spike else 0) + (1 if div_bullish else 0) + (1 if pullback_leadership else 0)
    strength_score = min(6, max(1, total_points))
    strength_bar = "🟢" * strength_score + "⚪" * (6 - strength_score)
    
    print(f"\n--- RESULTADO FINAL ---")
    print(f"📊 BARRA DE FORÇA: {strength_bar} ({strength_score}/6)")
    print(f"Score Total Calculado: {total_points}")
    print(f"------------------------\n")

if __name__ == "__main__":
    asyncio.run(test_strength_calculation())
