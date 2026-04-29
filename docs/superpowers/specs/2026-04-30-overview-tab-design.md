# Overview Tab — Command Centre Design

**Date:** 2026-04-30  
**Status:** Approved  

---

## Goal

Add an Overview tab as the default landing screen of the BNCE//TERMINAL dashboard. One glance should tell the trader everything they need to know: account health, open positions, latest signal, and news sentiment — without switching tabs.

---

## Layout

Two-column layout within the existing centre panel (matching the current terminal aesthetic: dark background, IBM Plex Mono, green/red/amber palette).

### Left Column — Account Health + Risk

**Account Health panel** (top):
- KPI strip with 3 tiles: Daily PnL, Unrealised P&L, Win Rate
- Daily loss limit progress bar: shows % of max daily loss consumed, colour shifts green → amber → red as it approaches the 5% halt threshold
- Live badge: ACTIVE / HALTED sourced from `/api/risk/status`

**Risk Status panel** (below):
- 4 cells in a 2×2 grid: Open Positions (n/max), Drawdown %, Daily Loss %, Kelly Size (USDT)
- Sourced from `/api/risk/status` and `/api/kelly`

### Right Column — Positions + Signal + News

**Open Positions panel** (top):
- Header row + one row per open position: direction arrow, symbol, entry price, mark price, unrealised PnL
- Inline **CLOSE** button per row — fires a market close order via `POST /api/order/market` (same as the order panel, with `dry_run: false` and opposite side)
- Sourced from `/api/stats` (open_trades array) + live mark prices from `/api/prices`

**Latest Signal panel** (middle):
- Shows the most recent signal from `/api/signal/scan_multi` (cached, not re-run on every render)
- Fields: direction icon, symbol, timeframe pair, confluence %, R:R, SL, TP, age ("2 min ago")
- Inline **→ APPLY** button — switches to the Order panel tab and pre-fills symbol + side (same logic as the existing `applySignalToOrder()` function in app.js)
- If no signal: "No active signals · last scan X min ago"

**News Sentiment panel** (bottom):
- Aggregate sentiment badge: BULLISH / BEARISH / NEUTRAL + score
- Top 3 headlines with per-article sentiment badge and score
- Sourced from `/api/news?limit=3`

---

## Data & Refresh

| Source | Endpoint | Refresh |
|---|---|---|
| Daily PnL, positions, win rate | `/api/stats` | every 30 s |
| Risk status, drawdown, Kelly | `/api/risk/status` + `/api/kelly` | every 30 s |
| Mark prices (CLOSE button calc) | `/api/prices` | every 15 s (already polling) |
| Unrealised P&L | WebSocket `/ws` tick (`upnl`) | real-time |
| Latest signal | cached from last `/api/signal/scan_multi` call | on tab focus + every 5 min |
| News headlines | `/api/news?limit=3` | on tab focus + every 2 min |

All polling uses `setInterval` with staggered timers to avoid request bursts. Overview only polls while it is the active tab (`S.currentView === 'overview'`), same pattern used by existing tabs.

---

## Navigation

- Overview is the first tab and the default (`active`) on page load — replaces ML Analytics as the landing screen
- ML Analytics remains available as the second tab
- Clicking any panel section (e.g., the Positions panel header) navigates to the relevant full tab (Trade Stats, Signal Engine, News) — cosmetic click handler, no new API calls

---

## CLOSE Button Behaviour

1. User clicks CLOSE on a position row
2. Confirmation: `window.confirm("Close BTCUSDT LONG position?")` — simple browser confirm, no custom modal
3. On confirm: `POST /api/order/market` with `{ symbol, side: opposite, quantity: positionAmt, dry_run: false }`
4. Show inline result text (OK / error) on the row for 3 seconds, then reload the positions panel

---

## Implementation Scope

**Files changed:**
- `frontend/index.html` — add `#view-overview` section, move it to first tab position
- `frontend/app.js` — add `loadOverview()`, polling, CLOSE handler, APPLY wiring
- `frontend/style.css` — add `.overview-*` classes (kpi strip, loss bar, risk grid, positions table variant)

**No backend changes required.** All data comes from existing endpoints.

**No new dependencies.**

---

## Out of Scope

- Custom close modal (browser confirm is sufficient)
- Real-time per-position mark price via individual WebSocket streams (polling `/api/prices` every 15 s is adequate)
- Editing Kelly or risk parameters from the overview (navigate to the full tab for that)
