import logging
import os
import sys
import asyncio
import threading
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import requests
from scanner import MarketScanner
from config import Config

# Logs para o console do Railway
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# --- Configurações ---
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or "8890309916:AAEkC2DPEtuyGJWDbtof-4s6YozCC9bvjGs"
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or "1354621810"
PORT = int(os.getenv("PORT", 8080))

config = Config()
config.TELEGRAM_TOKEN = TOKEN
config.TELEGRAM_CHAT_ID = CHAT_ID
scanner = MarketScanner(config)

# --- Servidor Web (para o Railway não desligar o bot) ---
app = Flask(__name__)

@app.route('/')
def health():
    return "Bot is alive!", 200

def run_flask():
    logger.info(f"Iniciando servidor web na porta {PORT}...")
    app.run(host='0.0.0.0', port=PORT)

# --- Lógica do Telegram ---
async def send_online_notification():
    """Envia notificação inicial via HTTP direto para máxima garantia"""
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": "🟢 *Bot de Ações Ativo no Railway*\nO bot ligou com sucesso e está pronto para receber comandos.",
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
        logger.info("Notificação de 'Online' enviada via HTTP.")
    except Exception as e:
        logger.error(f"Erro ao enviar notificação inicial: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Comando /start recebido")
    await update.message.reply_text("🚀 Bot de Ações Ativo! Use /scan para análise imediata.")

async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Comando /scan recebido")
    await update.message.reply_text("🔍 Analisando mercado... Aguarde.")
    
    signals = []
    # Scan rápido dos primeiros 30 ativos
    for ticker in config.ASSETS[:30]:
        try:
            result = scanner.analyze(ticker)
            if result:
                signals.append(result)
        except:
            continue

    if signals:
        msg = "🎯 *Ações em Ponto de Compra:*\n\n"
        for s in signals:
            msg += f"🔹 *{s['ticker']}* @ ${s['price']}\n"
        await update.message.reply_text(msg, parse_mode="Markdown")
    else:
        await update.message.reply_text("✅ Scan concluído. Nenhuma oportunidade encontrada agora.")

async def main():
    # Iniciar servidor web em thread separada
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Enviar notificação de que ligou
    await send_online_notification()
    
    # Iniciar Bot Telegram
    logger.info("Iniciando Polling do Telegram...")
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('scan', scan))
    
    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    
    # Manter vivo
    while True:
        await asyncio.sleep(3600)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot desligado.")
