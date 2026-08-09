"""
Stock Signal Bot - Versão Estável para Railway
"""

import asyncio
import logging
import os
import sys
from datetime import datetime
import pytz

from telegram import Bot
from telegram.ext import Application, CommandHandler
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from scanner import MarketScanner
from notifier import Notifier
from config import Config

# Configuração de logs
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    stream=sys.stdout
)
logger = logging.getLogger(__name__)
LISBON_TZ = pytz.timezone("Europe/Lisbon")

class StockSignalBot:
    def __init__(self):
        self.config = Config()
        
        # Fallback para credenciais se as variáveis de ambiente falharem
        self.token = os.getenv("TELEGRAM_BOT_TOKEN") or "8890309916:AAEkC2DPEtuyGJWDbtof-4s6YozCC9bvjGs"
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID") or "1354621810"
        
        # Forçar no config para o Notifier usar
        self.config.TELEGRAM_TOKEN = self.token
        self.config.TELEGRAM_CHAT_ID = self.chat_id

        self.scanner = MarketScanner(self.config)
        self.notifier = Notifier(self.config)
        
        # Construir a aplicação
        self.app = Application.builder().token(self.token).build()
        self.scheduler = AsyncIOScheduler(timezone=LISBON_TZ)
        
        logger.info("Bot inicializado com sucesso.")

    async def run_market_scan(self):
        logger.info("Iniciando scan de mercado...")
        signals = []
        for ticker in self.config.ASSETS:
            try:
                # Análise técnica
                result = await asyncio.get_event_loop().run_in_executor(
                    None, self.scanner.analyze, ticker
                )
                if result:
                    signals.append(result)
            except Exception as e:
                logger.error(f"Erro ao analisar {ticker}: {e}")

        await self.notifier.send_scan_report(
            total=len(self.config.ASSETS),
            signals=len(signals),
            tickers=signals
        )
        return signals

    # --- Comandos do Telegram ---
    async def cmd_start(self, update, context):
        await update.message.reply_text("🤖 *Bot de Ações Online!*\nUse /scan para análise imediata ou /help para critérios.", parse_mode="Markdown")

    async def cmd_help(self, update, context):
        msg = (
            "📖 *Estratégia de Pontos de Compra*\n"
            "• Volume > 1M | Preço > $10\n"
            "• RSI Diário < 70 | RSI 4H < 60\n"
            "• Distância EMA20 < 8%\n"
            "• Tendência: Preço > EMA200"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def cmd_scan(self, update, context):
        await update.message.reply_text("🔍 *A iniciar scan manual...*\nIsto pode demorar um pouco.", parse_mode="Markdown")
        await self.run_market_scan()
        await update.message.reply_text("✅ *Scan concluído!* Verifique a lista acima.", parse_mode="Markdown")

    async def cmd_status(self, update, context):
        now = datetime.now(LISBON_TZ).strftime("%d/%m/%Y %H:%M")
        await update.message.reply_text(f"📊 *Status do Bot*\n🟢 Online: {now}\n⏰ Scan: Diário às 08:00", parse_mode="Markdown")

    async def run(self):
        # 1. Configurar Handlers
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("help", self.cmd_help))
        self.app.add_handler(CommandHandler("scan", self.cmd_scan))
        self.app.add_handler(CommandHandler("status", self.cmd_status))

        # 2. Configurar Agendamento (08:00 Lisboa)
        self.scheduler.add_job(self.run_market_scan, "cron", hour=8, minute=0)
        self.scheduler.start()

        # 3. Iniciar Bot
        logger.info("Iniciando Polling...")
        
        # Notificação de que ligou (usando o bot da aplicação)
        try:
            await self.app.bot.send_message(
                chat_id=self.chat_id, 
                text="🟢 *Bot de Ações Iniciado*\nO bot está agora ativo e a processar comandos no Railway.",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Erro ao enviar mensagem inicial: {e}")

        # O run_polling() é bloqueante e gere o loop de eventos corretamente
        await self.app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    bot = StockSignalBot()
    # Criar e rodar o loop principal
    asyncio.run(bot.run())
