import asyncio
import html

def demo_score():
    ticker = "NVDA"
    current_price = 128.50
    sup_type = "Semanal (01/06) Open"
    sup_price = 127.80
    dist = 0.54
    
    # Simulação de critérios preenchidos (Cenário Ideal 6/6)
    conf_list = ["EMA 200 🎯", "EMA 70 🛡️", "Golden Pocket 📐", "Institucional 🏛️"]
    conf_count = len(conf_list)
    vol_spike = True
    div_bullish = True
    pullback_leadership = True
    
    # Lógica de cálculo implementada no bot
    total_points = conf_count + (1 if vol_spike else 0) + (1 if div_bullish else 0) + (1 if pullback_leadership else 0)
    strength_score = min(6, max(1, total_points))
    strength_bar = "🟢" * strength_score + "⚪" * (6 - strength_score)
    
    vol_msg = "✅ <b>Defesa Institucional (Volume Spike!)</b>" if vol_spike else "⚠️ Sem pico de volume"
    rs_msg = "⚡ <b>Liderança no Pullback (Resiliência Forte)</b>" if pullback_leadership else ""
    conf_msg = f"🌟 <b>Confluência: {' + '.join(conf_list)}</b>" if conf_list else ""
    
    alert = (f"🎯 <b>ZONA DE COMPRA - Suporte Confirmado (30m)!</b>\n"
             f"🔥 <b>{ticker}</b> @ <code>${current_price}</code> encostou em: <b>{sup_type} (${sup_price})</b>\n"
             f"📊 <b>Barra de Força:</b> {strength_bar} ({strength_score}/6)\n"
             f"✅ <b>Confirmação 30m:</b> High/Low Superior\n"
             f"{vol_msg}\n"
             f"{rs_msg}\n"
             f"{conf_msg}\n"
             f"   RS/Setor: <code>1.45</code> | RSI D: <code>42.30</code>")
    
    print("\n--- EXEMPLO DE NOTIFICAÇÃO 6/6 NO TELEGRAM ---")
    print(alert.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", ""))
    print("----------------------------------------------\n")

if __name__ == "__main__":
    demo_score()
