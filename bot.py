"""
Stock Signal Bot - Localizador de Pontos de Compra
"""

import asyncio
import logging
import os
from datetime import datetime
import pytz

from telegram import Bot
from telegram.ext import Application, CommandHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from scanner import MarketScanner
from notifier import Notifier
from config import Config
from health_server import start_health_server

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
            logger.info("Config loaded successfully")
            self.scanner = MarketScanner(self.config)
            self.notifier = Notifier(self.config)
            
            if not self.config.TELEGRAM_TOKEN:
                logger.error("TELEGRAM_TOKEN not found in config!")
                raise ValueError("TELEGRAM_TOKEN is missing")
                
            self.app = Application.builder().token(self.config.TELEGRAM_TOKEN).build()
            self.scheduler = AsyncIOScheduler(timezone=LISBON_TZ)
            self.trade_log = []
            logger.info("Bot components initialized successfully")
        except Exception as e:
            logger.error(f"Critical error during bot initialization: {e}")
            raise e

    def setup_handlers(self):
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("status", self.cmd_status))
        self.app.add_handler(CommandHandler("scan", self.cmd_scan))
        self.app.add_handler(CommandHandler("list", self.cmd_list_assets))
        self.app.add_handler(CommandHandler("help", self.cmd_help))

    def setup_scheduler(self):
        # Scan diário às 08:00
        self.scheduler.add_job(
            self.run_market_scan, "cron",
            hour=8, minute=0, id="daily_scan"
        )

    async def run_market_scan(self):
        logger.info("Starting market scan...")
        signals = []
        for ticker in self.config.ASSETS:
            try:
                # Executar análise em thread separada para não bloquear o loop async
                result = await asyncio.get_event_loop().run_in_executor(
                    None, self.scanner.analyze, ticker
                )
                if result:
                    signals.append(result)
                    # Opcional: enviar sinal individual ou agrupar no relatório final
            except Exception as e:
                logger.error(f"Error analyzing {ticker}: {e}")

        await self.notifier.send_scan_report(
            total=len(self.config.ASSETS),
            signals=len(signals),
            tickers=signals
        )
        self.trade_log.extend(signals)
        logger.info(f"Scan complete. {len(signals)} signals found.")
        return signals

    async def cmd_start(self, update, context):
        msg = (
            "🤖 *Bot de Ações (Pontos de Compra)* está online!\n\n"
            "Este bot monitoriza o mercado em busca de ações que cumpram critérios rigorosos de volume, capitalização e indicadores técnicos.\n\n"
            "Comandos disponíveis:\n"
            "/status — Estado do bot e filtros\n"
            "/scan — Iniciar scan manual imediato\n"
            "/list — Listar ativos monitorizados\n"
            "/help — Ver critérios da estratégia"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def cmd_status(self, update, context):
        now = datetime.now(LISBON_TZ).strftime("%d/%m/%Y %H:%M")
        msg = (
            f"📊 *Status do Bot*\n\n"
            f"🟢 Online: {now}\n"
            f"🔄 Scan: cada 4 horas\n"
            f"📋 Ativos monitorizados: {len(self.config.ASSETS)}\n"
            f"📈 Sinais detetados hoje: {len([s for s in self.trade_log if datetime.now().date() == datetime.now().date()])}"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def cmd_scan(self, update, context):
        await update.message.reply_text("🔍 A iniciar scan manual de ativos líquidas...")
        signals = await self.run_market_scan()
        await update.message.reply_text(
            f"✅ Scan concluído. {len(signals)} ativos encontrados."
        )

    async def cmd_list_assets(self, update, context):
        assets = self.config.ASSETS
        msg = "📋 *Ativos Monitorizados:*\n\n" + ", ".join(sorted(assets))
        if len(msg) > 4000:
            for i in range(0, len(msg), 4000):
                await update.message.reply_text(msg[i:i+4000], parse_mode="Markdown")
        else:
            await update.message.reply_text(msg, parse_mode="Markdown")

    async def cmd_help(self, update, context):
        msg = (
            "📖 *Estratégia de Pontos de Compra*\n\n"
            "*Filtros de Seleção:*\n"
            "• Volume Médio > 1M ações/dia\n"
            "• Volume Financeiro > $20M USD/dia\n"
            "• Preço > $10 | Capitalização > $2B\n\n"
            "*Filtros de Eliminação (Não mostra se):*\n"
            "❌ RSI Diário > 70 (Sobrecomprado)\n"
            "❌ RSI 4H > 60\n"
            "❌ Afastamento EMA20 > 8% (Esticado)\n"
            "❌ Preço < EMA200 (Tendência de Baixa)\n"
            "❌ EMA20 < EMA70 ou EMA70 < EMA200\n"
            "❌ ATR% < 2% (Baixa Volatilidade)"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def run(self):
        # Health server para Docker/Render/Heroku
        try:
            start_health_server(port=8080)
        except:
            pass
            
        self.setup_handlers()
        self.setup_scheduler()
        self.scheduler.start()

        # Inicializar a aplicação explicitamente
        await self.app.initialize()
        await self.app.start()
        
        # Enviar notificação de que o bot ligou
        logger.info("Sending online status to Telegram...")
        await self.notifier.send_status_online()
        
        logger.info("Bot is polling...")
        await self.app.updater.start_polling()
        
        # Manter o bot a correr
        try:
            while True:
                await asyncio.sleep(3600)
        except (KeyboardInterrupt, SystemExit):
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()


if __name__ == "__main__":
    bot = StockSignalBot()
    asyncio.run(bot.run())
