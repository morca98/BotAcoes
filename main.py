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
        self.active_signals = {} # Tickers que passaram no último scan
        self.notified_touches = set() # Evitar spam de toques
        self.user_watchlist = self._load_watchlist()
        
        # Monitorização de Saúde (Watchdog)
        self.last_scan_time = datetime.now(LISBON_TZ)
        self.last_support_check_time = datetime.now(LISBON_TZ)
        
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
        
        try:
            # 1. Obter Universo Dinâmico (S&P 500 + Nasdaq 100 + ETFs + Watchlist)
            loop = asyncio.get_running_loop()
            full_universe = await loop.run_in_executor(None, self.scanner.get_dynamic_universe)
            full_universe = list(set(full_universe) | self.user_watchlist)
            
            # 2. Filtrar por Top Liquidez (500 ativos)
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
        self.notified_touches = set() # Resetar memória de toques no novo scan

        msg = ""
        
        # Função para calcular pontuação de ranking
        def get_rank_score(s):
            # Peso principal: RS Setorial
            score = s['rs_sector'] * 10
            # Bónus por indicadores positivos
            if s['is_vcp']: score += 5
            if s['div_bullish']: score += 3
            if s['breakout_2h']: score += 10
            return score

        if is_manual:
            msg = f"🔍 *Scan Completo ({len(filtered_universe)} de {len(full_universe)} ativos)* — {now}\n"
            if not current_signals:
                msg += "Nenhuma ação cumpre os critérios no momento."
            else:
                # Ordenar por score de ranking (descendente)
                sorted_signals = sorted(current_signals.values(), key=get_rank_score, reverse=True)
                
                # OTIMIZAÇÃO: Suportes já calculados no Scanner.analyze
                for s in sorted_signals:
                    msg += self._format_signal(s)
        else:
            if new_tickers or new_breakouts:
                msg = f"🔔 *Atualização Importante* — {now}\n━━━━━━━━━━━━━━━━━━━━\n"
                if new_tickers:
                    msg += "🌟 *Novos Ativos na Lista (Ordenados por Força):*\n"
                    sorted_new = sorted([current_signals[t] for t in new_tickers], key=get_rank_score, reverse=True)
                    for s in sorted_new:
                        msg += self._format_signal(s)

                if new_breakouts:
                    msg += "\n🚀 *Rompimentos 2h Detetados:*\n"
                    sorted_breakouts = sorted([current_signals[t] for t in new_breakouts], key=get_rank_score, reverse=True)
                    for s in sorted_breakouts:
                        if s['ticker'] in new_tickers:
                            msg += f"🔹 *{s['ticker']}* também confirmou rompimento!\n"
                        else:
                            msg += self._format_signal(s)
            else:
                logger.info("Nenhuma atualização importante encontrada.")
                return

        if msg:
            await self.send_direct_msg(msg)

    def _format_signal(self, s):
        div_status = "✅ Sim" if s['div_bullish'] else "❌ Não"
        vcp_status = "✅ Sim" if s['is_vcp'] else "❌ Não"
        break_status = "🚀 *ROMPIMENTO 2H!*" if s['breakout_2h'] else ""
        
        support_msg = ""
        if s.get('key_supports'):
            virgin_supports = [sup for sup in s['key_supports'] if sup.get('virgin')]
            if virgin_supports:
                support_msg = "🛡️ *Suportes Virgens Próximos:*\n"
                for sup in virgin_supports:
                    confluences = []
                    if sup.get('conf_ema'): confluences.append("EMA 200 🎯")
                    if sup.get('conf_fib'): confluences.append("FIB 61.8% 📐")
                    conf_text = f" (Confluência: {' + '.join(confluences)})" if confluences else ""
                    support_msg += f"   └ {sup['type']} Open: `${sup['price']}` (a {sup['dist']}%){conf_text}\n"

        return (f"🔹 *{s['ticker']}* @ `${s['price']}` {break_status}\n"
                f"   RS/Setor ({s['sector_etf']}): `{s['rs_sector']}`\n"
                f"   Divergência (4h): {div_status} | VCP: {vcp_status}\n"
                f"{support_msg}"
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
                    
                    # Verificar suportes (DO/WO)
                    supports = await loop.run_in_executor(None, self.scanner.get_key_supports, ticker, current_price)
                    
                    for sup in supports:
                        # Notificar apenas se for VIRGEM e estiver muito próximo (< 0.2%)
                        if sup['virgin'] and sup['dist'] <= 0.2:
                            touch_key = f"{ticker}_{sup['type']}_{sup['price']}"
                            if touch_key not in self.notified_touches:
                                # 1. Confirmação de Volume (Volume Spike > 1.5x média 20min)
                                vol_spike = False
                                try:
                                    avg_vol = current_data['Volume'].iloc[-21:-1].mean()
                                    last_vol = current_data['Volume'].iloc[-1]
                                    if last_vol > (avg_vol * 1.5):
                                        vol_spike = True
                                except: pass
                                
                                vol_msg = "✅ *Defesa Institucional (Volume Spike!)*" if vol_spike else "⚠️ Sem pico de volume"
                                
                                conf_list = []
                                if sup.get('conf_ema'): conf_list.append("EMA 200 🎯")
                                if sup.get('conf_fib'): conf_list.append("FIB 61.8% 📐")
                                conf_msg = f"🌟 *Confluência Detetada: {' + '.join(conf_list)}*" if conf_list else ""
                                
                                current_price_fmt = round(current_price, 2)
                                alert = (f"🎯 *ZONA DE COMPRA - Suporte Virgem Tocado! (< 0.2%)*\n"
                                         f"🔥 *{ticker}* @ `${current_price_fmt}` encostou em: *{sup['type']} Open (${sup['price']})*\n"
                                         f"   {vol_msg}\n"
                                         f"   {conf_msg}\n"
                                         f"   RS/Setor: `{s['rs_sector']}` | RSI D: `{s['rsi_daily']}`")
                                await self.send_direct_msg(alert.replace("\n   \n", "\n"))
                                self.notified_touches.add(touch_key)
                
                self.last_support_check_time = datetime.now(LISBON_TZ) # Heartbeat
            except Exception as e:
                logger.error(f"Erro no monitor de suportes: {e}")
            
            await asyncio.sleep(300) # Verificar a cada 5 minutos

    async def scheduler_loop(self):
        logger.info("Monitorização contínua (2h) com universo dinâmico.")
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
        # Agendar o primeiro scan com um pequeno delay para garantir que o bot está pronto
        loop = asyncio.get_event_loop()
        loop.call_later(5, lambda: asyncio.create_task(self.run_scan(is_manual=False)))
        # Iniciar loops de agendamento
        asyncio.create_task(self.scheduler_loop())
        asyncio.create_task(self.support_monitor_loop())
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
