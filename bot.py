import logging
import os
import sys
import asyncio
import threading
from datetime import datetime
import pytz
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import requests

from config import Config
from scanner import Scanner

# Configuração de Logs para o Railway
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    stream=sys.stdout
)
logger = logging.getLogger(__name__)
LISBON_TZ = pytz.timezone("Europe/Lisbon")

# --- Credenciais Globais ---
config = Config()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or config.TELEGRAM_TOKEN
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or config.TELEGRAM_CHAT_ID

# --- Função de Envio Direto (Síncrona) ---
def send_direct_msg(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        r = requests.post(url, json=payload, timeout=10)
        logger.info(f"Envio direto: {r.status_code}")
        return r.status_code == 200
    except Exception as e:
        logger.error(f"Erro no envio direto: {e}")
        return False

# --- Servidor Web para Railway ---
flask_app = Flask(__name__)

@flask_app.route('/')
def health():
    return "Bot is active", 200

def run_flask():
    port = int(os.getenv("PORT", 8080))
    logger.info(f"Servidor web na porta {port}")
    flask_app.run(host='0.0.0.0', port=port)

# --- Scanner e Lógica ---
bot_scanner = Scanner(config)

async def run_market_scan(app_bot=None):
    logger.info("Executando scan de mercado...")
    signals = []
    for ticker in config.ASSETS:
        try:
            res = await asyncio.get_event_loop().run_in_executor(None, bot_scanner.analyze, ticker)
            if res:
                signals.append(res)
        except:
            continue

    now = datetime.now(LISBON_TZ).strftime("%d/%m/%Y %H:%M")
    if signals:
        msg = f"🎯 *Sinais de Compra* — {now}\n━━━━━━━━━━━━━━━━━━━━\n"
        for s in signals:
            msg += (f"🔹 *{s['ticker']}* @ `${s['price']}`\n"
                    f"   RSI D: `{s['rsi_daily']}` | RSI 4H: `{s['rsi_4h']}`\n"
                    f"   ATR%: `{s['atr_pct']}%` | Dist. EMA20: < 8%\n\n")
    else:
        msg = f"🔍 *Scan concluído* — {now}\nNenhuma ação cumpre os critérios no momento."
    
    send_direct_msg(msg)

# --- Handlers ---
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 *Bot de Ações Ativo!*\nUse /scan para análise imediata.")

async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 *A iniciar scan manual...*")
    await run_market_scan()

async def scheduler_loop():
    logger.info("Agendamento iniciado.")
    while True:
        now = datetime.now(LISBON_TZ)
        if now.hour == 8 and now.minute == 0:
            await run_market_scan()
            await asyncio.sleep(65)
        await asyncio.sleep(30)

async def main():
    # 1. Enviar notificação IMEDIATA
    logger.info("Enviando notificação de arranque...")
    send_direct_msg("🟢 *Bot Iniciado com Sucesso!*\nO bot está agora ativo no Railway.")

    # 2. Iniciar Servidor Web em background
    threading.Thread(target=run_flask, daemon=True).start()
    
    # 3. Iniciar Agendamento
    asyncio.create_task(scheduler_loop())
    
    # 4. Iniciar Bot do Telegram
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("scan", cmd_scan))
    
    logger.info("Iniciando Polling...")
    await application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
