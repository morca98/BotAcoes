"""
Stock Signal Bot - Localizador de Pontos de Compra
"""

import asyncio
import logging
import os
from datetime import datetime
import pytz

from telegram import Bot
from telegram.ext import Application, CommandHandler
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from scanner import MarketScanner
from notifier import Notifier
from config import Config
from health_server import start_health_server

# Configuração de logs mais detalhada
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)
LISBON_TZ = pytz.timezone("Europe/Lisbon")


class StockSignalBot:
    def __init__(self):
        try:
            self.config = Config()
            logger.info("Configuração carregada.")
            
            # Verificar se as variáveis de ambiente estão presentes
            if not self.config.TELEGRAM_TOKEN:
                logger.error("ERRO: TELEGRAM_BOT_TOKEN não encontrada!")
                # Se estiver no sandbox e vazio, usar o valor conhecido para o teste
                self.config.TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8890309916:AAEkC2DPEtuyGJWDbtof-4s6YozCC9bvjGs")
            
            if not self.config.TELEGRAM_CHAT_ID:
                logger.error("ERRO: TELEGRAM_CHAT_ID não encontrada!")
                self.config.TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1354621810")

            self.scanner = MarketScanner(self.config)
            self.notifier = Notifier(self.config)
            
            # Inicializar Application do python-telegram-bot
            self.app = Application.builder().token(self.config.TELEGRAM_TOKEN).build()
            self.scheduler = AsyncIOScheduler(timezone=LISBON_TZ)
            self.trade_log = []
            
            logger.info("Componentes inicializados com sucesso.")
        except Exception as e:
            logger.error(f"Erro crítico na inicialização: {e}")
            raise e

    def setup_handlers(self):
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("status", self.cmd_status))
        self.app.add_handler(CommandHandler("scan", self.cmd_scan))
        self.app.add_handler(CommandHandler("list", self.cmd_list_assets))
        self.app.add_handler(CommandHandler("help", self.cmd_help))

    def setup_scheduler(self):
        # Scan diário às 08:00 de Lisboa
        self.scheduler.add_job(
            self.run_market_scan, "cron",
            hour=8, minute=0, id="daily_scan"
        )
        logger.info("Agendamento configurado para as 08:00.")

    async def run_market_scan(self):
        logger.info("A iniciar scan de mercado...")
        signals = []
        for ticker in self.config.ASSETS:
            try:
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
        self.trade_log.extend(signals)
        logger.info(f"Scan concluído. {len(signals)} sinais encontrados.")
        return signals

    async def cmd_start(self, update, context):
        msg = "🤖 *Bot de Ações* online!\nUse /help para ver os critérios."
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def cmd_status(self, update, context):
        now = datetime.now(LISBON_TZ).strftime("%d/%m/%Y %H:%M")
        msg = f"📊 *Status*\n🟢 Online: {now}\n🔄 Scan: Diário (08:00)"
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def cmd_scan(self, update, context):
        await update.message.reply_text("🔍 A iniciar scan manual...")
        await self.run_market_scan()

    async def cmd_list_assets(self, update, context):
        assets = ", ".join(sorted(self.config.ASSETS))
        await update.message.reply_text(f"📋 *Ativos:*\n{assets}", parse_mode="Markdown")

    async def cmd_help(self, update, context):
        msg = "📖 *Critérios:*\n• Vol > 1M\n• Preço > $10\n• M.Cap > $2B\n• RSI D < 70\n• Dist. EMA20 < 8%"
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def run(self):
        # Iniciar servidor de saúde para o Railway
        try:
            start_health_server(port=int(os.environ.get("PORT", 8080)))
        except:
            pass
            
        self.setup_handlers()
        self.setup_scheduler()
        self.scheduler.start()

        # Lógica de arranque simplificada
        logger.info("A iniciar a aplicação Telegram...")
        await self.app.initialize()
        await self.app.start()
        
        # Teste de envio imediato
        logger.info("A enviar notificação de arranque...")
        try:
            await self.notifier.send_status_online()
            logger.info("Notificação enviada!")
        except Exception as e:
            logger.error(f"Falha ao enviar notificação inicial: {e}")
        
        logger.info("A iniciar polling...")
        await self.app.updater.start_polling()
        
        # Manter vivo
        try:
            while True:
                await asyncio.sleep(3600)
        except (KeyboardInterrupt, SystemExit):
            logger.info("A desligar...")
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()


if __name__ == "__main__":
    bot = StockSignalBot()
    asyncio.run(bot.run())
