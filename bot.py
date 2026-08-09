import logging
import os
import sys
import asyncio
from datetime import datetime
import pytz
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from config import Config
from scanner import Scanner

# Logs para o Railway
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    stream=sys.stdout
)
logger = logging.getLogger(__name__)
LISBON_TZ = pytz.timezone("Europe/Lisbon")

# --- Configurações ---
config = Config()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or config.TELEGRAM_TOKEN
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or config.TELEGRAM_CHAT_ID

def send_direct_msg(text):
    """Método HTTP direto que funcionou no teste"""
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logger.error(f"Erro no envio: {e}")

# --- Comandos ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 *Bot Ativo!* Use /scan para análise.")

async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 *Analisando mercado...*")
    bot_scanner = Scanner(config)
    signals = []
    # Scan rápido dos primeiros 40 ativos
    for ticker in config.ASSETS[:40]:
        try:
            res = await asyncio.get_event_loop().run_in_executor(None, bot_scanner.analyze, ticker)
            if res: signals.append(res)
        except: continue

    now = datetime.now(LISBON_TZ).strftime("%d/%m/%Y %H:%M")
    if signals:
        msg = f"🎯 *Sinais* — {now}\n" + "\n".join([f"🔹 *{s['ticker']}* @ ${s['price']}" for s in signals])
    else:
        msg = f"✅ *Scan concluído* — {now}\nNenhum sinal encontrado."
    send_direct_msg(msg)

async def scheduler():
    """Agendamento simples sem bibliotecas extras"""
    while True:
        now = datetime.now(LISBON_TZ)
        if now.hour == 8 and now.minute == 0:
            bot_scanner = Scanner(config)
            # Rodar scan... (simplificado para o log)
            logger.info("Executando scan agendado...")
            await asyncio.sleep(60)
        await asyncio.sleep(30)

async def main():
    # 1. Notificação imediata (O que funcionou no teste)
    send_direct_msg("🟢 *Bot Iniciado no Railway*")
    
    # 2. Iniciar Polling do Telegram
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("scan", scan))
    
    # Iniciar agendamento em background
    asyncio.create_task(scheduler())
    
    logger.info("Bot em polling...")
    await application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
