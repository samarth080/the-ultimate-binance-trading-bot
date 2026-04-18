# Intelligence Engine Upgrade — Design Spec
**Date:** 2026-04-18
**Status:** Approved

## Overview

Upgrade the Ultimate Binance Trading Bot with four interconnected improvements inspired by OpenTradex: an Intelligence Engine with persistent memory and self-learning, signal quality tiers, Kelly criterion position sizing, and four new dashboard tabs. The bot runs on Binance Futures testnet (with a path to mainnet). The existing tabbed React + FastAPI dashboard is extended — not replaced.

---

## Section 1: Intelligence Engine (`src/intelligence.py`)

A new module that owns the bot's long-term memory and self-tuning logic. Three responsibilities:

### 1.1 SOUL
- Loads `data/SOUL.md` on startup (created with defaults if missing)
- `SOUL.md` is a markdown file with sections: Identity, Risk Rules, Anti-Patterns, Regime Overrides
- `get_active_soul()` returns a gate dictionary merging static SOUL rules with the top 3 most recent auto-extracted lessons
- `strategy_engine.py` calls this once per cycle and injects the result into `SignalEngine`
- The UI (SOUL tab) renders editable fields backed by this file; changes take effect on next cycle with no restart

### 1.2 Trade Journal
- SQLite database at `data/intelligence.db` with three tables:
  - `trades` — one row per closed trade: symbol, direction, regime, tier, confidence, indicators_fired, entry_price, exit_reason, pnl, rr_actual, session_date, lesson
  - `near_misses` — TIER_3 signals that were skipped: symbol, regime, confidence, indicators, entry_price_at_skip, outcome_price (price 20 bars later, filled by background check), outcome (WIN/LOSS/PENDING — WIN if price moved ≥1×ATR in signal direction within 20 bars)
  - `lessons` — extracted lessons with timestamp, regime scope, rule text, trade count basis
- `record_close(trade)` writes to `trades` then immediately runs `_extract_lesson()`
- `_extract_lesson()` queries last 20 closed trades grouped by regime and generates lesson strings when patterns cross thresholds:
  - Win rate by regime — if VOLATILE win rate < 35%, lesson: "Enforce TIER_1 only in VOLATILE"
  - Exit reason distribution — if SL exits > 60% in a regime, lesson flags it
  - Trailing effectiveness — if TRAIL exits in TRENDING have win rate > 65%, lesson raises trail confidence gate
- Every 50 skipped signals, `_review_near_misses()` checks if >60% would have been profitable; flags threshold-too-strict lesson

### 1.3 Kelly Sizing
- `compute_kelly_size(equity, confidence, regime)` method
- Formula:
  ```
  edge  = win_rate × avg_win_r − loss_rate × avg_loss_r
  kelly = edge / avg_win_r
  f     = kelly × 0.5                    # half-Kelly haircut
  f     = f × (confidence / 100)         # scale by signal confidence
  f     = f × drawdown_multiplier        # 1.0 / 0.5 / 0.25 at 0/5/8% drawdown
  size  = min(equity × f, equity × 0.05) # hard cap at 5% per trade
  ```
- Requires minimum 20 closed trades in journal; falls back to existing 1%-risk sizing below that
- `kelly_active` flag set at init based on trade count

### 1.4 Startup Sequence
1. `IntelligenceEngine.__init__()` — loads SOUL.md, opens DB, checks trade count → sets `kelly_active`
2. Cycle start — `get_active_soul()` → gate dict injected into `SignalEngine`
3. Signal emitted → tier classified → SOUL gate checked → `compute_kelly_size()` called (if active)
4. Trade closes → `record_close()` → lesson extracted → DB updated

**Backward compatibility:** If `intelligence.db` missing, bot runs exactly as today. SOUL.md missing = no gates applied. Kelly activates automatically after 20 trades.

---

## Section 2: Signal Quality Tiers

Added to `src/signal_engine.py`. A `tier` field is added to the `Signal` dataclass.

### 2.1 Tier Classification

| Tier | Score | Criteria | Action |
|------|-------|----------|--------|
| TIER_1 | ≥ 80 | ≥4 indicators agree, HTF hard-confirms (HTF Supertrend explicitly agrees with direction), regime is TRENDING or NEUTRAL | Full Kelly size, trailing stop enabled |
| TIER_2 | 65–79 | 2–3 indicators agree, HTF soft-confirms (HTF Supertrend is neutral — not actively against direction) | Kelly size × 0.5 additional multiplier on top of confidence scaling, fixed TP |
| TIER_3 | 50–64 | Weak confluence, RANGING or VOLATILE regime | Skip — logged as near-miss |

### 2.2 Implementation
- New `_classify_tier(score, indicators_fired, htf_confirmed, regime)` function in `signal_engine.py`
- Returns `Tier` enum (TIER_1 / TIER_2 / TIER_3)
- Called after score computation, result stored on `Signal.tier`
- TIER_3 signals are never emitted to `strategy_engine` but are passed to `intel.record_near_miss()`

### 2.3 SOUL Gate
- Before emitting a signal, `analyse()` checks `intel.get_active_soul()` gate dict
- Gate can block: specific tiers in specific regimes, entries when drawdown threshold active, entries against strong news sentiment
- Blocked signals logged to the live stream with reason; not counted as near-misses

---

## Section 3: Kelly Criterion Position Sizing

Changes to `src/risk_manager.py` and `src/strategy_engine.py`.

### 3.1 RiskManager Changes
- `compute_position_size()` gains optional `kelly_usdt: float = None` parameter
- If provided and passes R:R gate, `kelly_usdt` overrides the ATR-derived quantity
- All existing guards (R:R check, drawdown halt, daily loss halt) still apply

### 3.2 Strategy Engine Changes
- After signal emitted, before sizing: call `intel.compute_kelly_size(equity, signal.confidence, signal.regime)`
- Pass result as `kelly_usdt` to `risk_manager.compute_position_size()`
- If Kelly not active (<20 trades), `kelly_usdt=None` → existing behavior unchanged

### 3.3 Sizing Safeguards
- Minimum 20 trades before Kelly activates
- Hard cap: 5% of equity per trade regardless of Kelly output
- Drawdown multipliers: 0% drawdown → 1.0×; ≥5% → 0.5×; ≥8% → 0.25×
- Confidence scaling: score 65 → 0.6×; score 100 → 1.0× (linear interpolation)
- TIER_2 additional multiplier: 0.5× applied after confidence scaling (so TIER_2 at score 72 → `f × 0.72 × 0.5`)

---

## Section 4: Learning Loop

### 4.1 Lesson Extraction Rules
Lessons are extracted by `_extract_lesson()` after every closed trade using rolling 20-trade windows per regime:

| Pattern | Threshold | Lesson Generated |
|---------|-----------|-----------------|
| VOLATILE win rate | < 35% | "Enforce TIER_1 only in VOLATILE" |
| SL exits in any regime | > 60% | "Stop distance too tight in {regime} — raise atr_stop_multiplier" |
| TRAIL exits win rate in TRENDING | > 65% | "Trail effective in TRENDING ADX>30 — lower confidence gate to 70" |
| Near-miss profitable rate | > 60% after 50 samples | "Confidence threshold may be too strict — consider lowering to 60" |

### 4.2 Lesson Application
- Top 3 most recent lessons (by timestamp) are included in `get_active_soul()` output
- `signal_engine.py` reads them as additional gates — they can override default thresholds
- Lessons are advisory, not destructive: they narrow entries but cannot disable the bot
- Manual override: SOUL.md `[override]` section can disable any specific lesson by name

### 4.3 SOUL.md Default Contents
```markdown
# Trading Soul

## Identity
Systematic crypto futures trader. Technical signals + regime awareness. No guessing.

## Risk Rules
- Max risk per trade: 1%
- Daily loss halt: 5%
- Drawdown halt: 10%
- Max open positions: 10
- Min R:R: 1.5

## Anti-Patterns
- Do not trade VOLATILE regime at TIER_2 or below
- Do not enter against funding rate > 0.1%
- Skip signals within 30 min of major news events

## Regime Overrides
# Add manual overrides here, e.g.:
# skip_regime: RANGING
```

---

## Section 5: Dashboard — Four New Tabs

Extends the existing React + FastAPI tab structure. Four new tab components added to `frontend/src/`.

### Tab 1: Live Signal Stream (`SignalStream.tsx`)
- WebSocket connection to `GET /api/stream` (existing WS log endpoint, extended)
- Scrolling log of every indicator check, regime classification, tier decision, SOUL gate verdict, and final entry/skip
- Each log line has a type badge: ENTRY (green) / SKIP (yellow) / GATED (orange) / ERROR (red)
- Filter buttons: ALL · ENTRIES ONLY · SKIPS · ERRORS
- Auto-scrolls; pause-on-hover

### Tab 2: Trade Journal (`TradeJournal.tsx`)
- Summary stats strip: win rate, avg R:R, trade count, Kelly active status
- Table: trade #, symbol, direction, regime, tier, confidence, exit reason, PnL, lesson
- Filterable by regime (TRENDING/RANGING/VOLATILE/NEUTRAL) and outcome (WIN/LOSS)
- Expandable rows showing full indicator list and lesson text
- Data from `GET /api/journal`

### Tab 3: SOUL Config (`SoulConfig.tsx`)
- Two panels side by side:
  - Left: editable Risk Rules (numeric inputs for risk%, daily halt%, drawdown%, min R:R, max positions)
  - Right: read-only Active Lessons list (auto-derived, timestamped, regime-scoped)
- Save button PATCHes `POST /api/soul` which writes back to `data/SOUL.md`
- Changes reflected on next strategy cycle (no restart required)

### Tab 4: Kelly Sizing (`KellySizing.tsx`)
- Three metric cards: Kelly f*, Half-Kelly %, Next trade size in USDT
- Stats breakdown table: win rate, avg win R, avg loss R, edge, drawdown multiplier, confidence scalar
- "Kelly active" vs "Warming up (N/20 trades)" status indicator
- Data from `GET /api/kelly`

### New API Endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/stream` | WS | Extended existing WS log — adds tier/gate/SOUL events |
| `/api/journal` | GET | Returns trade journal rows + summary stats |
| `/api/soul` | GET/POST | Read or update SOUL.md contents |
| `/api/kelly` | GET | Returns Kelly stats, f*, next size |

---

## Section 6: File Change Summary

### New Files
| File | Purpose |
|------|---------|
| `src/intelligence.py` | IntelligenceEngine class |
| `data/SOUL.md` | Trading principles (auto-created on first run) |
| `data/intelligence.db` | SQLite journal (auto-created) |
| `frontend/src/components/SignalStream.tsx` | Live signal stream tab |
| `frontend/src/components/TradeJournal.tsx` | Trade journal tab |
| `frontend/src/components/SoulConfig.tsx` | SOUL config tab |
| `frontend/src/components/KellySizing.tsx` | Kelly sizing tab |

### Modified Files
| File | Changes |
|------|---------|
| `src/signal_engine.py` | Add `_classify_tier()`, SOUL gate check, `tier` field on Signal |
| `src/risk_manager.py` | Add `kelly_usdt` param to `compute_position_size()` |
| `src/strategy_engine.py` | Call `intel.get_active_soul()` at cycle start; `intel.record_close()` after close |
| `api.py` | 4 new endpoints; extend WS log with tier/gate events |
| `frontend/src/App.tsx` | Add 4 new tab components |

---

## Non-Goals
- No LLM API calls (no Anthropic/OpenAI cost per cycle)
- No rebuild of existing signal indicators (Supertrend, ADX, MACD, etc.)
- No change to backtesting engine
- No change to order execution logic
- No change to Telegram notification format

## Testing Approach
- `IntelligenceEngine` unit tests: lesson extraction with mocked trade history, Kelly formula edge cases (0 trades, exactly 20 trades, high drawdown)
- Signal tier classification tests: boundary scores (64/65/79/80), each regime
- Integration test: full cycle with mocked Binance client, verify journal row written after close
- Manual: run on testnet for 5 cycles, verify stream tab shows reasoning, journal accumulates rows
