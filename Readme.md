# Binance Futures Trading Bot

<div align="center">

![Python](https://img.shields.io/badge/python-v3.8+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Binance](https://img.shields.io/badge/exchange-Binance%20Futures-yellow.svg)
![Status](https://img.shields.io/badge/status-active-success.svg)

*A full-stack algorithmic trading system for Binance Futures — multi-timeframe signal engine, intelligence-gated entries, Kelly Criterion sizing, news-driven auto-trading, ATR-based risk management, Telegram alerts, and a live terminal-style web UI.*

</div>

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the Bot](#running-the-bot)
- [Web UI Tabs](#web-ui-tabs)
- [API Endpoints](#api-endpoints)
- [Risk Management](#risk-management)
- [Intelligence Engine](#intelligence-engine)
- [Telegram Notifications](#telegram-notifications)
- [Security](#security)
- [Disclaimer](#disclaimer)

---

## Features

### Web UI (Terminal-Style Dashboard)
- Live BTC / ETH / SOL price tickers in the header, updated every 15 seconds
- Nine tabs: **ML Analytics**, **Signal Engine**, **Scanner**, **Trade Stats**, **News**, **Live Stream**, **Journal**, **SOUL**, **Kelly**
- System log panel with ALL / INFO / WARN / ERR filters and live tail
- Status bar: connection status, API key status, risk state, last action

### Intelligence Engine
- SQLite-backed persistent memory (`data/intelligence.db`) that survives restarts
- **SOUL** — configurable personality gates: skip volatile TIER_2 signals, skip adverse regimes, minimum confidence thresholds
- **Trade Journal** — every closed trade is recorded with entry/exit/PnL/regime/confidence for future learning
- **Lesson extraction** — automatically flags consecutive losses and low-confidence patterns
- **SOUL.md** — human-readable narrative of the bot's learned trading personality, editable from the dashboard

### Signal Quality Tiers
| Tier | Score | HTF Confirmed | Regime | Action |
|------|-------|---------------|--------|--------|
| TIER_1 | ≥ 80 | Yes | TRENDING / NEUTRAL | Emitted — full Kelly size |
| TIER_2 | ≥ 65 | Any | Any | Emitted — half Kelly size (unless SOUL gate blocks) |
| TIER_3 | < 65 | — | — | Near-miss recorded only, no trade |

### Kelly Criterion Position Sizing
- Half-Kelly formula: `f = (edge / odds) × 0.5`
- Confidence scaling: size × (confidence / 100)
- Drawdown multiplier: reduces size when equity is below peak
- Hard cap at 5% of equity per trade
- Requires 20+ historical trades to activate; falls back to ATR sizing before then

### Signal Engine
- Multi-timeframe confluence analysis (primary TF + confirmation TF)
- Indicators: **RSI**, **MACD**, **Bollinger Bands**, **ATR**, **Supertrend**, **VWAP**, **ADX**, **StochRSI**
- Confidence score (0–100%) gating at configurable threshold (default 65%)
- ATR-based stop-loss and take-profit calculation
- Funding rate bias overlay (positive funding → SHORT bias, negative → LONG bias)

### Market Scanner
- Scan up to 10 symbols simultaneously with one click
- Funding rates table: 8-hour rate, annualized APR, market bias per symbol
- MTF signal scan table: direction, confidence, price, top confluence factor
- Selectable primary TF and confirmation TF before scanning

### News Auto-Trade
- Monitors 15+ RSS feeds (CoinDesk, CoinTelegraph, The Block, Decrypt, Blockworks, etc.)
- Opt-in via `NEWS_ENGINE=true` env var — disabled by default to keep RAM usage low
- NLP keyword scoring: each headline scored for bullish/bearish sentiment per symbol
- Automatically opens a futures position when score exceeds threshold
- Per-symbol cooldown (120s) prevents duplicate signals from the same article batch
- Memory-safe: capped connection pool, explicit GC after each poll, RSS guard pauses polling if process exceeds `NEWS_ENGINE_MEM_MB` (default 400MB)

### Order Types
| Type | Description |
|------|-------------|
| **Market** | Instant execution at current market price |
| **Limit** | Precise entry/exit at a specific price |
| **OCO** | One-Cancels-Other: profit target + stop loss in one shot |
| **Stop-Limit** | Conditional execution with price protection |
| **TWAP** | Time-Weighted Average Price — splits large orders into N parts over T seconds |

### Risk Manager
- **Per-trade risk**: size positions to risk exactly X% of equity (default 1%)
- **Daily loss limit**: halt trading if daily P&L drops below threshold (default 5%)
- **Max drawdown guard**: halt if equity drops >10% from peak
- **Max open positions**: hard cap on concurrent trades (default 10)
- **Min R:R ratio**: reject trades below minimum risk/reward (default 1.5)
- **Trailing stop**: ATR-based ratchet stop that follows the position
- State persists to `logs/risk_state.json` — survives restarts within the same day

### Trade Tracker
- SQLite-backed trade journal (`logs/trades.db`)
- Equity curve endpoint for charting P&L over time
- Trade Stats tab: total trades, win rate, avg P&L, open positions, equity chart

### Telegram Notifications
- Signal alerts (symbol, direction, confidence, entry/SL/TP)
- Order filled confirmations
- Trade closed summaries with P&L
- Error alerts
- Daily summary at 23:55 UTC (total trades, daily P&L, open positions)

### Security
- Rate limiting on all endpoints (slowapi)
- Input validation and symbol whitelisting
- API keys loaded exclusively from environment variables — never logged, never returned by API
- Sanitized error responses (no stack traces exposed to clients)

---

## Architecture

```
Browser (index.html)
        │  fetch / WebSocket (/ws, /ws/log)
        ▼
  FastAPI  (api.py)  ── port 8000
        │
        ├── SignalEngine       (src/signal_engine.py)    multi-TF confluence + signal tiers
        ├── IntelligenceEngine (src/intelligence.py)     SOUL gates, Kelly sizing, journal
        ├── NewsEngine         (src/news_engine.py)      RSS + NLP scoring (opt-in)
        ├── RiskManager        (src/risk_manager.py)     ATR sizing + Kelly override
        ├── TradeTracker       (src/trade_tracker.py)    SQLite trade journal
        ├── TelegramNotifier   (src/notifications.py)    async Telegram alerts
        ├── StrategyEngine     (src/strategy_engine.py)  auto-scan loop
        └── Binance SDK        (binance-futures-connector)
```

---

## Project Structure

```
binance-trading-bot/
├── api.py                        # FastAPI backend — all endpoints + auto-trade loop
├── config.json                   # Symbols, risk params, TWAP defaults, Telegram config
├── requirements.txt
├── frontend/
│   └── index.html                # Single-file terminal web UI (9 tabs)
├── src/
│   ├── signal_engine.py          # Multi-TF confluence signal generator + signal tiers
│   ├── intelligence.py           # IntelligenceEngine: SOUL, Kelly, journal, lessons
│   ├── news_engine.py            # RSS feed fetcher + NLP scorer (memory-safe)
│   ├── risk_manager.py           # ATR sizing + Kelly override, drawdown guard
│   ├── trade_tracker.py          # SQLite trade journal + equity curve
│   ├── notifications.py          # Telegram async notifier
│   ├── strategy_engine.py        # Symbol scan loop (strategy auto-mode)
│   ├── market_orders.py          # CLI market order placer
│   ├── limit_orders.py           # CLI limit order placer
│   ├── bot.py                    # CLI orchestrator (legacy)
│   └── advanced/
│       ├── oco.py                # OCO order logic
│       ├── stop_limit_orders.py  # Stop-limit logic
│       └── twap.py               # TWAP execution engine
├── data/
│   ├── intelligence.db           # SQLite intelligence memory (auto-created)
│   └── SOUL.md                   # Bot trading personality (auto-generated, editable)
├── logs/
│   ├── trades.db                 # SQLite trade journal (auto-created)
│   ├── risk_state.json           # Daily risk state (auto-created)
│   └── bot.log                   # Application log
└── tests/
    ├── test_intelligence.py
    ├── test_signal_tiers.py
    └── backtesting/
```

---

## Installation

### Prerequisites

- Python 3.8+
- Binance Futures account with API keys

### 1. Clone the repo

```bash
git clone https://github.com/samarth080/the-ultimate-binance-trading-bot.git
cd the-ultimate-binance-trading-bot
```

### 2. Create and activate a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate        # macOS / Linux
# venv\Scripts\activate         # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

---

## Configuration

### .env file

Create a `.env` file in the project root:

```env
# Binance API
BINANCE_API_KEY=your_api_key_here
BINANCE_SECRET_KEY=your_secret_key_here

# Set to false for live trading (true = testnet)
USE_TESTNET=true

# Telegram (optional — leave blank to disable notifications)
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Risk overrides (optional — defaults shown)
RISK_PER_TRADE_PCT=0.01
MAX_DAILY_LOSS_PCT=0.05
DRAWDOWN_HALT_PCT=0.10
MAX_OPEN_POSITIONS=10
MIN_RR_RATIO=1.5

# News engine — disabled by default, enable to poll RSS feeds
NEWS_ENGINE=false

# News engine RAM guard — pause polling if process RSS exceeds this (MB)
NEWS_ENGINE_MEM_MB=400
```

### config.json

Key sections:

```json
{
  "strategy": {
    "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", ...],
    "primary_tf": "5m",
    "confirm_tf": "1h",
    "scan_interval_seconds": 60
  },
  "risk": {
    "risk_per_trade_pct": 0.01,
    "max_daily_loss_pct": 0.03,
    "drawdown_halt_pct": 0.10,
    "max_open_positions": 3,
    "min_rr_ratio": 1.5,
    "atr_stop_multiplier": 1.6,
    "atr_tp_multiplier": 2.8,
    "trailing_atr_mult": 1.2
  },
  "twap": {
    "default_parts": 5,
    "default_interval": 60
  }
}
```

### Telegram setup

1. Message [@BotFather](https://t.me/BotFather) on Telegram → `/newbot` → copy the token
2. Message [@userinfobot](https://t.me/userinfobot) → copy your chat ID
3. Add both to `.env` as shown above

---

## Running the Bot

```bash
# Start with news engine disabled (recommended for low RAM usage)
uvicorn api:app --host 0.0.0.0 --port 8000 --reload

# Start with news engine enabled
NEWS_ENGINE=true uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

Then open [http://localhost:8000](http://localhost:8000) in your browser.

---

## Web UI Tabs

### ML Analytics
- Select symbol and timeframe, click **ANALYZE**
- Returns RSI, MACD, Bollinger Bands, ATR, Supertrend, VWAP, ADX, StochRSI values
- Shows buy/sell/neutral signal for each indicator

### Signal Engine
- Select symbol, primary TF, confirmation TF, click **RUN ANALYSIS**
- Returns overall direction (LONG / SHORT / FLAT), confidence %, and the list of confluence reasons
- Shows ATR-based stop-loss and take-profit levels
- Signals are classified into TIER_1 / TIER_2 / TIER_3 based on score and HTF confirmation

### Scanner
- Click **SCAN ALL** to scan all configured symbols in parallel
- Top table: funding rates per symbol — rate, annualized APR, market bias
- Bottom table: MTF signal per symbol — direction, confidence, price, top factor
- Change timeframes using the dropdowns before scanning

### Trade Stats
- Win rate, total trades, average P&L, current open positions
- Equity curve chart (line chart of cumulative P&L over time)

### News
- Live feed from 15+ crypto news sources (requires `NEWS_ENGINE=true`)
- Each article scored for bullish/bearish sentiment per symbol
- **Auto-Trade** toggle: when enabled, high-confidence news signals open real positions

### Live Stream
- Real-time structured event log streamed over WebSocket (`/ws/log`)
- Filter by event type: ALL / SIGNAL / TRADE / ERROR
- Live tail of bot decisions as they happen

### Journal
- Full history of every closed trade recorded by the Intelligence Engine
- Entry price, exit price, P&L, tier, confidence, regime, and lessons learned per trade

### SOUL
- View and edit the bot's trading personality (`data/SOUL.md`)
- Gates visible: `skip_volatile_tier2`, `skip_regimes`, `min_confidence`
- Changes take effect on the next signal evaluation

### Kelly
- Current Kelly Criterion parameters derived from trade history
- Win rate, average win/loss, computed Kelly fraction, half-Kelly size
- Requires 20+ historical trades; shows "insufficient data" until then

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/status` | Server health, API key presence, testnet mode |
| GET | `/api/ml/analyze` | Run ML indicator analysis for a symbol |
| GET | `/api/signal` | Run MTF signal engine for a symbol |
| GET | `/api/signal/scan_multi` | Scan multiple symbols simultaneously |
| GET | `/api/funding` | Funding rates + market bias for symbol list |
| GET | `/api/prices` | Lightweight multi-symbol price fetch |
| GET | `/api/positions/live` | Live open positions from Binance exchange |
| GET | `/api/stats` | Trade statistics (win rate, P&L, open positions) |
| GET | `/api/stats/equity_curve` | Equity curve data for charting |
| GET | `/api/risk/status` | Current risk manager state |
| GET | `/api/news` | Latest news articles with sentiment scores |
| GET | `/api/news/signals` | High-confidence news-driven signals |
| GET | `/api/journal` | Full trade journal from Intelligence Engine |
| GET | `/api/soul` | Current SOUL.md content and parsed gates |
| POST | `/api/soul` | Update SOUL.md content |
| GET | `/api/kelly` | Current Kelly Criterion parameters and sizing |
| GET | `/api/logs` | Last N lines of system log |
| POST | `/api/order/market` | Place a market order |
| POST | `/api/order/limit` | Place a limit order |
| POST | `/api/order/oco` | Place an OCO order |
| POST | `/api/order/stop_limit` | Place a stop-limit order |
| POST | `/api/order/twap` | Start a TWAP execution |
| POST | `/api/news/auto_trade` | Trigger news-based auto-trade evaluation |
| WS | `/ws` | Live price + signal WebSocket stream |
| WS | `/ws/log` | Structured event log stream (signals, trades, errors) |

---

## Risk Management

The `RiskManager` (`src/risk_manager.py`) enforces five rules on every trade:

1. **Position sizing** — risk exactly `RISK_PER_TRADE_PCT` of current equity per trade, using ATR stop distance to back-calculate quantity. Overridden by Kelly sizing once 20+ trades are recorded.
2. **Daily loss limit** — if cumulative daily P&L falls below `MAX_DAILY_LOSS_PCT × equity`, all trading halts for the rest of the day
3. **Drawdown guard** — if equity falls more than `DRAWDOWN_HALT_PCT` from its all-time peak, trading halts
4. **Open position cap** — no new trades if `open_positions >= MAX_OPEN_POSITIONS`
5. **Minimum R:R** — trades with `TP distance / SL distance < MIN_RR_RATIO` are rejected before any order is sent

State is persisted to `logs/risk_state.json` so limits survive server restarts within the same trading day.

---

## Intelligence Engine

The `IntelligenceEngine` (`src/intelligence.py`) provides persistent memory and adaptive sizing:

### SOUL Gates
Edit `data/SOUL.md` or use the SOUL tab in the dashboard to configure:
- `skip_volatile_tier2: true` — skip TIER_2 signals during high-volatility regimes
- `skip_regimes: [VOLATILE]` — list of market regimes to avoid entirely
- `min_confidence: 70` — minimum confidence score required to enter a trade

### Kelly Criterion
After 20+ closed trades are recorded, the bot switches from fixed ATR sizing to half-Kelly:
```
kelly_fraction = (win_rate × avg_win - loss_rate × avg_loss) / avg_win × 0.5
position_usdt  = equity × kelly_fraction × (confidence / 100) × drawdown_multiplier
```
Capped at 5% of equity per trade regardless of Kelly output.

### Trade Journal
Every closed trade is saved with: symbol, direction, tier, confidence, entry/exit price, PnL, regime, and any lessons extracted. Viewable in the Journal tab or via `/api/journal`.

---

## Telegram Notifications

When `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set in `.env`, the bot sends:

- **Signal alert** — when a news-driven signal passes confidence threshold
- **Order filled** — symbol, direction, entry price, SL, TP, quantity, risk amount
- **Trade closed** — symbol, exit price, P&L in USDT
- **Error alert** — if an auto-trade attempt fails
- **Daily summary** — sent at 23:55 UTC: trades today, daily P&L, open positions

All Telegram calls are fire-and-forget (daemon threads) — a Telegram outage never blocks order execution.

---

## Security

- All API keys are loaded from environment variables only — never hardcoded, never returned by any endpoint
- Rate limiting applied to all endpoints via `slowapi` (configurable via env vars)
- All symbol and interval inputs are validated against a whitelist before being used in any Binance API call
- Error responses return sanitized messages only — no Python tracebacks exposed to the client
- `USE_TESTNET=true` by default — you must explicitly set it to `false` to trade on mainnet

---

## Disclaimer

**This software is for educational and research purposes only. Cryptocurrency trading carries a high level of risk and may not be suitable for all investors. Past performance is not indicative of future results. Never trade with funds you cannot afford to lose. The authors are not responsible for any financial losses incurred through the use of this software.**

Always test thoroughly on Binance Testnet (`USE_TESTNET=true`) before enabling live trading.

---

<div align="center">
Built with love by samarth and udai
</div>
