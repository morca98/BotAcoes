import logging
import os
import sys
import time
import requests
import asyncio
from telegram.ext import ApplicationBuilder, CommandHandler

# Configuração de logs para aparecerem IMEDIATAMENTE no Railway
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# Credenciais
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or "8890309916:AAEkC2DPEtuyGJWDbtof-4s6YozCC9bvjGs"
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or "1354621810"

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=10)
        logger.info(f"Envio Telegram: {r.status_code} - {r.text}")
    except Exception as e:
        logger.error(f"Falha ao enviar Telegram: {e}")

async def start(update, context):
    await update.message.reply_text("✅ Bot Online e a responder!")

async def main():
    logger.info("=== INICIANDO BOT (VERSÃO DIAGNÓSTICO) ===")
    
    # Notificação inicial (O que funcionou no teste manual)
    send_telegram("🚀 *Bot a tentar ligar no Railway...*")
    
    try:
        application = ApplicationBuilder().token(TOKEN).build()
        application.add_handler(CommandHandler("start", start))
        
        await application.initialize()
        await application.start()
        
        send_telegram("🟢 *Bot em Polling!* Se recebeu isto, o polling está ativo.")
        
        logger.info("Iniciando polling...")
        await application.updater.start_polling(drop_pending_updates=True)
        
        # Loop infinito para o Railway não matar o processo
        while True:
            logger.info("Bot vivo... aguardando comandos.")
            await asyncio.sleep(60)
            
    except Exception as e:
        logger.error(f"ERRO CRÍTICO NO MAIN: {e}")
        send_telegram(f"❌ *Erro Crítico:* {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())
