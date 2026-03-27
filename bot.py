"""
Stock Signal Bot - MTF V3
Multi-Timeframe Technical Analysis Trading Bot AI
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
from risk_manager import RiskManager
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
        self.config = Config()
        self.scanner = MarketScanner(self.config)
        self.risk_manager = RiskManager(self.config)
        self.notifier = Notifier(self.config)
        self.app = Application.builder().token(self.config.TELEGRAM_TOKEN).build()
        self.scheduler = AsyncIOScheduler(timezone=LISBON_TZ)
        self.trade_log = []

    def setup_handlers(self):
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("status", self.cmd_status))
        self.app.add_handler(CommandHandler("trades", self.cmd_trades))
        self.app.add_handler(CommandHandler("scan", self.cmd_scan))
        self.app.add_handler(CommandHandler("capital", self.cmd_capital))
        self.app.add_handler(CommandHandler("help", self.cmd_help))

    def setup_scheduler(self):
        self.scheduler.add_job(
            self.run_market_scan, "cron",
            hour="0,4,8,12,16,20", minute=0, id="market_scan"
        )
        self.scheduler.add_job(
            self.send_daily_report, "cron",
            hour=9, minute=0, id="daily_report"
        )

    async def run_market_scan(self):
        logger.info("Starting market scan...")
        signals = []
        for ticker in self.config.WATCHLIST:
            try:
                result = await asyncio.get_event_loop().run_in_executor(
                    None, self.scanner.analyze, ticker
                )
                if result and result.get("signal"):
                    result = self.risk_manager.calculate_levels(result, self.config.CAPITAL)
                    signals.append(result)
                    await self.notifier.send_signal(result)
            except Exception as e:
                logger.error(f"Error analyzing {ticker}: {e}")

        await self.notifier.send_scan_report(
            total=len(self.config.WATCHLIST),
            signals=len(signals),
            tickers=signals
        )
        logger.info(f"Scan complete. {len(signals)} signals found.")
        return signals

    async def send_daily_report(self):
        today = datetime.now(LISBON_TZ).date().isoformat()
        today_trades = [t for t in self.trade_log if t.get("date") == today]
        await self.notifier.send_daily_report(today_trades, self.config.CAPITAL)

    async def cmd_start(self, update, context):
        msg = (
            "🤖 *Stock Signal Bot MTF V3* está online!\n\n"
            "Comandos disponíveis:\n"
            "/status — Estado do bot\n"
            "/scan — Iniciar scan manual\n"
            "/trades — Últimos sinais\n"
            "/capital — Ver/alterar capital\n"
            "/help — Ajuda completa"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def cmd_status(self, update, context):
        now = datetime.now(LISBON_TZ).strftime("%d/%m/%Y %H:%M")
        msg = (
            f"📊 *Status do Bot*\n\n"
            f"🟢 Online: {now}\n"
            f"💰 Capital: €{self.config.CAPITAL:,.2f}\n"
            f"⚙️ Risco/trade: {self.config.RISK_PCT*100:.0f}%\n"
            f"📋 Ativos: {len(self.config.WATCHLIST)}\n"
            f"🔄 Scan: cada 4 horas\n"
            f"📈 Sinais hoje: {len(self.trade_log)}"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def cmd_trades(self, update, context):
        if not self.trade_log:
            await update.message.reply_text("Nenhum sinal registado ainda.")
            return
        lines = ["📋 *Últimos Sinais*\n"]
        for t in reversed(self.trade_log[-5:]):
            lines.append(
                f"• *{t['ticker']}* @ {t['price']:.2f} "
                f"| SL: {t['sl']:.2f} | TP: {t['tp']:.2f} "
                f"| Conf: {t['confidence']}%"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def cmd_scan(self, update, context):
        await update.message.reply_text("🔍 A iniciar scan manual...")
        signals = await self.run_market_scan()
        await update.message.reply_text(
            f"✅ Scan concluído. {len(signals)} sinal(is) encontrado(s)."
        )

    async def cmd_capital(self, update, context):
        args = context.args
        if args:
            try:
                novo = float(args[0])
                self.config.CAPITAL = novo
                await update.message.reply_text(f"✅ Capital: €{novo:,.2f}")
            except ValueError:
                await update.message.reply_text("❌ Uso: /capital 10000")
        else:
            await update.message.reply_text(f"💰 Capital: €{self.config.CAPITAL:,.2f}")

    async def cmd_help(self, update, context):
        msg = (
            "📖 *Stock Signal Bot MTF V3 — Ajuda*\n\n"
            "*5 Filtros da Estratégia:*\n"
            "1️⃣ RSI Semanal < 50\n"
            "2️⃣ Preço > SMA70 Diário\n"
            "3️⃣ RSI 4H < 40 (pullback)\n"
            "4️⃣ Divergência Bullish MACD 4H\n"
            "5️⃣ Vela 4H com HH + HL\n\n"
            "*Gestão de Risco:*\n"
            "• R:R 1:3 | Risco 1% trade\n"
    
            "/start /status /scan /trades /capital"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def run(self):
        start_health_server(port=8080)
        self.setup_handlers()
        self.setup_scheduler()
        self.scheduler.start()

        async with self.app:
            await self.app.start()
            await self.notifier.send_status_online()
            await self.app.updater.start_polling()
            logger.info("Bot is polling...")
            await asyncio.Event().wait()
            await self.app.updater.stop()
            await self.app.stop()


if __name__ == "__main__":
    bot = StockSignalBot()
    asyncio.run(bot.run())
