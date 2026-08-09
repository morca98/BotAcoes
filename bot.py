import logging
import os
import sys
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from scanner import MarketScanner
from config import Config

# Logs para o console do Railway
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# Configurações
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or "8890309916:AAEkC2DPEtuyGJWDbtof-4s6YozCC9bvjGs"
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or "1354621810"

config = Config()
config.TELEGRAM_TOKEN = TOKEN
config.TELEGRAM_CHAT_ID = CHAT_ID
scanner = MarketScanner(config)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start"""
    logger.info("Comando /start recebido")
    await update.message.reply_text("🚀 Bot de Ações Ativo! Use /scan para analisar o mercado.")

async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /scan"""
    logger.info("Comando /scan recebido")
    await update.message.reply_text("🔍 Iniciando análise técnica... Aguarde um momento.")
    
    signals = []
    # Analisar apenas os primeiros 20 ativos para garantir resposta rápida no teste
    assets_to_scan = config.ASSETS[:20]
    
    for ticker in assets_to_scan:
        try:
            result = scanner.analyze(ticker)
            if result:
                signals.append(result)
        except Exception as e:
            logger.error(f"Erro em {ticker}: {e}")

    if signals:
        msg = "🎯 *Ações em Ponto de Compra:*\n\n"
        for s in signals:
            msg += f"🔹 *{s['ticker']}* @ ${s['price']}\n"
        await update.message.reply_text(msg, parse_mode="Markdown")
    else:
        await update.message.reply_text("✅ Scan concluído. Nenhuma oportunidade encontrada nos critérios atuais.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /help"""
    await update.message.reply_text("Comandos: /start, /scan, /help")

if __name__ == '__main__':
    logger.info("Iniciando bot...")
    
    # Criar a aplicação
    application = ApplicationBuilder().token(TOKEN).build()
    
    # Adicionar comandos
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('scan', scan))
    application.add_handler(CommandHandler('help', help_command))
    
    # Rodar o bot (método mais simples e robusto)
    logger.info("Bot em execução (Polling)...")
    application.run_polling(drop_pending_updates=True)
