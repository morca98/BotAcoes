import logging
import os
import sys
import asyncio
import json
import html
from datetime import datetime
import pytz
import pandas_market_calendars as mcal
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import InvalidToken
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
        self.token = os.getenv("TELEGRAM_TOKEN") or self.config.TELEGRAM_TOKEN
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID") or self.config.TELEGRAM_CHAT_ID

        # Memória e Watchlist
        self.last_scan_tickers = set()
        self.active_breakouts = set()
        self.active_signals = {} # Tickers que passaram no último scan
        # Evita alertas falsos de entrada/saída quando o fornecedor devolve dados instáveis.
        self.pending_new_tickers = set()
        self.announced_tickers = set()
        self.pending_breakouts = set()
        self.announced_breakouts = set()
        self.notified_touches = set() # Evitar spam de toques (Diário)
        self.notified_breakouts = set() # Evitar spam de rompimentos (Diário)
        self.last_reset_date = datetime.now(LISBON_TZ).date()
        self.user_watchlist = self._load_watchlist()
        
        # Monitorização de Saúde (Watchdog)
        self.last_scan_time = datetime.now(LISBON_TZ)
        self.last_support_check_time = datetime.now(LISBON_TZ)
        self.scan_lock = asyncio.Lock() # Evitar scans simultâneos
        self.signal_history = [] # Guardar os últimos 5 sinais
        self.recent_supports = {} # Ticker -> {'time': datetime, 'type': str, 'price': float}
        self.recent_breakouts = {} # Ticker -> {'time': datetime, 'price': float}
        
        self.market_calendar_cache = {}
        self.initial_scan_completed = False
        self.app = ApplicationBuilder().token(self.token).build()

    def _get_market_calendar_code(self, ticker: str) -> str:
        """Devolve o calendário oficial da bolsa do ticker monitorizado."""
        ticker = ticker.upper()
        european_calendars = {
            ".PA": "XPAR", ".DE": "XETR", ".L": "LSE", ".MI": "XMIL",
            ".AS": "XAMS", ".BR": "XBRU", ".MC": "XMAD", ".LS": "XLIS",
            ".SW": "XSWX", ".ST": "XSTO", ".CO": "XCSE", ".OL": "XOSL",
            ".HE": "XHEL", ".VI": "XWBO", ".IR": "XDUB", ".WA": "XWAR",
            ".LU": "XLUX", ".AT": "ASEX", ".TA": "TASE"
        }
        return next((calendar for suffix, calendar in european_calendars.items() if ticker.endswith(suffix)), "NYSE")

    def _is_regular_market_open(self, ticker: str, now_utc=None) -> bool:
        """Valida sessão regular; exclui pre-market, after-hours, fins de semana e feriados."""
        try:
            now_utc = now_utc or datetime.now(pytz.UTC)
            if now_utc.tzinfo is None:
                now_utc = pytz.UTC.localize(now_utc)
            else:
                now_utc = now_utc.astimezone(pytz.UTC)

            calendar_code = self._get_market_calendar_code(ticker)
            cache_key = (calendar_code, now_utc.date().isoformat())
            if cache_key not in self.market_calendar_cache:
                calendar = mcal.get_calendar(calendar_code)
                schedule = calendar.schedule(start_date=now_utc.date(), end_date=now_utc.date())
                if schedule.empty:
                    self.market_calendar_cache[cache_key] = None
                else:
                    self.market_calendar_cache[cache_key] = (
                        schedule.iloc[0]["market_open"].to_pydatetime(),
                        schedule.iloc[0]["market_close"].to_pydatetime()
                    )

            session = self.market_calendar_cache[cache_key]
            return bool(session and session[0] <= now_utc <= session[1])
        except Exception as exc:
            logger.warning(f"Não foi possível validar a sessão de {ticker}: {exc}")
            # Falha fechada: não são enviados alertas quando não há confirmação de sessão.
            return False

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
        """Envia texto HTML em blocos de linhas, sem cortar tags ou perder conteúdo."""
        lines = text.splitlines(keepends=True) or [text]
        chunks, current = [], ""
        for line in lines:
            if len(line) > 3800:
                # Mensagens criadas pelo bot não devem atingir este caso; preserva o texto em blocos.
                if current:
                    chunks.append(current)
                    current = ""
                chunks.extend(line[i:i + 3800] for i in range(0, len(line), 3800))
            elif current and len(current) + len(line) > 3800:
                chunks.append(current)
                current = line
            else:
                current += line
        if current:
            chunks.append(current)

        for chunk in chunks:
            try:
                await self.app.bot.send_message(chat_id=self.chat_id, text=chunk, parse_mode="HTML")
            except Exception as exc:
                logger.error("Erro ao enviar mensagem HTML: %s", exc)
                try:
                    await self.app.bot.send_message(chat_id=self.chat_id, text=html.unescape(chunk))
                except Exception as fallback_exc:
                    logger.error("Erro ao enviar mensagem simples: %s", fallback_exc)

    async def send_alert_with_buttons(self, text: str, ticker: str):
        """Envia alerta com botão de acesso direto ao TradingView."""
        try:
            # Limpar sufixos do yfinance para TradingView (ex: SAP.DE -> ETR:SAP ou simplesmente manter ticker)
            tv_symbol = ticker.replace('-', '').replace('.L', '').replace('.DE', '').replace('.PA', '').replace('.AS', '')
            tv_url = f"https://www.tradingview.com/chart/?symbol={tv_symbol}"
            
            keyboard = [[InlineKeyboardButton("📈 Ver no TradingView", url=tv_url)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await self.app.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode="HTML",
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Error sending alert with buttons: {e}")
            await self.send_direct_msg(text)

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

            progress_msg = None

            async def update_scan_progress(text):
                nonlocal progress_msg
                if not is_manual:
                    return
                try:
                    if progress_msg is None:
                        progress_msg = await self.app.bot.send_message(chat_id=self.chat_id, text=text)
                    else:
                        await progress_msg.edit_text(text)
                except Exception as exc:
                    logger.warning("Não foi possível atualizar o progresso do scan: %s", exc)

            self.market_regime = "🟢 <b>MERCADO SAUDÁVEL (Risk-On)</b>"
            try:
                await update_scan_progress("⏳ Scan 1/4: a calcular o regime de mercado...")
                # 1. Verificar Regime de Mercado (SPY) e Market Breadth (Saúde Interna)
                import yfinance as yf
                loop = asyncio.get_running_loop()
                spy = yf.Ticker("SPY")
                spy_data = spy.history(period="5d", interval="60m")

                # Um só pedido de lote substitui 30 pedidos individuais ao Yahoo.
                breadth_sample = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "JPM", "V", "UNH", "XOM", "LLY", "JNJ", "MA", "PG", "HD", "COST", "MRK", "ABBV", "PEP", "KO", "ADBE", "WMT", "BAC", "CRM", "MCD", "ACN", "NFLX", "AMD", "QCOM"]

                def fetch_breadth_batch():
                    return yf.download(
                        breadth_sample, period="3mo", interval="1d", group_by="ticker",
                        threads=False, progress=False, auto_adjust=False,
                    )

                above_ema50_count = 0
                total_checked = 0
                try:
                    breadth_data = await loop.run_in_executor(None, fetch_breadth_batch)
                    for sample_t in breadth_sample:
                        try:
                            close_series = breadth_data[sample_t]["Close"].dropna()
                            if len(close_series) >= 50:
                                ema50 = close_series.ewm(span=50, adjust=False).mean().iloc[-1]
                                if close_series.iloc[-1] > ema50:
                                    above_ema50_count += 1
                                total_checked += 1
                        except (KeyError, TypeError):
                            continue
                except Exception as e:
                    logger.warning("Breadth indisponível neste ciclo: %s", e)

                if total_checked >= 15:
                    breadth_pct = above_ema50_count / total_checked * 100
                    breadth_str = f" | Breadth (EMA50): <b>{breadth_pct:.0f}%</b>"
                else:
                    breadth_pct = None
                    breadth_str = " | Breadth (EMA50): <b>indisponível</b>"
                    logger.warning("Breadth indisponível: cobertura insuficiente (%s/%s).", total_checked, len(breadth_sample))

                if not spy_data.empty:
                    spy_price = spy_data['Close'].iloc[-1]
                    spy_ema20 = spy_data['Close'].ewm(span=20, adjust=False).mean().iloc[-1]
                    if spy_price < spy_ema20 or (breadth_pct is not None and breadth_pct < 45):
                        self.market_regime = f"⚠️ <b>MERCADO EM QUEDA / FRÁGIL (Risk-Off)</b>{breadth_str}"
                        logger.warning("Mercado frágil. Breadth: %s", f"{breadth_pct:.1f}%" if breadth_pct is not None else "indisponível")
                    else:
                        self.market_regime = f"🟢 <b>MERCADO SAUDÁVEL (Risk-On)</b>{breadth_str}"

                # 2. Obter Universo Dinâmico (S&P 500 + Nasdaq 100 + ETFs + Watchlist)
                await update_scan_progress("⏳ Scan 2/4: a preparar o universo EUA + STOXX 600...")
                full_universe = await loop.run_in_executor(None, self.scanner.get_dynamic_universe)
                full_universe = list(set(full_universe) | self.user_watchlist)

                # 3. Filtrar pelos ativos mais líquidos para manter um ciclo sustentável.
                await update_scan_progress(
                    f"⏳ Scan 3/4: a selecionar os {self.config.MAX_SCAN_ASSETS} ativos mais líquidos..."
                )
                filtered_universe = await loop.run_in_executor(
                    None, self.scanner.filter_by_liquidity, full_universe, self.config.MAX_SCAN_ASSETS
                )

                # 4. Pré-carregar Benchmarks (Evitar concorrência de pedidos ao mesmo ETF)
                await update_scan_progress("⏳ Scan 4/4: a carregar benchmarks e filtros técnicos...")
                await loop.run_in_executor(None, self.scanner.preload_benchmarks)

                # 5. Analisar ativos em paralelo (com semáforo para evitar bloqueios)
                current_signals = {}
                total_to_analyze = len(filtered_universe)
                logger.info(f"A iniciar análise paralela de {total_to_analyze} ativos...")
                
                # Duas análises simultâneas e espaçamento global reduzem a pressão no Yahoo.
                semaphore = asyncio.Semaphore(2)
                await update_scan_progress(f"⏳ Análise técnica: 0% (0/{total_to_analyze})")

                analyzed_count = 0
                request_pacer = asyncio.Lock()
                last_request_started = 0.0
                rate_limit_until = 0.0

                async def semi_analyze(ticker, index):
                    nonlocal analyzed_count, last_request_started, rate_limit_until
                    async with semaphore:
                        try:
                            # Espaçamento entre inícios de análise: evita rajadas de pedidos.
                            async with request_pacer:
                                now_monotonic = loop.time()
                                wait_for_cooldown = max(0.0, rate_limit_until - now_monotonic)
                                wait_for_pacing = max(0.0, 0.5 - (now_monotonic - last_request_started))
                                if wait_for_cooldown or wait_for_pacing:
                                    await asyncio.sleep(max(wait_for_cooldown, wait_for_pacing))
                                last_request_started = loop.time()
                            res = await loop.run_in_executor(None, self.scanner.analyze, ticker)
                            return ticker, res
                        except Exception as e:
                            error_str = str(e)
                            if "Too Many Requests" in error_str or "429" in error_str:
                                async with request_pacer:
                                    rate_limit_until = max(rate_limit_until, loop.time() + 60)
                                logger.warning("Rate limit detetado. Pausa global de 60s ativada.")
                            logger.error(f"Erro em {ticker}: {e}")
                            return ticker, None
                        finally:
                            analyzed_count += 1
                            if analyzed_count % 10 == 0 or analyzed_count == total_to_analyze:
                                pct = int((analyzed_count / total_to_analyze) * 100)
                                await update_scan_progress(
                                    f"⏳ Análise técnica: {pct}% ({analyzed_count}/{total_to_analyze})"
                                )

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
        raw_new_tickers = current_tickers - self.last_scan_tickers
        raw_new_breakouts = {t for t, s in current_signals.items() if s['breakout_2h'] and t not in self.active_breakouts}

        # Só comunicamos movimentos quando a bolsa desse ativo está em sessão regular.
        # À noite, em fins de semana e feriados, fornecedores podem atualizar/corrigir barras já
        # fechadas. Essas alterações não representam uma nova oportunidade negociável.
        market_open_tickers = {ticker for ticker in current_tickers if self._is_regular_market_open(ticker)}

        # Os ativos vistos fora da sessão ficam pendentes. Serão anunciados apenas se ainda
        # cumprirem todos os critérios quando a respetiva bolsa voltar a abrir.
        self.pending_new_tickers.update(raw_new_tickers - market_open_tickers)
        self.pending_new_tickers.intersection_update(current_tickers)
        confirmed_deferred_tickers = self.pending_new_tickers & market_open_tickers
        new_tickers = ((raw_new_tickers & market_open_tickers) | confirmed_deferred_tickers) - self.announced_tickers
        self.pending_new_tickers.difference_update(new_tickers)
        self.announced_tickers.update(new_tickers)

        self.pending_breakouts.update(raw_new_breakouts - market_open_tickers)
        self.pending_breakouts.intersection_update(current_tickers)
        confirmed_deferred_breakouts = self.pending_breakouts & market_open_tickers
        new_breakouts = ((raw_new_breakouts & market_open_tickers) | confirmed_deferred_breakouts) - self.announced_breakouts
        self.pending_breakouts.difference_update(new_breakouts)
        self.announced_breakouts.update(new_breakouts)
        
        self.last_scan_tickers = current_tickers
        self.active_breakouts = {t for t, s in current_signals.items() if s['breakout_2h']}
        self.active_signals = current_signals # Guardar para monitorização de toques
        # REMOVIDO: self.notified_touches = set() -> Agora o reset é diário no topo do run_scan

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
                summary_lines = [f"📋 <b>Ativos Detetados ({len(sorted_signals)}):</b>\n"]
                for s in sorted_signals:
                    stars = "⭐" * s.get('stars', 1)
                    summary_lines.append(f"🔹 <b>{s['ticker']}</b> {stars} @ <code>${s['price']}</code> | RS: {s['rs_sector']} | RSI D: {s['rsi_daily']}")
                summary_lines.append("\n💡 <i>Usa /analisar [TICKER] para ver a ficha técnica completa e suportes (ex: /analisar GE)</i>")
                
                # Enviar em blocos por linha para evitar cortar tags HTML a meio
                current_chunk = []
                current_length = 0
                for line in summary_lines:
                    line_len = len(line) + 1
                    if current_length + line_len > 3800:
                        await self.send_direct_msg("\n".join(current_chunk))
                        current_chunk = [line]
                        current_length = line_len
                    else:
                        current_chunk.append(line)
                        current_length += line_len
                if current_chunk:
                    await self.send_direct_msg("\n".join(current_chunk))
        else:
            if new_tickers or new_breakouts:
                header = f"🔔 <b>Atualização Importante</b> — {now}\n━━━━━━━━━━━━━━━━━━━━\n"
                await self.send_direct_msg(header)
                
                if new_tickers:
                    summary_new = ["🌟 <b>Novos Ativos na Lista:</b>"]
                    sorted_new = sorted([current_signals[t] for t in new_tickers], key=get_rank_score, reverse=True)
                    
                    # Análise de Correlação Setorial (Aviso de Exposição Elevada)
                    sector_counts = {}
                    for s in sorted_new:
                        sec = s.get('sector_etf', 'UNKNOWN')
                        sector_counts[sec] = sector_counts.get(sec, 0) + 1
                    overexposed = [sec for sec, cnt in sector_counts.items() if cnt >= 3]
                    if overexposed:
                        summary_new.append(f"⚠️ <b>Alerta de Concentração:</b> Exposição elevada em <code>{', '.join(overexposed)}</code>.")

                    for s in sorted_new:
                        stars = "⭐" * s.get('stars', 1)
                        summary_new.append(f"🔹 <b>{s['ticker']}</b> {stars} @ <code>${s['price']}</code>")
                    summary_new.append("\n💡 <i>Usa /analisar [TICKER] para ver detalhes completos.</i>")
                    await self.send_direct_msg("\n".join(summary_new))

                if new_breakouts:
                    summary_break = ["🚀 <b>Rompimentos 2h Detetados:</b>"]
                    sorted_breakouts = sorted([current_signals[t] for t in new_breakouts], key=get_rank_score, reverse=True)
                    for s in sorted_breakouts:
                        summary_break.append(f"🔹 <b>{s['ticker']}</b> @ <code>${s['price']}</code>")
                    summary_break.append("\n💡 <i>Usa /analisar [TICKER] para ver detalhes completos.</i>")
                    await self.send_direct_msg("\n".join(summary_break))
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

        earnings_days = s.get('earnings_days')
        earnings_msg = ""
        if earnings_days is not None:
            if earnings_days <= 3:
                earnings_msg = f"\n⚠️ <b>RISCO DE EARNINGS:</b> Resultados em {earnings_days} dias!"
            else:
                earnings_msg = f"\n📅 <b>Earnings:</b> a {earnings_days} dias"

        return (f"🔹 <b>{ticker}</b> {stars} @ <code>${s['price']}</code> {break_status}{stretch_msg}{earnings_msg}\n"
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
        help_text = (
            "🚀 <b>BOT PRO ATIVO!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🤖 <b>Comandos Disponíveis:</b>\n"
            "🔹 /lista - Ver todos os ativos monitorizados\n"
            "🔹 /sinais - Ver os últimos 5 sinais disparados\n"
            "🔹 /analisar <code>TICKER</code> - Ver ficha técnica completa (ex: /analisar GE)\n"
            "🔹 /scan - Iniciar scan manual completo\n"
            "🔹 /watchlist - Ver a tua lista pessoal\n"
            "🔹 /add <code>TICKER</code> - Adicionar à watchlist\n"
            "🔹 /remove <code>TICKER</code> - Remover da watchlist\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Scan automático a cada 2h | Monitorização 15m</i>"
        )
        await update.message.reply_text(help_text, parse_mode="HTML")

    async def cmd_lista(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Mostra o total de ativos e os nomes organizados por mercado."""
        if not self.active_signals:
            await update.message.reply_text("A lista está vazia. Aguarda pela conclusão do primeiro scan.")
            return
        
        tickers = sorted(self.active_signals.keys())
        eu_tickers = [t for t in tickers if any(t.endswith(x) for x in [".DE", ".PA", ".L", ".LS", ".MC", ".MI", ".AS", ".SW", ".ST", ".CO", ".OL", ".HE", ".VI", ".BR", ".IR", ".WA", ".LU", ".AT", ".TA"])]
        us_tickers = [t for t in tickers if t not in eu_tickers]
        
        msg = (
            f"📋 <b>ATIVOS MONITORIZADOS ({len(tickers)})</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🇺🇸 <b>EUA ({len(us_tickers)}):</b>\n"
            f"<code>{', '.join(us_tickers[:100])}</code>"
        )
        if len(us_tickers) > 100: msg += "..."
        
        if eu_tickers:
            msg += (
                f"\n\n🇪🇺 <b>EUROPA ({len(eu_tickers)}):</b>\n"
                f"<code>{', '.join(eu_tickers[:100])}</code>"
            )
            if len(eu_tickers) > 100: msg += "..."
            
        msg += f"\n━━━━━━━━━━━━━━━━━━━━\n{self.market_regime}"
        
        await self.send_direct_msg(msg)

    async def cmd_sinais(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Mostra os últimos 5 sinais disparados."""
        if not self.signal_history:
            await update.message.reply_text("Ainda não foram disparados sinais hoje.")
            return
        
        msg = "🎯 <b>ÚLTIMOS 5 SINAIS DISPARADOS</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        for s in reversed(self.signal_history):
            time_str = s['time'].strftime("%H:%M")
            msg += (
                f"🕒 <code>{time_str}</code> | <b>{s['ticker']}</b>\n"
                f"🔹 {s['type']} | {s['score_bar']}\n"
                f"💰 Preço: <code>${s['price']}</code>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
            )
        
        await update.message.reply_text(msg, parse_mode="HTML")

    async def cmd_analisar(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Analisa um ativo específico e retorna a ficha técnica completa."""
        if not context.args:
            await update.message.reply_text("Uso: /analisar TICKER (ex: /analisar GE)")
            return
        
        ticker = context.args[0].upper()
        signal = self.active_signals.get(ticker)
        
        if not signal:
            await update.message.reply_text(f"⏳ A analisar <b>{ticker}</b> em detalhe...", parse_mode="HTML")
            loop = asyncio.get_running_loop()
            signal = await loop.run_in_executor(None, self.scanner.analyze, ticker)
            if signal:
                self.active_signals[ticker] = signal
            else:
                await update.message.reply_text(f"❌ O ativo <b>{ticker}</b> não cumpre os critérios técnicos no momento ou é inválido.", parse_mode="HTML")
                return

        msg = self._format_signal(signal)
        tv_url = f"https://www.tradingview.com/chart/?symbol={ticker}"
        keyboard = [[InlineKeyboardButton("📈 Ver no TradingView", url=tv_url)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=reply_markup)

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
                    if not self._is_regular_market_open(ticker):
                        continue
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
                                # 1. Confirmação de Reversão 15m (Mínima e Máxima Superior)
                                is_reversal = await loop.run_in_executor(None, self.scanner.check_reversal_15m, ticker)
                                if not is_reversal:
                                    logger.info(f"{ticker} tocou suporte mas aguarda confirmação de vela 15m.")
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
                                conf_count = 0
                                if sup.get('conf_ema200'): 
                                    conf_list.append("EMA 200 🎯")
                                    conf_count += 1
                                if sup.get('conf_ema70'): 
                                    conf_list.append("EMA 70 🛡️")
                                    conf_count += 1
                                if sup.get('conf_fib'): 
                                    conf_list.append("Golden Pocket 📐")
                                    conf_count += 1
                                if sup.get('conf_avwap'): 
                                    conf_list.append("Institucional 🏛️")
                                    conf_count += 1
                                
                                # 3. Verificar Liderança no Pullback (RS Momentum)
                                pullback_leadership = False
                                try:
                                    asset_h1 = tk.history(period="5d", interval="60m")
                                    bench_symbol = "EXSA.DE" if any(ticker.endswith(x) for x in [".DE", ".PA", ".L", ".LS", ".MC", ".MI", ".AS", ".SW", ".ST", ".CO", ".OL", ".HE", ".VI", ".BR", ".IR", ".WA", ".LU", ".AT", ".TA"]) else "SPY"
                                    bench_h1 = yf.Ticker(bench_symbol).history(period="5d", interval="60m")
                                    pullback_leadership = await loop.run_in_executor(None, self.scanner._check_pullback_leadership, asset_h1, bench_h1)
                                except: pass

                                rs_msg = "⚡ <b>Liderança no Pullback (Resiliência Forte)</b>" if pullback_leadership else ""

                                # Barra de Força (Escala de 1 a 6 com base nas confluências, volume, divergência e momentum)
                                total_points = conf_count + (1 if vol_spike else 0) + (1 if s.get('div_bullish') else 0) + (1 if pullback_leadership else 0)
                                strength_score = min(6, max(1, total_points))
                                strength_bar = "🟢" * strength_score + "⚪" * (6 - strength_score)
                                
                                conf_msg = f"🌟 <b>Confluência: {' + '.join(conf_list)}</b>" if conf_list else ""
                                
                                current_price_fmt = round(current_price, 2)
                                ticker_esc = html.escape(ticker)
                                type_esc = html.escape(sup['type'])
                                price_val = sup['price']
                                
                                alert = (f"🎯 <b>ZONA DE COMPRA - Suporte Confirmado (15m)!</b>\n"
                                         f"🔥 <b>{ticker_esc}</b> @ <code>${current_price_fmt}</code> encostou em: <b>{type_esc} (${price_val})</b>\n"
                                         f"📊 <b>Barra de Força:</b> {strength_bar} ({strength_score}/6)\n"
                                         f"✅ <b>Confirmação 15m:</b> High/Low Superior\n"
                                         f"{vol_msg}\n"
                                         f"{rs_msg}\n"
                                         f"{conf_msg}\n"
                                         f"   RS/Setor: <code>{s['rs_sector']}</code> | RSI D: <code>{s['rsi_daily']}</code>")
                                
                                if strength_score <= 1:
                                    logger.info(f"Alerta ignorado para {ticker}: Força 1/6 (abaixo do limiar mínimo)")
                                    continue

                                now_time = datetime.now(LISBON_TZ)
                                await self.send_alert_with_buttons(alert, ticker)
                                logger.info(f"Alerta enviado para {ticker} com força {strength_score}/6")
                                self.signal_history.append({
                                    'ticker': ticker, 'type': 'Suporte',
                                    'score_bar': strength_bar, 'price': current_price_fmt,
                                    'time': now_time
                                })
                                if len(self.signal_history) > 5:
                                    self.signal_history.pop(0)

                                self.recent_supports[ticker] = {
                                    'time': now_time,
                                    'type': sup['type'],
                                    'price': sup['price']
                                }
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
                    if not self._is_regular_market_open(ticker):
                        continue
                    if ticker in self.notified_breakouts: continue

                    import yfinance as yf
                    tk = yf.Ticker(ticker)
                    h1_data = tk.history(period="5d", interval="60m")
                    if h1_data.empty: continue

                    is_breakout = await loop.run_in_executor(None, self.scanner._check_breakout_2h, h1_data)
                    
                    if is_breakout:
                        # Obter dados diários para os detalhes ricos
                        daily_data = tk.history(period="1y", interval="1d")
                        details = await loop.run_in_executor(None, self.scanner.get_breakout_details, h1_data, daily_data)
                        
                        current_price = float(h1_data['Close'].iloc[-1])
                        ticker_esc = html.escape(ticker)
                        
                        # 1. Calcular Score de Rompimento
                        pullback_leadership = False
                        try:
                            bench_symbol = "EXSA.DE" if any(ticker.endswith(x) for x in [".DE", ".PA", ".L", ".LS", ".MC", ".MI", ".AS", ".SW", ".ST", ".CO", ".OL", ".HE", ".VI", ".BR", ".IR", ".WA", ".LU", ".AT", ".TA"]) else "SPY"
                            bench_h1 = yf.Ticker(bench_symbol).history(period="5d", interval="60m")
                            pullback_leadership = await loop.run_in_executor(None, self.scanner._check_pullback_leadership, h1_data, bench_h1)
                        except: pass

                        # Score de 4 Pontos para Rompimento:
                        # 1. Base Breakout (1)
                        # 2. Volume Spike > 1.2x (+1)
                        # 3. VCP Pattern (+1)
                        # 4. Pullback Leadership (+1)
                        b_score = 1
                        vol_spike = details['vol_ratio'] > 1.2
                        is_vcp = details['is_vcp']

                        if vol_spike: b_score += 1
                        if is_vcp: b_score += 1
                        if pullback_leadership: b_score += 1
                        
                        strength_bar = "🟢" * b_score + "⚪" * (4 - b_score)
                        
                        vol_status = "✅ <b>Forte (Volume > Média)</b>" if vol_spike else "⚠️ Moderado"
                        vcp_status = "✅ <b>Detetado (Contração Estreita)</b>" if is_vcp else "❌ Não"
                        
                        conf_list_b = []
                        if vol_spike: conf_list_b.append("Volume Spike 📊")
                        if is_vcp: conf_list_b.append("VCP Spring ⚡")
                        if pullback_leadership: conf_list_b.append("Liderança 🏆")
                        
                        conf_msg_b = f"🌟 <b>Confluência: {' + '.join(conf_list_b)}</b>" if conf_list_b else ""
                        
                        # 2. Verificar se é um Sinal Combinado (Combo Suporte + Rompimento)
                        combo_msg = ""
                        header = "🚀 <b>ALERTA DE ROMPIMENTO 2H!</b>"
                        if ticker in self.recent_supports:
                            sup_info = self.recent_supports[ticker]
                            time_diff = (datetime.now(LISBON_TZ) - sup_info['time']).total_seconds() / 3600
                            if time_diff <= 48: # Janela de 48 horas
                                header = "🎯 <b>CONFLUÊNCIA EXTREMA (Combo)</b>"
                                combo_msg = (f"\n⚡ <b>Impulso de Reversão Detetado!</b>\n"
                                             f"   └ Este ativo defendeu o suporte <b>{sup_info['type']}</b> (${sup_info['price']}) nas últimas {int(time_diff)}h.")

                        alert = (f"{header}\n"
                                 f"🔥 <b>{ticker_esc}</b> rompeu a resistência recente!\n"
                                 f"📊 <b>Barra de Força:</b> {strength_bar} ({b_score}/4)\n"
                                 f"   Preço: <code>${round(current_price, 2)}</code>\n"
                                 f"{combo_msg}\n\n"
                                 f"📊 <b>Métricas de Explosão:</b>\n"
                                 f"   └ <b>Volume:</b> {vol_status} (<code>{details['vol_ratio']}x</code>)\n"
                                 f"   └ <b>Padrão VCP:</b> {vcp_status}\n"
                                 f"   └ <b>Distância do Breakout:</b> <code>+{details['dist_pct']}%</code>\n\n"
                                 f"{conf_msg_b}\n\n"
                                 f"🎯 <b>Próximo Alvo:</b> <code>${details['target']}</code> (Resistência)\n"
                                 f"🏢 <b>Setor:</b> RS <code>{s['rs_sector']}</code> | RSI D: <code>{s['rsi_daily']}</code>")
                        
                        if b_score > 1:
                            await self.send_alert_with_buttons(alert, ticker)
                            logger.info(f"Breakout enviado para {ticker} com força {b_score}/4")
                            
                            now_time = datetime.now(LISBON_TZ)
                            # Registar rompimento recente para combo simétrico
                            self.recent_breakouts[ticker] = {
                                'time': now_time,
                                'price': round(current_price, 2)
                            }

                            # Adicionar ao histórico (Tipo Combo ou Rompimento)
                            sig_type = "🎯 Combo" if "CONFLUÊNCIA" in header else "🚀 Rompimento"
                            self.signal_history.append({
                                'ticker': ticker, 'type': sig_type, 
                                'score_bar': strength_bar, 'price': round(current_price, 2),
                                'time': now_time
                            })
                            if len(self.signal_history) > 5: self.signal_history.pop(0)
                        else:
                            logger.info(f"Breakout ignorado para {ticker}: Força 1/4")
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
        startup_msg = (
            "🚀 <b>BOT PRO: READY FOR ACTION</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🎯 <b>Foco:</b> Reversões em Suporte & Breakouts 2H\n"
            "⚡ <b>Gatilho:</b> Confirmação 15m + Volume Spike\n"
            "📈 <b>Interface:</b> TradingView Integrado\n\n"
            "🔍 <i>A iniciar scan de alta precisão...</i>"
        )
        await self.send_direct_msg(startup_msg)
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
        self.app.add_handler(CommandHandler("lista", self.cmd_lista))
        self.app.add_handler(CommandHandler("sinais", self.cmd_sinais))
        self.app.add_handler(CommandHandler("analisar", self.cmd_analisar))
        self.app.post_init = self.post_init
        
        # Usar a forma recomendada para v20+ em ambientes com loops ativos
        import nest_asyncio
        nest_asyncio.apply()
        try:
            self.app.run_polling(drop_pending_updates=True, close_loop=False)
        except InvalidToken:
            logger.critical(
                "A credencial Telegram foi rejeitada. Atualiza a variável Telegram no Railway e faz novo deploy."
            )
            raise SystemExit(1)

if __name__ == "__main__":
    bot = StockBot()
    bot.run()
