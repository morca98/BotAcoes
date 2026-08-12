import logging
import os
import sys
import asyncio
import json
from datetime import datetime
import pytz
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

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
WATCHLIST_FILE = "watchlist.json"

class StockBot:
    def __init__(self):
        self.config = Config()
        self.scanner = Scanner(self.config)
        self.token = os.getenv("TELEGRAM_BOT_TOKEN") or self.config.TELEGRAM_TOKEN
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID") or self.config.TELEGRAM_CHAT_ID
        
        # Memória e Watchlist
        self.last_scan_tickers = set()
        self.active_breakouts = set()
        self.user_watchlist = self._load_watchlist()
        
        self.app = ApplicationBuilder().token(self.token).build()

    def _load_watchlist(self):
        if os.path.exists(WATCHLIST_FILE):
            try:
                with open(WATCHLIST_FILE, 'r') as f:
                    return set(json.load(f))
            except:
                return set()
        return set()

    def _save_watchlist(self):
        with open(WATCHLIST_FILE, 'w') as f:
            json.dump(list(self.user_watchlist), f)

    async def send_direct_msg(self, text: str):
        try:
            await self.app.bot.send_message(chat_id=self.chat_id, text=text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Erro ao enviar mensagem: {e}")

    async def run_scan(self, is_manual=False):
        logger.info("A iniciar scan dinâmico...")
        
        # 1. Obter Universo Dinâmico (S&P 500 + Nasdaq 100 + ETFs + Watchlist)
        loop = asyncio.get_running_loop()
        full_universe = await loop.run_in_executor(None, self.scanner.get_dynamic_universe)
        full_universe = list(set(full_universe) | self.user_watchlist)
        
        # 2. Filtrar por Top Liquidez (500 ativos)
        filtered_universe = await loop.run_in_executor(None, self.scanner.filter_by_liquidity, full_universe, 500)
        
        # 3. Analisar cada ativo
        current_signals = {}
        for ticker in filtered_universe:
            try:
                res = await loop.run_in_executor(None, self.scanner.analyze, ticker)
                if res:
                    current_signals[ticker] = res
            except:
                continue

        now = datetime.now(LISBON_TZ).strftime("%d/%m/%Y %H:%M")
        current_tickers = set(current_signals.keys())
        new_tickers = current_tickers - self.last_scan_tickers
        new_breakouts = {t for t, s in current_signals.items() if s['breakout_2h'] and t not in self.active_breakouts}
        
        self.last_scan_tickers = current_tickers
        self.active_breakouts = {t for t, s in current_signals.items() if s['breakout_2h']}

        msg = ""
        if is_manual:
            msg = f"🔍 *Scan Completo ({len(filtered_universe)} ativos)* — {now}\n"
            if not current_signals:
                msg += "Nenhuma ação cumpre os critérios no momento."
            else:
                for t, s in current_signals.items():
                    msg += self._format_signal(s)
        else:
            if new_tickers or new_breakouts:
                msg = f"🔔 *Atualização Importante* — {now}\n━━━━━━━━━━━━━━━━━━━━\n"
                if new_tickers:
                    msg += "\n🌟 *Novos Ativos na Lista:*\n"
                    for t in new_tickers:
                        msg += self._format_signal(current_signals[t])
                if new_breakouts:
                    msg += "\n🚀 *Rompimentos 2h Detetados:*\n"
                    for t in new_breakouts:
                        if t in new_tickers:
                            msg += f"🔹 *{t}* também confirmou rompimento!\n"
                        else:
                            msg += self._format_signal(current_signals[t])
            else:
                logger.info("Nenhuma atualização importante encontrada.")
                return

        if msg:
            await self.send_direct_msg(msg)

    def _format_signal(self, s):
        div_status = "✅ Sim" if s['div_bullish'] else "❌ Não"
        vcp_status = "✅ Sim" if s['is_vcp'] else "❌ Não"
        break_status = "🚀 *ROMPIMENTO 2H!*" if s['breakout_2h'] else ""
        return (f"🔹 *{s['ticker']}* @ `${s['price']}` {break_status}\n"
                f"   RS/Setor ({s['sector_etf']}): `{s['rs_sector']}`\n"
                f"   Divergência (4h): {div_status} | VCP: {vcp_status}\n"
                f"   ATR%: `{s['atr_pct']}%` | RSI D: `{s['rsi_daily']}`\n\n")

    # --- Comandos de Watchlist ---
    async def cmd_add(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Uso: /add TICKER")
            return
        ticker = context.args[0].upper()
        self.user_watchlist.add(ticker)
        self._save_watchlist()
        await update.message.reply_text(f"✅ *{ticker}* adicionado à tua watchlist!")

    async def cmd_remove(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Uso: /remove TICKER")
            return
        ticker = context.args[0].upper()
        if ticker in self.user_watchlist:
            self.user_watchlist.remove(ticker)
            self._save_watchlist()
            await update.message.reply_text(f"🗑️ *{ticker}* removido da watchlist.")
        else:
            await update.message.reply_text(f"O ativo *{ticker}* não está na tua watchlist.")

    async def cmd_watchlist(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.user_watchlist:
            await update.message.reply_text("A tua watchlist está vazia.")
            return
        msg = "📋 *Tua Watchlist:*\n" + ", ".join(sorted(self.user_watchlist))
        await update.message.reply_text(msg)

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("🚀 *Bot Pro Ativo!*\nScan 2h: S&P 500 + Nasdaq + ETFs + Watchlist.\n\nComandos:\n/add - Adicionar ativo\n/remove - Remover ativo\n/watchlist - Ver lista\n/scan - Scan manual")

    async def scheduler_loop(self):
        logger.info("Monitorização contínua (2h) com universo dinâmico.")
        while True:
            await self.run_scan(is_manual=False)
            await asyncio.sleep(7200)

    async def post_init(self, application):
        await self.send_direct_msg("🟢 *Bot Pro Iniciado!* (Universo Dinâmico Ativo)")
        asyncio.create_task(self.scheduler_loop())

    def run(self):
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("scan", self.cmd_scan))
        self.app.add_handler(CommandHandler("add", self.cmd_add))
        self.app.add_handler(CommandHandler("remove", self.cmd_remove))
        self.app.add_handler(CommandHandler("watchlist", self.cmd_watchlist))
        self.app.post_init = self.post_init
        self.app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    bot = StockBot()
    bot.run()
