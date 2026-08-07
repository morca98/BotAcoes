"""Notifier — Stock Signal Bot"""

import logging
from datetime import datetime
import pytz
from telegram import Bot
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)
LISBON_TZ = pytz.timezone("Europe/Lisbon")


class Notifier:
    def __init__(self, config):
        self.config = config
        self.bot = Bot(token=config.TELEGRAM_TOKEN)
        self.chat_id = config.TELEGRAM_CHAT_ID

    async def _send(self, text: str):
        try:
            await self.bot.send_message(chat_id=self.chat_id, text=text, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Telegram error: {e}")

    async def send_scan_report(self, total: int, signals: int, tickers: list):
        now = datetime.now(LISBON_TZ).strftime("%d/%m/%Y %H:%M")
        msg = (
            f"🎯 *RELATÓRIO DE PONTOS DE COMPRA* — {now}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Ativos analisados: *{total}*\n"
            f"🚀 Oportunidades encontradas: *{signals}*\n"
        )
        if tickers:
            msg += "\n📋 *Ações perto de ponto de compra:*\n"
            for t in tickers:
                msg += (
                    f"\n🔹 *{t['ticker']}* @ `${t['price']}`\n"
                    f"  • RSI Diário: `{t['rsi_daily']}` (≤70)\n"
                    f"  • RSI 4H: `{t['rsi_4h']}` (≤60)\n"
                    f"  • EMA20: `{t['ema20']}` | EMA70: `{t['ema70']}` | EMA200: `{t['ema200']}`\n"
                    f"  • ATR%: `{t['atr_pct']}%` (≥2%)\n"
                    f"  • Vol. Dólar: `$ {t['dollar_volume']}M` | M.Cap: `$ {t['market_cap']}B`\n"
                )
        else:
            msg += "\nNenhuma ação cumpriu rigorosamente todos os filtros técnicos e de volume nesta ronda."
        
        await self._send(msg)

    async def send_status_online(self):
        now = datetime.now(LISBON_TZ).strftime("%d/%m/%Y %H:%M")
        msg = (
            f"🟢 *Bot de Ações (Pontos de Compra) — Online*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ Iniciado: {now}\n"
            f"🔄 Filtros Ativos:\n"
            f"  • Volume médio > 1M | Vol. USD > $20M\n"
            f"  • Preço > $10 | M.Cap > $2B\n"
            f"  • RSI Diário < 70 | RSI 4H < 60\n"
            f"  • Tendência: Preço > EMA200 > EMA70 > EMA20\n"
            f"  • Afastamento EMA20 < 8% | ATR% > 2%\n"
        )
        await self._send(msg)
