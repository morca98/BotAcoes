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
        
        # Build application
        self.app = ApplicationBuilder().token(self.token).build()

    async def send_direct_msg(self, text: str):
        """Envia uma mensagem direta para o chat configurado."""
        try:
            # Usar o bot da aplicação para enviar mensagens de forma assíncrona
            await self.app.bot.send_message(chat_id=self.chat_id, text=text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Erro ao enviar mensagem: {e}")

    async def run_scan(self):
        """Executa o scan de mercado para todos os ativos configurados."""
        logger.info("A iniciar scan de mercado...")
        signals = []
        
        # Obter o loop atual para executar tarefas síncronas num executor
        loop = asyncio.get_running_loop()
        
        for ticker in self.config.ASSETS:
            try:
                # Executar análise num executor para não bloquear o loop (yf.history é bloqueante)
                res = await loop.run_in_executor(None, self.scanner.analyze, ticker)
                if res:
                    signals.append(res)
            except Exception as e:
                logger.error(f"Erro ao processar {ticker}: {e}")
                continue

        now = datetime.now(LISBON_TZ).strftime("%d/%m/%Y %H:%M")
        if signals:
            msg = f"🎯 *Sinais de Compra* — {now}\n━━━━━━━━━━━━━━━━━━━━\n"
            for s in signals:
                msg += (f"🔹 *{s['ticker']}* @ `${s['price']}`\n"
                        f"   RS/Setor ({s['sector_etf']}): `{s['rs_sector']}`\n"
                        f"   ATR%: `{s['atr_pct']}%` | RSI D: `{s['rsi_daily']}`\n\n")
        else:
            msg = f"🔍 *Scan concluído* — {now}\nNenhuma ação cumpre os critérios no momento."
        
        await self.send_direct_msg(msg)

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o comando /start."""
        await update.message.reply_text("🚀 *Bot de Ações Ativo!*\nUse /scan para análise imediata.")

    async def cmd_scan(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o comando /scan."""
        await update.message.reply_text("🔍 *A iniciar scan manual...*")
        await self.run_scan()

    async def scheduler_loop(self):
        """Loop de agendamento para execução diária."""
        logger.info("Agendamento iniciado (08:00 Europe/Lisbon).")
        while True:
            now = datetime.now(LISBON_TZ)
            # Verifica se é 08:00
            if now.hour == 8 and now.minute == 0:
                await self.run_scan()
                # Espera 65 segundos para não disparar várias vezes no mesmo minuto
                await asyncio.sleep(65)
            await asyncio.sleep(30)

    async def post_init(self, application):
        """Função chamada automaticamente após a inicialização do bot."""
        await self.send_direct_msg("🟢 *Bot Iniciado com Sucesso!*")
        # Iniciar o loop de agendamento como uma task de background
        asyncio.create_task(self.scheduler_loop())

    def run(self):
        """Inicia o bot em modo polling."""
        # Handlers
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("scan", self.cmd_scan))
        
        # Configurar post_init para startup logic
        self.app.post_init = self.post_init
        
        logger.info("Bot em polling...")
        # run_polling é um método síncrono que gere o seu próprio loop de eventos internamente
        # Isto resolve o erro "RuntimeError: This event loop is already running"
        self.app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    bot = StockBot()
    bot.run()
