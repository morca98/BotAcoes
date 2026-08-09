import logging
import os
import sys

# Configuração de logs imediata
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

def critical_log(msg):
    print(f"CRITICAL_DIAG: {msg}", flush=True)
    logger.error(msg)

try:
    critical_log("Iniciando carregamento de módulos...")
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
    critical_log("Módulos carregados com sucesso.")
except Exception as e:
    critical_log(f"FALHA NO CARREGAMENTO DE MÓDULOS: {e}")
    sys.exit(1)

# --- Servidor Web Minimalista ---
flask_app = Flask(__name__)
@flask_app.route('/')
def health(): return "OK", 200

def run_flask():
    port = int(os.getenv("PORT", 8080))
    critical_log(f"Iniciando Flask na porta {port}")
    flask_app.run(host='0.0.0.0', port=port)

# --- Bot ---
async def main():
    try:
        critical_log("Configurando Bot...")
        config = Config()
        token = os.getenv("TELEGRAM_BOT_TOKEN") or config.TELEGRAM_TOKEN
        chat_id = os.getenv("TELEGRAM_CHAT_ID") or config.TELEGRAM_CHAT_ID
        
        # Envio de teste imediato via HTTP
        critical_log("Enviando sinal de vida inicial...")
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", 
                      json={"chat_id": chat_id, "text": "🚀 *Bot a tentar arrancar no Railway...*", "parse_mode": "Markdown"}, 
                      timeout=10)

        # Iniciar Flask em thread
        threading.Thread(target=run_flask, daemon=True).start()

        # Iniciar Telegram
        application = ApplicationBuilder().token(token).build()
        application.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text("Bot Online!")))
        
        critical_log("Iniciando Polling...")
        await application.initialize()
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)
        
        while True:
            await asyncio.sleep(3600)
            
    except Exception as e:
        critical_log(f"ERRO DURANTE EXECUÇÃO: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
