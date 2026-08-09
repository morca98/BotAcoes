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

# --- Servidor Web para Railway ---
flask_app = Flask(__name__)

@flask_app.route('/')
def health():
    return "Bot is active", 200

def run_flask():
    port = int(os.getenv("PORT", 8080))
    logger.info(f"Servidor web na porta {port}")
    flask_app.run(host='0.0.0.0', port=port)

# --- Classe Principal do Bot ---
class StockBot:
    def __init__(self):
        self.config = Config()
        self.scanner = Scanner(self.config)
        self.token = self.config.TELEGRAM_TOKEN
        self.chat_id = self.config.TELEGRAM_CHAT_ID
        
        self.app = ApplicationBuilder().token(self.token).build()

    async def send_msg(self, text: str):
        """Envia mensagem via HTTP direto para evitar bloqueios de polling"""
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "Markdown"}
        try:
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            logger.error(f"Erro ao enviar mensagem: {e}")

    async def run_scan(self):
        """Realiza o scan completo e envia relatório"""
        logger.info("Executando scan de mercado...")
        signals = []
        for ticker in self.config.ASSETS:
            try:
                # Usar run_in_executor para não travar o loop async
                res = await asyncio.get_event_loop().run_in_executor(None, self.scanner.analyze, ticker)
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
                        f"   EMA20 Dist: `{s['atr_pct']}%` (ATR)\n\n")
            await self.send_msg(msg)
        else:
            await self.send_msg(f"🔍 *Scan concluído* — {now}\nNenhuma ação cumpre os critérios técnicos no momento.")
        return signals

    # --- Handlers de Comandos ---
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("🚀 *Bot de Ações Ativo!*\nUse /scan para análise imediata ou /help para ver os filtros.", parse_mode="Markdown")

    async def cmd_scan(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("🔍 *A iniciar scan manual...*\nIsto pode demorar cerca de 1 minuto.", parse_mode="Markdown")
        await self.run_scan()

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = (
            "📖 *Estratégia de Pontos de Compra*\n\n"
            "*Filtros:*\n"
            "• Volume > 1M | Vol. USD > $20M\n"
            "• Preço > $10 | M.Cap > $2B\n"
            "• RSI Diário < 70 | RSI 4H < 60\n"
            "• Distância EMA20 < 8%\n"
            "• Preço > EMA200\n"
            "• EMA20 > EMA70 > EMA200"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    # --- Loop de Agendamento ---
    async def scheduler_loop(self):
        """Loop simplificado para scan diário às 08:00 Lisboa"""
        logger.info("Loop de agendamento iniciado.")
        while True:
            now = datetime.now(LISBON_TZ)
            # Se for 08:00 e ainda não rodou hoje
            if now.hour == 8 and now.minute == 0:
                await self.run_scan()
                await asyncio.sleep(65) # Esperar o minuto passar
            await asyncio.sleep(30) # Verificar a cada 30 segundos

    async def run(self):
        # 1. Iniciar Servidor Web
        threading.Thread(target=run_flask, daemon=True).start()
        
        # 2. Notificação de arranque imediata via HTTP (síncrona para garantir entrega)
        logger.info("A enviar notificação de arranque...")
        await self.send_msg("🟢 *Bot Iniciado com Sucesso!*\nO bot está agora ativo e a monitorizar o mercado no Railway.")
        
        # 3. Adicionar Handlers
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("scan", self.cmd_scan))
        self.app.add_handler(CommandHandler("help", self.cmd_help))
        
        # 4. Iniciar Agendamento
        asyncio.create_task(self.scheduler_loop())
        
        # 5. Iniciar Polling (com inicialização explícita)
        logger.info("Bot em polling...")
        async with self.app:
            await self.app.start()
            await self.app.updater.start_polling(drop_pending_updates=True)
            # Manter o loop vivo
            while True:
                await asyncio.sleep(3600)

if __name__ == "__main__":
    bot = StockBot()
    asyncio.run(bot.run())
