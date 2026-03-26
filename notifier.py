"""Notifier — Stock Signal Bot MTF V3"""

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

    async def send_signal(self, s: dict):
        now = datetime.now(LISBON_TZ).strftime("%d/%m/%Y %H:%M")
        bar = self._bar(s["confidence"])
        msg = (
            f"🚀 *SINAL DE COMPRA — {s['ticker']}*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 {now}\n\n"
            f"💵 *Entrada:* `{s['price']}`\n"
            f"🛡 *Stop Loss:* `{s['sl']}` (-{abs(s['price']-s['sl'])/s['price']*100:.1f}%)\n"
            f"🎯 *Take Profit:* `{s['tp']}` (+{abs(s['tp']-s['price'])/s['price']*100:.1f}%)\n"
            f"⚖️ *R:R:* 1:{s['rr']:.0f}\n\n"
            f"📐 *Gestão:*\n"
            f"  • Breakeven a: `{s['breakeven_price']}`\n"
            f"  • Trailing a:  `{s['trailing_price']}`\n"
            f"  • Tamanho:     `{s['size']} unid.`\n"
            f"  • Risco:       `€{s['risk_eur']}`\n\n"
            f"📊 *Indicadores:*\n"
            f"  • RSI Semanal: `{s['rsi_weekly']}` < 50 ✅\n"
            f"  • RSI 4H:      `{s['rsi_4h']}` < 40 ✅\n"
            f"  • SMA70:       `{s['sma70']}` ✅\n"
            f"  • Div. MACD:   Bullish ✅\n"
            f"  • HH+HL:       Confirmado ✅\n\n"
            f"🔥 *Confiança:* {s['confidence']}% {bar}"
        )
        await self._send(msg)

    async def send_scan_report(self, total: int, signals: int, tickers: list):
        now = datetime.now(LISBON_TZ).strftime("%d/%m/%Y %H:%M")
        extra = ""
        if tickers:
            extra = "\n\n📋 *Sinais:*\n" + "\n".join(
                f"  • {t['ticker']} @ {t['price']} (conf: {t['confidence']}%)"
                for t in tickers
            )
        msg = (
            f"🔍 *Relatório de Scan* — {now}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Ativos analisados: *{total}*\n"
            f"🎯 Sinais encontrados: *{signals}*\n"
            f"🔄 Próximo scan: em *4 horas*{extra}"
        )
        await self._send(msg)

    async def send_daily_report(self, trades: list, capital: float):
        now = datetime.now(LISBON_TZ).strftime("%d/%m/%Y")
        msg = (
            f"📈 *Relatório Diário — {now}*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Capital: `€{capital:,.2f}`\n"
            f"📋 Sinais hoje: `{len(trades)}`\n"
        )
        if trades:
            msg += "\n*Trades do dia:*\n"
            for t in trades:
                msg += f"  • {t.get('ticker','?')} @ {t.get('price','?')}\n"
        msg += "\n✅ Bot operacional — bom trading! 🎯"
        await self._send(msg)

    async def send_status_online(self):
        now = datetime.now(LISBON_TZ).strftime("%d/%m/%Y %H:%M")
        msg = (
            f"🟢 *Stock Signal Bot MTF V3 — Online*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ Iniciado: {now}\n"
            f"🔄 Scan: cada 4 horas\n"
            f"📊 Ativos: 143 | Risco: 1%/trade\n"
            f"🎯 5 filtros MTF ativos\n\n"
            f"_Bot pronto para operar._"
        )
        await self._send(msg)

    @staticmethod
    def _bar(confidence: int) -> str:
        f = round(confidence / 10)
        return "█" * f + "░" * (10 - f)
