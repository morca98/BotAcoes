import logging
import os
import sys
import asyncio
import json
import html
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
        self.active_signals = {} # Tickers que passaram no último scan
        self.notified_touches = set() # Evitar spam de toques (Diário)
        self.notified_breakouts = set() # Evitar spam de rompimentos (Diário)
        self.last_reset_date = datetime.now(LISBON_TZ).date()
        self.user_watchlist = self._load_watchlist()
        
        # Monitorização de Saúde (Watchdog)
        self.last_scan_time = datetime.now(LISBON_TZ)
        self.last_support_check_time = datetime.now(LISBON_TZ)
        self.scan_lock = asyncio.Lock() # Evitar scans simultâneos
        
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
        """Envia mensagens longas dividindo-as se necessário e usando HTML para estabilidade."""
        try:
            # Limite do Telegram é 4096 carateres
            if len(text) <= 4000:
                await self.app.bot.send_message(chat_id=self.chat_id, text=text, parse_mode="HTML")
            else:
                # Dividir por blocos de ativos (🔹)
                parts = text.split("🔹")
                current_msg = parts[0]
                for part in parts[1:]:
                    if len(current_msg) + len(part) + 2 > 4000:
                        await self.app.bot.send_message(chat_id=self.chat_id, text=current_msg, parse_mode="HTML")
                        current_msg = "🔹" + part
                    else:
                        current_msg += "🔹" + part
                if current_msg:
                    await self.app.bot.send_message(chat_id=self.chat_id, text=current_msg, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Erro ao enviar mensagem: {e}")
            # Tentar enviar sem formatação se falhar
            try:
                await self.app.bot.send_message(chat_id=self.chat_id, text=text[:4000])
            except: pass

    async def run_scan(self, is_manual=False):
        if self.scan_lock.locked():
            logger.warning("Scan já em curso. A ignorar novo pedido.")
            return

        async with self.scan_lock:
            # Verificar reset diário de notificações
            today = datetime.now(LISBON_TZ).date()
            if today > self.last_reset_date:
                logger.info("Novo dia detetado. A limpar memória de notificações.")
                self.notified_touches = set()
                self.notified_breakouts = set()
                self.last_reset_date = today

            logger.info("A iniciar scan dinâmico...")
            
            self.market_regime = "🟢 <b>MERCADO SAUDÁVEL (Risk-On)</b>"
            try:
                # 1. Verificar Regime de Mercado (SPY)
                import yfinance as yf
                spy = yf.Ticker("SPY")
                spy_data = spy.history(period="5d", interval="60m")
                if not spy_data.empty:
                    spy_price = spy_data['Close'].iloc[-1]
                    spy_ema20 = spy_data['Close'].ewm(span=20, adjust=False).mean().iloc[-1]
                    if spy_price < spy_ema20:
                        self.market_regime = "⚠️ <b>MERCADO EM QUEDA (Risk-Off)</b>"
                        logger.warning("Mercado em queda (SPY < EMA20).")
                
                # 2. Obter Universo Dinâmico (S&P 500 + Nasdaq 100 + ETFs + Watchlist)
                loop = asyncio.get_running_loop()
                full_universe = await loop.run_in_executor(None, self.scanner.get_dynamic_universe)
                full_universe = list(set(full_universe) | self.user_watchlist)
                
                # 3. Filtrar por Top Liquidez (500 ativos)
                filtered_universe = await loop.run_in_executor(None, self.scanner.filter_by_liquidity, full_universe, 500)
                
                # 3. Analisar ativos em paralelo (com semáforo para evitar bloqueios)
                current_signals = {}
                total_to_analyze = len(filtered_universe)
                logger.info(f"A iniciar análise paralela de {total_to_analyze} ativos...")
                
                semaphore = asyncio.Semaphore(15) # Máximo de 15 análises simultâneas
                progress_msg = None
                if is_manual:
                    progress_msg = await self.app.bot.send_message(chat_id=self.chat_id, text="⏳ Progresso: 0%")

                async def semi_analyze(ticker, index):
                    async with semaphore:
                        try:
                            res = await loop.run_in_executor(None, self.scanner.analyze, ticker)
                            if index % 50 == 0 and progress_msg:
                                pct = int((index / total_to_analyze) * 100)
                                await progress_msg.edit_text(f"⏳ Progresso: {pct}% ({index}/{total_to_analyze})")
                            return ticker, res
                        except Exception as e:
                            logger.error(f"Erro em {ticker}: {e}")
                            return ticker, None

                tasks = [semi_analyze(t, i) for i, t in enumerate(filtered_universe)]
                results = await asyncio.gather(*tasks)
                
                for ticker, res in results:
                    if res:
                        current_signals[ticker] = res
                
                if progress_msg:
                    await progress_msg.delete()

                self.last_scan_time = datetime.now(LISBON_TZ) # Heartbeat
                now = datetime.now(LISBON_TZ).strftime("%d/%m/%Y %H:%M")
            except Exception as e:
                logger.error(f"Erro crítico no scan: {e}")
                await self.send_direct_msg(f"❌ *ERRO CRÍTICO NO SCAN:* {str(e)[:200]}")
                return
        current_tickers = set(current_signals.keys())
        new_tickers = current_tickers - self.last_scan_tickers
        new_breakouts = {t for t, s in current_signals.items() if s['breakout_2h'] and t not in self.active_breakouts}
        
        self.last_scan_tickers = current_tickers
        self.active_breakouts = {t for t, s in current_signals.items() if s['breakout_2h']}
        self.active_signals = current_signals # Guardar para monitorização de toques
        # REMOVIDO: self.notified_touches = set() -> Agora o reset é diário no topo do run_scan

        msg = ""
        
        # Função para calcular pontuação de ranking (Prioridade: Estrelas > RS)
        def get_rank_score(s):
            import numpy as np
            # Critério 1: Estrelas (Peso 1000 para garantir que 5 estrelas > 4 estrelas sempre)
            stars = s.get('stars', 1)
            
            # Critério 2: RS Setorial (Desempate)
            rs = s.get('rs_sector', 1.0)
            if rs is None or (isinstance(rs, float) and np.isnan(rs)): rs = 1.0
            
            return (stars * 1000) + (rs * 10)

        if is_manual:
            header = f"🔍 <b>Scan Completo ({len(filtered_universe)} de {len(full_universe)} ativos)</b>\n{self.market_regime}\n🕒 {now}\n"
            await self.send_direct_msg(header)
            
            if not current_signals:
                await self.send_direct_msg("Nenhuma ação cumpre os critérios no momento.")
            else:
                sorted_signals = sorted(current_signals.values(), key=get_rank_score, reverse=True)
                for s in sorted_signals:
                    await self.send_direct_msg(self._format_signal(s))
                    await asyncio.sleep(0.3) # Delay para evitar rate limit
        else:
            if new_tickers or new_breakouts:
                header = f"🔔 <b>Atualização Importante</b> — {now}\n━━━━━━━━━━━━━━━━━━━━\n"
                await self.send_direct_msg(header)
                
                if new_tickers:
                    await self.send_direct_msg("🌟 <b>Novos Ativos na Lista:</b>")
                    sorted_new = sorted([current_signals[t] for t in new_tickers], key=get_rank_score, reverse=True)
                    for s in sorted_new:
                        await self.send_direct_msg(self._format_signal(s))
                        await asyncio.sleep(0.3)

                if new_breakouts:
                    await self.send_direct_msg("\n🚀 <b>Rompimentos 2h Detetados:</b>")
                    sorted_breakouts = sorted([current_signals[t] for t in new_breakouts], key=get_rank_score, reverse=True)
                    for s in sorted_breakouts:
                        if s['ticker'] in new_tickers:
                            await self.send_direct_msg(f"🔹 <b>{s['ticker']}</b> também confirmou rompimento!")
                        else:
                            await self.send_direct_msg(self._format_signal(s))
                        await asyncio.sleep(0.3)
            else:
                logger.info("Nenhuma atualização importante encontrada.")
        
        if progress_msg:
            try: await progress_msg.delete()
            except: pass

    def _format_signal(self, s):
        div_status = "✅ Sim" if s['div_bullish'] else "❌ Não"
        vcp_status = "✅ Sim" if s['is_vcp'] else "❌ Não"
        break_status = "🚀 <b>ROMPIMENTO 2H!</b>" if s['breakout_2h'] else ""
        
        # Sistema de Estrelas
        stars = "⭐" * s.get('stars', 1)
        
        # Alerta de Exaustão
        stretch_msg = "\n⚠️ <b>ATIVO ESTICADO (Risco de Pullback)</b>" if s.get('is_stretched') else ""
        
        ticker = html.escape(str(s['ticker']))
        sector_etf = html.escape(str(s['sector_etf']))
        
        support_msg = ""
        if s.get('key_supports'):
            relevant_supports = s['key_supports']
            if relevant_supports:
                support_msg = "🛡️ <b>Zonas de Interesse (Clica para ver):</b>\n<tg-spoiler>"
                for sup in relevant_supports:
                    confluences = []
                    if sup.get('conf_ema200'): confluences.append("EMA 200 🎯")
                    if sup.get('conf_ema70'): confluences.append("EMA 70 🛡️")
                    if sup.get('conf_fib'): confluences.append("Golden Pocket 📐")
                    if sup.get('conf_avwap'): confluences.append("Institucional 🏛️")
                    
                    conf_text = f" ({' + '.join(confluences)})" if confluences else ""
                    icon = "🔥 " if sup.get('is_zone') else "└ "
                    support_msg += f"   {icon}{html.escape(sup['type'])}: <b>${sup['price']}</b> (a {sup['dist']}%){conf_text}\n"
                support_msg += "</tg-spoiler>"

        return (f"🔹 <b>{ticker}</b> {stars} @ <code>${s['price']}</code> {break_status}{stretch_msg}\n"
                f"   RS/Setor ({sector_etf}): <code>{s['rs_sector']}</code>\n"
                f"   Divergência (4h): {div_status} | VCP: {vcp_status}\n"
                f"{support_msg}"
                f"   ATR%: <code>{s['atr_pct']}%</code> | RSI D: <code>{s['rsi_daily']}</code>")

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

    async def cmd_scan(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("🔍 *A iniciar scan completo...*")
        await self.run_scan(is_manual=True)

    async def support_monitor_loop(self):
        """Monitoriza toques em suporte a cada 5 minutos para os ativos da lista."""
        logger.info("Monitorização de toques em suporte iniciada (5 min).")
        while True:
            try:
                if not self.active_signals:
                    await asyncio.sleep(300)
                    continue

                loop = asyncio.get_running_loop()
                for ticker, s in list(self.active_signals.items()):
                    # Obter preço atual rápido
                    import yfinance as yf
                    tk = yf.Ticker(ticker)
                    current_data = tk.history(period="1d", interval="1m")
                    if current_data.empty: continue
                    
                    current_price = float(current_data['Close'].iloc[-1])
                    
                    # Obter histórico diário para suportes
                    daily_data = tk.history(period="1y", interval="1d")
                    supports = await loop.run_in_executor(None, self.scanner.get_key_supports, ticker, current_price, daily_data)
                    
                    for sup in supports:
                        # Notificar apenas se for VIRGEM e estiver muito próximo (< 0.2%)
                        if sup['virgin'] and sup['dist'] <= 0.2:
                            touch_key = f"{ticker}_{sup['type']}_{sup['price']}"
                            if touch_key not in self.notified_touches:
                                # 1. Confirmação de Reversão 30m (Mínima e Máxima Superior)
                                is_reversal = await loop.run_in_executor(None, self.scanner.check_reversal_30m, ticker)
                                if not is_reversal:
                                    logger.info(f"{ticker} tocou suporte mas aguarda confirmação de vela 30m.")
                                    continue

                                # 2. Confirmação de Volume (Volume Spike > 1.5x média 20min)
                                vol_spike = False
                                try:
                                    avg_vol = current_data['Volume'].iloc[-21:-1].mean()
                                    last_vol = current_data['Volume'].iloc[-1]
                                    if last_vol > (avg_vol * 1.5):
                                        vol_spike = True
                                except: pass
                                
                                vol_msg = "✅ <b>Defesa Institucional (Volume Spike!)</b>" if vol_spike else "⚠️ Sem pico de volume"
                                
                                conf_list = []
                                if sup.get('conf_ema200'): conf_list.append("EMA 200 🎯")
                                if sup.get('conf_ema70'): conf_list.append("EMA 70 🛡️")
                                if sup.get('conf_fib'): conf_list.append("Golden Pocket 📐")
                                if sup.get('conf_avwap'): conf_list.append("Institucional 🏛️")
                                conf_msg = f"🌟 <b>Confluência Detetada: {' + '.join(conf_list)}</b>" if conf_list else ""
                                
                                current_price_fmt = round(current_price, 2)
                                ticker_esc = html.escape(ticker)
                                type_esc = html.escape(sup['type'])
                                price_val = sup['price']
                                
                                alert = (f"🎯 <b>ZONA DE COMPRA - Suporte Confirmado (30m)!</b>\n"
                                         f"🔥 <b>{ticker_esc}</b> @ <code>${current_price_fmt}</code> encostou em: <b>{type_esc} (${price_val})</b>\n"
                                         f"✅ <b>Confirmação 30m:</b> High/Low Superior\n"
                                         f"{vol_msg}\n"
                                         f"{conf_msg}\n"
                                         f"   RS/Setor: <code>{s['rs_sector']}</code> | RSI D: <code>{s['rsi_daily']}</code>")
                                
                                await self.send_direct_msg(alert)
                                self.notified_touches.add(touch_key)
                self.last_support_check_time = datetime.now(LISBON_TZ) # Heartbeat
            except Exception as e:
                logger.error(f"Erro no monitor de suportes: {e}")
            
            await asyncio.sleep(300) # Verificar a cada 5 minutos

    async def breakout_monitor_loop(self):
        """Monitoriza rompimentos 2h a cada 15 minutos para ativos na lista."""
        logger.info("Monitorização de rompimentos iniciada (15 min).")
        while True:
            try:
                if not self.active_signals:
                    await asyncio.sleep(900)
                    continue

                loop = asyncio.get_running_loop()
                for ticker, s in list(self.active_signals.items()):
                    if ticker in self.notified_breakouts: continue

                    import yfinance as yf
                    tk = yf.Ticker(ticker)
                    h1_data = tk.history(period="5d", interval="60m")
                    if h1_data.empty: continue

                    is_breakout = await loop.run_in_executor(None, self.scanner._check_breakout_2h, h1_data)
                    
                    if is_breakout:
                        ticker_esc = html.escape(ticker)
                        alert = (f"🚀 <b>ALERTA DE ROMPIMENTO 2H!</b>\n"
                                 f"🔥 <b>{ticker_esc}</b> rompeu a resistência recente!\n"
                                 f"   Preço: <code>${round(h1_data['Close'].iloc[-1], 2)}</code>\n"
                                 f"   RS/Setor: <code>{s['rs_sector']}</code> | RSI D: <code>{s['rsi_daily']}</code>\n"
                                 f"🔗 Analisa o gráfico antes de entrar!")
                        
                        await self.send_direct_msg(alert)
                        self.notified_breakouts.add(ticker)
                        await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"Erro no monitor de rompimentos: {e}")
            
            await asyncio.sleep(900) # Verificar a cada 15 minutos

    async def scheduler_loop(self):
        logger.info("Monitorização contínua (2h) com universo dinâmico.")
        # Pequeno delay inicial para não colidir com o post_init
        await asyncio.sleep(60) 
        while True:
            await self.run_scan(is_manual=False)
            await asyncio.sleep(7200)

    async def watchdog_loop(self):
        """Monitor de saúde: Alerta se os loops pararem."""
        logger.info("Watchdog de saúde iniciado.")
        while True:
            await asyncio.sleep(900) # Verificar a cada 15 minutos
            now = datetime.now(LISBON_TZ)
            
            # 1. Verificar Scan (2h normal, alertar se > 3h)
            scan_diff = (now - self.last_scan_time).total_seconds() / 3600
            if scan_diff > 3.0:
                await self.send_direct_msg(f"⚠️ *AVISO DE SAÚDE:* O scan automático não é concluído há {round(scan_diff, 1)} horas! Possível bloqueio.")
                self.last_scan_time = now # Reset para evitar spam
            
            # 2. Verificar Monitor de Suportes (5 min normal, alertar se > 20 min)
            sup_diff = (now - self.last_support_check_time).total_seconds() / 60
            if sup_diff > 20.0:
                await self.send_direct_msg(f"⚠️ *AVISO DE SAÚDE:* O monitor de suportes está inativo há {round(sup_diff, 0)} minutos!")
                self.last_support_check_time = now

    async def post_init(self, application):
        await self.send_direct_msg("🟢 *Bot Pro Iniciado!* (Universo Dinâmico Ativo)\n_A preparar o primeiro scan..._")
        # Iniciar o primeiro scan com is_manual=True para mostrar o progresso ao utilizador
        asyncio.create_task(self.run_scan(is_manual=True))
        # Iniciar loops de agendamento
        asyncio.create_task(self.scheduler_loop())
        asyncio.create_task(self.support_monitor_loop())
        asyncio.create_task(self.breakout_monitor_loop())
        asyncio.create_task(self.watchdog_loop())

    def run(self):
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("scan", self.cmd_scan))
        self.app.add_handler(CommandHandler("add", self.cmd_add))
        self.app.add_handler(CommandHandler("remove", self.cmd_remove))
        self.app.add_handler(CommandHandler("watchlist", self.cmd_watchlist))
        self.app.post_init = self.post_init
        
        # Usar a forma recomendada para v20+ em ambientes com loops ativos
        import nest_asyncio
        nest_asyncio.apply()
        self.app.run_polling(drop_pending_updates=True, close_loop=False)

if __name__ == "__main__":
    bot = StockBot()
    bot.run()
