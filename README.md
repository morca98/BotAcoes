# 🤖 Stock Signal Bot MTF V3

Bot de análise técnica multi-timeframe para sinais de compra em 143 ativos (EUA, Portugal, Europa e Brasil).

---

## 📋 Estratégia — 5 Filtros Obrigatórios

| Filtro | Timeframe | Condição |
|--------|-----------|----------|
| 1 — RSI Macro | Semanal | RSI(14) < 50 (espaço para subida) |
| 2 — Tendência | Diário | Preço > SMA(70) |
| 3 — Pullback | 4 Horas | RSI(14) < 40 (sobrevenda) |
| 4 — Divergência | 4 Horas | Divergência Bullish MACD |
| 5 — Reversão | 4 Horas | Vela com Higher High + Higher Low |

Só gera sinal quando **todos os 5 filtros** estão satisfeitos.

---

## 💰 Gestão de Risco

| Parâmetro | Valor |
|-----------|-------|
| Risco por trade | 1% do capital |
| Rácio R:R | 1:3 |
| Breakeven | Move SL para entrada a +1% |
| Trailing Stop | Ativa a +2% |

---

## ⚙️ Instalação

### Pré-requisitos
- Python 3.11+
- Conta no Telegram
- Token de bot (via @BotFather)

### 1. Clonar / descarregar o projeto
```bash
cd stock_signal_bot
```

### 2. Instalar dependências
```bash
pip install -r requirements.txt
```

### 3. Configurar variáveis de ambiente
```bash
cp .env.example .env
# Edita o ficheiro .env com o teu token e chat_id
```

### 4. Iniciar o bot
```bash
python bot.py
```

---

## 🐳 Deploy com Docker

```bash
# Construir e iniciar
docker-compose up -d

# Ver logs
docker-compose logs -f

# Parar
docker-compose down
```

---

## 📱 Comandos Telegram

| Comando | Descrição |
|---------|-----------|
| `/start` | Iniciar bot e ver ajuda |
| `/status` | Estado atual do bot |
| `/scan` | Lançar scan manual |
| `/trades` | Últimos 5 sinais |
| `/capital [valor]` | Ver ou alterar capital |
| `/help` | Ajuda completa |

---

## 🏥 Health Check

O bot expõe `GET /health` na porta `8080`:

```bash
curl http://localhost:8080/health
# {"status": "ok", "uptime": "2:34:01", "bot": "Stock Signal Bot MTF V3"}
```

Usa o [UptimeRobot](https://uptimerobot.com) (gratuito) para monitorizar com alertas de 5 minutos.

---

## 📊 Ativos Monitorizados (143)

- **EUA**: 84 ações + 14 ETFs (S&P 500, Nasdaq, sectores)
- **Portugal**: 15 empresas do PSI (EDP, Galp, BCP, NOS...)
- **Europa**: 50 blue chips (ASML, LVMH, SAP, Nestlé, Shell...)
- **Brasil**: 20 empresas da B3 (Petrobras, Vale, Itaú...)

---

## ⚠️ Aviso Legal

Este bot é uma ferramenta de análise técnica para fins educativos e informativos. **Não constitui aconselhamento financeiro.** Trading envolve risco de perda de capital. Opera com responsabilidade.

---

## 📁 Estrutura do Projeto

```
stock_signal_bot/
├── bot.py           # Bot principal + comandos Telegram
├── scanner.py       # Motor de análise técnica (5 filtros)
├── risk_manager.py  # Gestão de risco e dimensionamento
├── notifier.py      # Formatação e envio de mensagens
├── health_server.py # Endpoint /health para uptime
├── config.py        # Configuração e watchlist
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── .env.example
```
