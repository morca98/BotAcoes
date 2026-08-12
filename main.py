import logging
import os
import sys
import asyncio
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

# --- Classe do Bot ---
class StockBot:
    def __init__(self):
        self.config = Config()
        self.scanner = Scanner(self.config)
        self.token = os.getenv("TELEGRAM_BOT_TOKEN") or self.config.TELEGRAM_TOKEN
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID") or self.config.TELEGRAM_CHAT_ID
        
        # Memória para evitar notificações repetitivas
        self.last_scan_tickers = set()
        self.active_breakouts = set()
        
        # Build application
        self.app = ApplicationBuilder().token(self.token).build()

    async def send_direct_msg(self, text: str):
        """Envia uma mensagem direta para o chat configurado."""
        try:
            await self.app.bot.send_message(chat_id=self.chat_id, text=text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Erro ao enviar mensagem: {e}")

    async def run_scan(self, is_manual=False):
        """Executa o scan de mercado e notifica apenas atualizações importantes."""
        logger.info("A iniciar scan de mercado...")
        current_signals = {}
        
        loop = asyncio.get_running_loop()
        
        for ticker in self.config.ASSETS:
            try:
                res = await loop.run_in_executor(None, self.scanner.analyze, ticker)
                if res:
                    current_signals[ticker] = res
            except Exception as e:
                logger.error(f"Erro ao processar {ticker}: {e}")
                continue

        now = datetime.now(LISBON_TZ).strftime("%d/%m/%Y %H:%M")
        current_tickers = set(current_signals.keys())
        
        # Identificar atualizações importantes
        new_tickers = current_tickers - self.last_scan_tickers
        new_breakouts = {t for t, s in current_signals.items() if s['breakout_2h'] and t not in self.active_breakouts}
        
        # Atualizar memória
        self.last_scan_tickers = current_tickers
        self.active_breakouts = {t for t, s in current_signals.items() if s['breakout_2h']}

        # Construir mensagem
        msg = ""
        if is_manual:
            msg = f"🔍 *Scan Manual Concluído* — {now}\n"
            if not current_signals:
                msg += "Nenhuma ação cumpre os critérios no momento."
            else:
                for t, s in current_signals.items():
                    msg += self._format_signal(s)
        else:
            # Notificação automática apenas se houver novidades
            if new_tickers or new_breakouts:
                msg = f"🔔 *Atualização Importante* — {now}\n━━━━━━━━━━━━━━━━━━━━\n"
                
                if new_tickers:
                    msg += "\n🌟 *Novos Ativos na Lista:*\n"
                    for t in new_tickers:
                        msg += self._format_signal(current_signals[t])
                
                if new_breakouts:
                    msg += "\n🚀 *Rompimentos 2h Detetados:*\n"
                    for t in new_breakouts:
                        # Se já foi listado em new_tickers, não repetir o sinal completo
                        if t in new_tickers:
                            msg += f"🔹 *{t}* também confirmou rompimento!\n"
                        else:
                            msg += self._format_signal(current_signals[t])
            else:
                logger.info("Scan concluído: Nenhuma atualização importante encontrada.")
                return

        if msg:
            await self.send_direct_msg(msg)

    def _format_signal(self, s):
        """Formata um sinal individual para a mensagem."""
        div_status = "✅ Sim" if s['div_bullish'] else "❌ Não"
        vcp_status = "✅ Sim" if s['is_vcp'] else "❌ Não"
        break_status = "🚀 *ROMPIMENTO 2H!*" if s['breakout_2h'] else ""
        
        return (f"🔹 *{s['ticker']}* @ `${s['price']}` {break_status}\n"
                f"   RS/Setor ({s['sector_etf']}): `{s['rs_sector']}`\n"
                f"   Divergência Bullish (4h): {div_status}\n"
                f"   Contração Volat. (VCP): {vcp_status}\n"
                f"   ATR%: `{s['atr_pct']}%` | RSI D: `{s['rsi_daily']}`\n\n")

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("🚀 *Bot de Monitorização Ativo!*\nScan automático a cada 2h.\nUse /scan para ver a lista atual.")

    async def cmd_scan(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("🔍 *A iniciar scan completo...*")
        await self.run_scan(is_manual=True)

    async def scheduler_loop(self):
        """Loop de agendamento: corre a cada 2 horas."""
        logger.info("Monitorização contínua iniciada (Intervalo: 2h).")
        while True:
            # Executar scan
            await self.run_scan(is_manual=False)
            # Esperar 2 horas (7200 segundos)
            await asyncio.sleep(7200)

    async def post_init(self, application):
        await self.send_direct_msg("🟢 *Bot de Monitorização 2h Iniciado!*")
        asyncio.create_task(self.scheduler_loop())

    def run(self):
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("scan", self.cmd_scan))
        self.app.post_init = self.post_init
        logger.info("Bot em polling...")
        self.app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    bot = StockBot()
    bot.run()
