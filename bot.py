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

# Configuração de Logs
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    stream=sys.stdout
)
logger = logging.getLogger(__name__)
LISBON_TZ = pytz.timezone("Europe/Lisbon")

# --- Servidor Web para o Railway (Obrigatório para evitar 'status: exited') ---
flask_app = Flask(__name__)

@flask_app.route('/')
def health():
    return "Bot is active and scanning!", 200

def run_flask():
    port = int(os.getenv("PORT", 8080))
    logger.info(f"Servidor web a iniciar na porta {port}...")
    flask_app.run(host='0.0.0.0', port=port)

# --- Classe do Bot ---
class StockBot:
    def __init__(self):
        self.config = Config()
        self.scanner = Scanner(self.config)
        self.token = os.getenv("TELEGRAM_BOT_TOKEN") or self.config.TELEGRAM_TOKEN
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID") or self.config.TELEGRAM_CHAT_ID
        
        self.app = ApplicationBuilder().token(self.token).build()

    async def send_direct_msg(self, text: str):
        """Envio via HTTP direto para máxima garantia de entrega"""
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "Markdown"}
        try:
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            logger.error(f"Erro ao enviar mensagem: {e}")

    async def run_scan(self):
        logger.info("A iniciar scan de mercado...")
        signals = []
        for ticker in self.config.ASSETS:
            try:
                res = await asyncio.get_event_loop().run_in_executor(None, self.scanner.analyze, ticker)
                if res:
                    signals.append(res)
            except:
                continue

        now = datetime.now(LISBON_TZ).strftime("%d/%m/%Y %H:%M")
        if signals:
            msg = f"🎯 *Ações em Ponto de Compra* — {now}\n━━━━━━━━━━━━━━━━━━━━\n"
            for s in signals:
                msg += (f"🔹 *{s['ticker']}* @ `${s['price']}`\n"
                        f"   RSI D: `{s['rsi_daily']}` | RSI 4H: `{s['rsi_4h']}`\n"
                        f"   ATR%: `{s['atr_pct']}%` | Dist. EMA20: < 8%\n\n")
            await self.send_msg_with_app(msg)
        else:
            await self.send_msg_with_app(f"🔍 *Scan concluído* — {now}\nNenhuma ação cumpre os critérios no momento.")

    async def send_msg_with_app(self, text: str):
        try:
            await self.app.bot.send_message(chat_id=self.chat_id, text=text, parse_mode="Markdown")
        except:
            await self.send_direct_msg(text)

    # --- Handlers ---
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("🚀 *Bot de Ações Ativo!*\nUse /scan para análise imediata ou /help para ver os filtros.")

    async def cmd_scan(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("🔍 *A iniciar scan manual...*")
        await self.run_scan()

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = (
            "📖 *Critérios da Estratégia:*\n"
            "• Volume > 1M | Preço > $10\n"
            "• RSI Diário < 70 | RSI 4H < 60\n"
            "• Distância EMA20 < 8%\n"
            "• Tendência: Preço > EMA200"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def scheduler_loop(self):
        logger.info("Loop de agendamento (08:00) iniciado.")
        while True:
            now = datetime.now(LISBON_TZ)
            if now.hour == 8 and now.minute == 0:
                await self.run_scan()
                await asyncio.sleep(65)
            await asyncio.sleep(30)

    async def run(self):
        # 1. Iniciar Servidor Web em background (Fundamental para o Railway)
        threading.Thread(target=run_flask, daemon=True).start()
        
        # 2. Notificação imediata de arranque
        await self.send_direct_msg("🟢 *Bot Iniciado com Sucesso!*\nO bot está agora ativo e a monitorizar o mercado no Railway.")
        
        # 3. Handlers
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("scan", self.cmd_scan))
        self.app.add_handler(CommandHandler("help", self.cmd_help))
        
        # 4. Agendamento
        asyncio.create_task(self.scheduler_loop())
        
        # 5. Polling
        logger.info("Bot em polling...")
        await self.app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    bot = StockBot()
    asyncio.run(bot.run())
