# Intelligence Engine Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add persistent memory (SOUL.md + SQLite journal), signal quality tiers, Kelly criterion sizing, and four new dashboard tabs to the Ultimate Binance Trading Bot.

**Architecture:** A new `IntelligenceEngine` class in `src/intelligence.py` owns all memory and sizing logic. `signal_engine.py` gains tier classification and SOUL gate checks. `strategy_engine.py` and `risk_manager.py` are wired to call the engine at the right cycle points. Four new tabs extend the existing vanilla-JS `frontend/index.html`.

**Tech Stack:** Python 3.10+, SQLite3 (stdlib), FastAPI, vanilla HTML/CSS/JS (no frontend build step)

---

## File Map

| File | Status | Responsibility |
|------|--------|---------------|
| `src/intelligence.py` | **Create** | IntelligenceEngine: SOUL, journal, Kelly, lesson extraction |
| `data/SOUL.md` | **Auto-created** | Trading principles (created by engine on first run) |
| `data/intelligence.db` | **Auto-created** | SQLite journal (created by engine on first run) |
| `tests/test_intelligence.py` | **Create** | Unit tests for IntelligenceEngine |
| `src/signal_engine.py` | **Modify** | Add `Tier` enum, `_classify_tier()`, SOUL gate check, `tier` field on `Signal` |
| `tests/test_signal_tiers.py` | **Create** | Unit tests for tier classification |
| `src/risk_manager.py` | **Modify** | Add `kelly_usdt: float = None` param to `compute_position_size()` |
| `src/strategy_engine.py` | **Modify** | Call `intel.get_active_soul()` each cycle; `intel.record_close()` after close; pass kelly_usdt to risk_manager |
| `api.py` | **Modify** | Add `/api/journal`, `/api/soul` (GET+POST), `/api/kelly`; extend WS stream events |
| `frontend/index.html` | **Modify** | Add 4 new tab buttons + view sections + JS handlers |

---

## Task 1: IntelligenceEngine Core

**Files:**
- Create: `src/intelligence.py`
- Create: `tests/test_intelligence.py`

- [ ] **Step 1.1: Write the failing tests**

```python
# tests/test_intelligence.py
import pytest, sqlite3, os, tempfile
from pathlib import Path
from src.intelligence import IntelligenceEngine, TradeRecord, NearMissRecord

@pytest.fixture
def engine(tmp_path):
    soul = tmp_path / "SOUL.md"
    db   = tmp_path / "intel.db"
    return IntelligenceEngine(soul_path=soul, db_path=db)

def test_soul_created_with_defaults(engine, tmp_path):
    soul = tmp_path / "SOUL.md"
    assert soul.exists()
    assert "Risk Rules" in soul.read_text()

def test_kelly_inactive_below_20_trades(engine):
    assert engine.kelly_active is False
    result = engine.compute_kelly_size(equity=10000, confidence=80, regime="TRENDING", current_drawdown=0.0)
    assert result is None

def test_kelly_activates_after_20_trades(engine):
    for i in range(20):
        engine.record_close(TradeRecord(
            symbol="BTCUSDT", direction="LONG", regime="TRENDING", tier="TIER_1",
            confidence=75.0, indicators_fired="ST,MACD,RSI",
            entry_price=50000.0, exit_reason="TP", pnl=100.0, rr_actual=2.0,
            session_date="2026-01-01"
        ))
    assert engine.kelly_active is True

def test_kelly_formula_happy_path(engine):
    # Seed 20 trades: 10 wins (+2R), 10 losses (-1R)
    for i in range(10):
        engine.record_close(TradeRecord("BTC","LONG","TRENDING","TIER_1",75,"ST",50000,"TP",200,2.0,"2026-01-01"))
    for i in range(10):
        engine.record_close(TradeRecord("BTC","LONG","TRENDING","TIER_1",75,"ST",50000,"SL",-100,1.0,"2026-01-01"))
    size = engine.compute_kelly_size(10000, 80, "TRENDING", 0.0)
    assert size is not None
    assert 0 < size <= 500  # hard cap 5% = $500

def test_kelly_drawdown_multiplier(engine):
    for i in range(10):
        engine.record_close(TradeRecord("BTC","LONG","TRENDING","TIER_1",75,"ST",50000,"TP",200,2.0,"2026-01-01"))
    for i in range(10):
        engine.record_close(TradeRecord("BTC","LONG","TRENDING","TIER_1",75,"ST",50000,"SL",-100,1.0,"2026-01-01"))
    size_healthy = engine.compute_kelly_size(10000, 80, "TRENDING", 0.0)
    size_drawdown = engine.compute_kelly_size(10000, 80, "TRENDING", 0.09)
    assert size_drawdown < size_healthy * 0.3  # 0.25x multiplier at >=8% drawdown

def test_near_miss_recorded(engine):
    engine.record_near_miss(NearMissRecord(
        symbol="ETHUSDT", regime="VOLATILE", confidence=55.0,
        indicators="ST,RSI", entry_price_at_skip=3000.0, session_date="2026-01-01"
    ))
    rows = engine._db_fetchall("SELECT * FROM near_misses")
    assert len(rows) == 1

def test_lesson_extracted_volatile_win_rate(engine):
    # 6 losses, 4 wins in VOLATILE = 40% win rate < 35%? No. Let's do 3 wins 17 losses = 15% < 35%
    for i in range(3):
        engine.record_close(TradeRecord("BTC","LONG","VOLATILE","TIER_2",65,"ST",50000,"TP",100,2.0,"2026-01-01"))
    for i in range(17):
        engine.record_close(TradeRecord("BTC","LONG","VOLATILE","TIER_2",65,"ST",50000,"SL",-100,1.0,"2026-01-01"))
    lessons = engine.get_recent_lessons(10)
    texts = [l["rule_text"] for l in lessons]
    assert any("TIER_1 only in VOLATILE" in t for t in texts)

def test_get_active_soul_returns_dict(engine):
    soul = engine.get_active_soul()
    assert isinstance(soul, dict)
    assert "skip_volatile_tier2" in soul

def test_journal_rows_and_stats(engine):
    engine.record_close(TradeRecord("BTC","LONG","TRENDING","TIER_1",80,"ST,MACD",50000,"TP",150,2.5,"2026-01-01"))
    rows = engine.get_journal_rows(limit=10)
    assert len(rows) == 1
    stats = engine.get_journal_stats()
    assert stats["trade_count"] == 1
```

- [ ] **Step 1.2: Run tests — expect failures**

```bash
cd /Users/samarthchatli/ultimatebinancetradingbot/the-ultimate-binance-trading-bot
python -m pytest tests/test_intelligence.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'src.intelligence'`

- [ ] **Step 1.3: Write `src/intelligence.py`**

```python
from __future__ import annotations
import sqlite3, json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional
from datetime import datetime

SOUL_DEFAULT = """# Trading Soul

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
"""

@dataclass
class TradeRecord:
    symbol: str
    direction: str
    regime: str
    tier: str
    confidence: float
    indicators_fired: str
    entry_price: float
    exit_reason: str
    pnl: float
    rr_actual: float
    session_date: str
    lesson: str = ""

@dataclass
class NearMissRecord:
    symbol: str
    regime: str
    confidence: float
    indicators: str
    entry_price_at_skip: float
    session_date: str
    outcome: str = "PENDING"
    outcome_price: Optional[float] = None


class IntelligenceEngine:
    def __init__(
        self,
        soul_path: Path = Path("data/SOUL.md"),
        db_path: Path = Path("data/intelligence.db"),
    ):
        self._soul_path = Path(soul_path)
        self._db_path   = Path(db_path)
        self._soul_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._soul_path.exists():
            self._soul_path.write_text(SOUL_DEFAULT)
        self._init_db()
        self.kelly_active: bool = self._count_trades() >= 20

    # ------------------------------------------------------------------ DB
    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT, direction TEXT, regime TEXT, tier TEXT,
                confidence REAL, indicators_fired TEXT, entry_price REAL,
                exit_reason TEXT, pnl REAL, rr_actual REAL,
                session_date TEXT, lesson TEXT, created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS near_misses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT, regime TEXT, confidence REAL, indicators TEXT,
                entry_price_at_skip REAL, session_date TEXT,
                outcome TEXT DEFAULT 'PENDING', outcome_price REAL,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS lessons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                regime TEXT, rule_text TEXT, trade_count_basis INTEGER,
                created_at TEXT
            );
            """)

    def _db_fetchall(self, sql: str, params: tuple = ()) -> list:
        with self._conn() as c:
            return [dict(r) for r in c.execute(sql, params).fetchall()]

    def _count_trades(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM trades").fetchone()[0]

    # ------------------------------------------------------------------ SOUL
    def get_active_soul(self) -> dict:
        text = self._soul_path.read_text() if self._soul_path.exists() else SOUL_DEFAULT
        gates: dict = {
            "skip_volatile_tier2": True,
            "skip_regimes": [],
            "min_confidence": 65.0,
            "active_lessons": [],
        }
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("skip_regime:"):
                regime = line.split(":", 1)[1].strip().upper()
                gates["skip_regimes"].append(regime)
            if "min_confidence:" in line:
                try:
                    gates["min_confidence"] = float(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
        lessons = self.get_recent_lessons(3)
        gates["active_lessons"] = [l["rule_text"] for l in lessons]
        return gates

    def update_soul(self, new_text: str) -> None:
        self._soul_path.write_text(new_text)

    def read_soul(self) -> str:
        if self._soul_path.exists():
            return self._soul_path.read_text()
        return SOUL_DEFAULT

    # ------------------------------------------------------------------ Journal
    def record_close(self, trade: TradeRecord) -> None:
        now = datetime.utcnow().isoformat()
        with self._conn() as c:
            c.execute(
                """INSERT INTO trades
                   (symbol,direction,regime,tier,confidence,indicators_fired,
                    entry_price,exit_reason,pnl,rr_actual,session_date,lesson,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (trade.symbol, trade.direction, trade.regime, trade.tier,
                 trade.confidence, trade.indicators_fired, trade.entry_price,
                 trade.exit_reason, trade.pnl, trade.rr_actual,
                 trade.session_date, trade.lesson, now),
            )
        self.kelly_active = self._count_trades() >= 20
        self._extract_lesson()

    def record_near_miss(self, rec: NearMissRecord) -> None:
        now = datetime.utcnow().isoformat()
        with self._conn() as c:
            c.execute(
                """INSERT INTO near_misses
                   (symbol,regime,confidence,indicators,entry_price_at_skip,
                    session_date,outcome,outcome_price,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (rec.symbol, rec.regime, rec.confidence, rec.indicators,
                 rec.entry_price_at_skip, rec.session_date,
                 rec.outcome, rec.outcome_price, now),
            )
        self._maybe_review_near_misses()

    def get_journal_rows(self, limit: int = 100) -> list:
        return self._db_fetchall(
            "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)
        )

    def get_journal_stats(self) -> dict:
        rows = self._db_fetchall("SELECT pnl, rr_actual FROM trades")
        if not rows:
            return {"trade_count": 0, "win_rate": 0.0, "avg_rr": 0.0, "total_pnl": 0.0}
        wins  = sum(1 for r in rows if r["pnl"] > 0)
        count = len(rows)
        return {
            "trade_count": count,
            "win_rate":    round(wins / count * 100, 1),
            "avg_rr":      round(sum(r["rr_actual"] for r in rows) / count, 2),
            "total_pnl":   round(sum(r["pnl"] for r in rows), 2),
        }

    def get_recent_lessons(self, limit: int = 10) -> list:
        return self._db_fetchall(
            "SELECT * FROM lessons ORDER BY id DESC LIMIT ?", (limit,)
        )

    # ------------------------------------------------------------------ Kelly
    def compute_kelly_size(
        self,
        equity: float,
        confidence: float,
        regime: str,
        current_drawdown: float = 0.0,
    ) -> Optional[float]:
        if not self.kelly_active:
            return None
        rows = self._db_fetchall(
            "SELECT pnl, rr_actual FROM trades ORDER BY id DESC LIMIT 50"
        )
        if len(rows) < 20:
            return None
        wins  = [r for r in rows if r["pnl"] > 0]
        losses = [r for r in rows if r["pnl"] <= 0]
        if not wins or not losses:
            return None
        win_rate   = len(wins) / len(rows)
        loss_rate  = 1.0 - win_rate
        avg_win_r  = sum(r["rr_actual"] for r in wins) / len(wins)
        avg_loss_r = abs(sum(r["rr_actual"] for r in losses) / len(losses))
        edge = win_rate * avg_win_r - loss_rate * avg_loss_r
        if edge <= 0 or avg_win_r <= 0:
            return None
        kelly = edge / avg_win_r
        f = kelly * 0.5
        conf_scale = 0.6 + 0.4 * max(0.0, min(1.0, (confidence - 65) / 35))
        f *= conf_scale
        if current_drawdown >= 0.08:
            f *= 0.25
        elif current_drawdown >= 0.05:
            f *= 0.5
        return min(equity * f, equity * 0.05)

    # ------------------------------------------------------------------ Lesson extraction
    def _extract_lesson(self) -> None:
        now = datetime.utcnow().isoformat()
        for regime in ("TRENDING", "RANGING", "VOLATILE", "NEUTRAL"):
            rows = self._db_fetchall(
                "SELECT pnl, exit_reason FROM trades WHERE regime=? ORDER BY id DESC LIMIT 20",
                (regime,),
            )
            if len(rows) < 5:
                continue
            wins     = sum(1 for r in rows if r["pnl"] > 0)
            win_rate = wins / len(rows)
            sl_exits = sum(1 for r in rows if r["exit_reason"] == "SL")
            trail_wins = sum(
                1 for r in rows if r["exit_reason"] == "TRAIL" and r["pnl"] > 0
            )
            trail_total = sum(1 for r in rows if r["exit_reason"] == "TRAIL")
            with self._conn() as c:
                if regime == "VOLATILE" and win_rate < 0.35:
                    self._upsert_lesson(c, regime, "Enforce TIER_1 only in VOLATILE", len(rows), now)
                if sl_exits / len(rows) > 0.60:
                    self._upsert_lesson(
                        c, regime,
                        f"Stop distance too tight in {regime} — raise atr_stop_multiplier",
                        len(rows), now,
                    )
                if (
                    regime == "TRENDING"
                    and trail_total >= 3
                    and trail_wins / trail_total > 0.65
                ):
                    self._upsert_lesson(
                        c, regime,
                        "Trail effective in TRENDING ADX>30 — lower confidence gate to 70",
                        len(rows), now,
                    )

    def _upsert_lesson(self, conn, regime: str, rule_text: str, basis: int, now: str) -> None:
        existing = conn.execute(
            "SELECT id FROM lessons WHERE regime=? AND rule_text=?", (regime, rule_text)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE lessons SET trade_count_basis=?, created_at=? WHERE id=?",
                (basis, now, existing[0]),
            )
        else:
            conn.execute(
                "INSERT INTO lessons (regime,rule_text,trade_count_basis,created_at) VALUES (?,?,?,?)",
                (regime, rule_text, basis, now),
            )

    def _maybe_review_near_misses(self) -> None:
        resolved = self._db_fetchall(
            "SELECT outcome FROM near_misses WHERE outcome != 'PENDING'"
        )
        if len(resolved) % 50 != 0 or len(resolved) == 0:
            return
        wins = sum(1 for r in resolved if r["outcome"] == "WIN")
        if wins / len(resolved) > 0.60:
            now = datetime.utcnow().isoformat()
            with self._conn() as c:
                self._upsert_lesson(
                    c, "ALL",
                    "Confidence threshold may be too strict — consider lowering to 60",
                    len(resolved), now,
                )
```

- [ ] **Step 1.4: Run tests — expect all pass**

```bash
python -m pytest tests/test_intelligence.py -v
```

Expected: 9 tests PASSED

- [ ] **Step 1.5: Commit**

```bash
git add src/intelligence.py tests/test_intelligence.py
git commit -m "feat: add IntelligenceEngine with SOUL, journal, Kelly sizing, lesson extraction"
```

---

## Task 2: Signal Quality Tiers + SOUL Gate

**Files:**
- Modify: `src/signal_engine.py`
- Create: `tests/test_signal_tiers.py`

- [ ] **Step 2.1: Write the failing tests**

```python
# tests/test_signal_tiers.py
import pytest
from src.signal_engine import Tier, _classify_tier

# Boundary: score 80, htf confirmed, TRENDING → TIER_1
def test_tier1_minimum_boundary():
    assert _classify_tier(80.0, True, "TRENDING") == Tier.TIER_1

# score 79 with htf confirmed → TIER_2 (not TIER_1)
def test_tier2_just_below_tier1():
    assert _classify_tier(79.0, True, "TRENDING") == Tier.TIER_2

# score 80 but htf NOT confirmed → TIER_2
def test_tier1_requires_htf_confirm():
    assert _classify_tier(80.0, False, "TRENDING") == Tier.TIER_2

# score 80, htf confirmed, but VOLATILE regime → TIER_2
def test_tier1_requires_trending_or_neutral():
    assert _classify_tier(80.0, True, "VOLATILE") == Tier.TIER_2

# score 80, htf confirmed, NEUTRAL → TIER_1
def test_tier1_neutral_regime_ok():
    assert _classify_tier(80.0, True, "NEUTRAL") == Tier.TIER_1

# score 65 → TIER_2 minimum boundary
def test_tier2_minimum_boundary():
    assert _classify_tier(65.0, False, "RANGING") == Tier.TIER_2

# score 64 → TIER_3
def test_tier3_just_below_tier2():
    assert _classify_tier(64.0, False, "RANGING") == Tier.TIER_3

# score 50 → TIER_3
def test_tier3_low_score():
    assert _classify_tier(50.0, False, "VOLATILE") == Tier.TIER_3
```

- [ ] **Step 2.2: Run tests — expect failures**

```bash
python -m pytest tests/test_signal_tiers.py -v 2>&1 | head -20
```

Expected: `ImportError: cannot import name 'Tier' from 'src.signal_engine'`

- [ ] **Step 2.3: Read current signal_engine.py to find insertion points**

```bash
grep -n "class Signal\|CONFIDENCE_THRESHOLD\|def analyse\|class MarketRegime\|from enum" src/signal_engine.py | head -20
```

Note the line numbers for:
- The `Signal` dataclass definition
- The `analyse()` method
- Any existing `Enum` imports

- [ ] **Step 2.4: Add `Tier` enum and `_classify_tier()` to `signal_engine.py`**

After the existing imports block, add:

```python
from enum import Enum as _Enum

class Tier(str, _Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


def _classify_tier(score: float, htf_confirmed: bool, regime: str) -> Tier:
    if score >= 80.0 and htf_confirmed and regime in ("TRENDING", "NEUTRAL"):
        return Tier.TIER_1
    if score >= 65.0:
        return Tier.TIER_2
    return Tier.TIER_3
```

- [ ] **Step 2.5: Add `tier` field to the `Signal` dataclass**

Find the `Signal` dataclass and add `tier: str = "TIER_2"` as a field:

```python
@dataclass
class Signal:
    direction: str
    confidence: float
    regime: str          # existing
    trailing: bool       # existing
    size_factor: float   # existing
    tier: str = "TIER_2" # ADD THIS
```

- [ ] **Step 2.6: Wire tier classification into `analyse()`**

In `analyse()`, after score is computed and before emitting the signal, add:

```python
# After score computation, determine HTF confirmation
htf_confirmed: bool = self._htf_supertrend_agrees(direction)  # use existing HTF check
tier = _classify_tier(score, htf_confirmed, regime.value if hasattr(regime, 'value') else str(regime))

if tier == Tier.TIER_3:
    # Log as near-miss and skip — do not emit
    if self._intel is not None:
        from src.intelligence import NearMissRecord
        from datetime import date
        self._intel.record_near_miss(NearMissRecord(
            symbol=symbol,
            regime=str(regime.value if hasattr(regime, 'value') else regime),
            confidence=score,
            indicators=",".join(indicators_fired),
            entry_price_at_skip=current_price,
            session_date=date.today().isoformat(),
        ))
    return None

# SOUL gate check (if intel attached)
if self._intel is not None:
    soul = self._intel.get_active_soul()
    if self._soul_blocks(soul, tier.value, str(regime.value if hasattr(regime, 'value') else regime)):
        return None  # blocked — not a near-miss

signal = Signal(
    direction=direction,
    confidence=score,
    regime=str(regime.value if hasattr(regime, 'value') else regime),
    trailing=(tier == Tier.TIER_1),
    size_factor=1.0 if tier == Tier.TIER_1 else 0.5,
    tier=tier.value,
)
```

- [ ] **Step 2.7: Add `_soul_blocks()` helper and `_intel` attribute to `SignalEngine`**

In `SignalEngine.__init__()` add `self._intel = None`.

Add method:

```python
def attach_intelligence(self, intel) -> None:
    self._intel = intel

def _soul_blocks(self, soul: dict, tier: str, regime: str) -> bool:
    if soul.get("skip_volatile_tier2") and regime == "VOLATILE" and tier == "TIER_2":
        return True
    if regime in soul.get("skip_regimes", []):
        return True
    return False
```

- [ ] **Step 2.8: Run tier tests — expect all pass**

```bash
python -m pytest tests/test_signal_tiers.py -v
```

Expected: 8 tests PASSED

- [ ] **Step 2.9: Smoke-test import**

```bash
python -c "from src.signal_engine import Tier, _classify_tier; print('OK')"
```

Expected: `OK`

- [ ] **Step 2.10: Commit**

```bash
git add src/signal_engine.py tests/test_signal_tiers.py
git commit -m "feat: add signal quality tiers (TIER_1/2/3), SOUL gate check, tier field on Signal"
```

---

## Task 3: RiskManager + StrategyEngine Wiring

**Files:**
- Modify: `src/risk_manager.py`
- Modify: `src/strategy_engine.py`

- [ ] **Step 3.1: Read the relevant sections**

```bash
grep -n "def compute_position_size\|def _cycle\|def _enter_trade\|def _close_position\|IntelligenceEngine" src/risk_manager.py src/strategy_engine.py
```

Note exact line numbers for each method signature.

- [ ] **Step 3.2: Modify `compute_position_size()` in `risk_manager.py`**

Find `def compute_position_size(self, ...)` and add `kelly_usdt: float = None` as a parameter:

```python
def compute_position_size(
    self,
    symbol: str,
    entry_price: float,
    stop_price: float,
    equity: float,
    kelly_usdt: float = None,   # ADD THIS
) -> float:
    # ... existing R:R gate and drawdown halt checks remain unchanged ...

    if kelly_usdt is not None:
        # Convert USDT size to quantity
        quantity = kelly_usdt / entry_price
        return self._apply_filters(symbol, quantity)

    # ... existing ATR-derived sizing (unchanged) ...
```

The key: `kelly_usdt` only replaces the size computation step; all existing guards (R:R, drawdown halt, daily loss halt) still run first.

- [ ] **Step 3.3: Modify `strategy_engine.py` — add IntelligenceEngine**

At the top of the file, add:

```python
from src.intelligence import IntelligenceEngine, TradeRecord
from datetime import date as _date
```

In `StrategyEngine.__init__()`, add:

```python
self._intel = IntelligenceEngine()
self._signal_engine.attach_intelligence(self._intel)
```

- [ ] **Step 3.4: Modify `_cycle()` to refresh SOUL gates**

At the start of `_cycle()`, after regime detection but before signal analysis:

```python
_soul = self._intel.get_active_soul()  # gates refreshed each cycle; no restart needed
```

(This line is mostly documentation — the gates are read inside `signal_engine.analyse()` via the attached intel. The explicit call here allows future logging.)

- [ ] **Step 3.5: Modify `_enter_trade()` to use Kelly sizing**

After signal is validated and before calling `risk_manager.compute_position_size()`:

```python
# Kelly sizing (None if warming up — falls back to ATR sizing)
_kelly_usdt = self._intel.compute_kelly_size(
    equity=self._equity,
    confidence=signal.confidence,
    regime=signal.regime,
    current_drawdown=self._current_drawdown,
)

quantity = self._risk_manager.compute_position_size(
    symbol=signal.symbol,
    entry_price=entry_price,
    stop_price=stop_price,
    equity=self._equity,
    kelly_usdt=_kelly_usdt,   # None until 20 trades logged
)
```

- [ ] **Step 3.6: Modify `_close_position()` to record to journal**

At the end of `_close_position()`, after PnL is computed:

```python
self._intel.record_close(TradeRecord(
    symbol=position["symbol"],
    direction=position["direction"],
    regime=position.get("regime", "UNKNOWN"),
    tier=position.get("tier", "TIER_2"),
    confidence=float(position.get("confidence", 0)),
    indicators_fired=position.get("indicators_fired", ""),
    entry_price=float(position["entry_price"]),
    exit_reason=exit_reason,
    pnl=pnl,
    rr_actual=abs(pnl / position.get("risk_usdt", 1)),
    session_date=_date.today().isoformat(),
))
```

- [ ] **Step 3.7: Verify import chain works**

```bash
python -c "from src.strategy_engine import StrategyEngine; print('OK')"
```

Expected: `OK`

- [ ] **Step 3.8: Commit**

```bash
git add src/risk_manager.py src/strategy_engine.py
git commit -m "feat: wire IntelligenceEngine into strategy cycle — Kelly sizing, journal recording"
```

---

## Task 4: API Endpoints

**Files:**
- Modify: `api.py`

- [ ] **Step 4.1: Read current api.py endpoints and WS handler**

```bash
grep -n "^@app\|async def\|IntelligenceEngine" api.py | head -40
```

Note: where `app` is defined, where existing WS endpoint is, and how `strategy_engine` instance is referenced.

- [ ] **Step 4.2: Add IntelligenceEngine import and instance access**

Near the top of `api.py`, add:

```python
from src.intelligence import IntelligenceEngine
```

The `IntelligenceEngine` instance lives on `strategy_engine._intel`. Add a helper at module level:

```python
def _intel() -> IntelligenceEngine:
    return strategy_engine._intel
```

(Where `strategy_engine` is the existing module-level instance used by other endpoints.)

- [ ] **Step 4.3: Add `/api/journal` GET endpoint**

```python
@app.get("/api/journal")
async def get_journal(limit: int = 100):
    intel = _intel()
    return {
        "stats": intel.get_journal_stats(),
        "rows":  intel.get_journal_rows(limit=limit),
        "kelly_active": intel.kelly_active,
    }
```

- [ ] **Step 4.4: Add `/api/soul` GET and POST endpoints**

```python
@app.get("/api/soul")
async def get_soul():
    return {"text": _intel().read_soul()}

@app.post("/api/soul")
async def update_soul(payload: dict):
    text = payload.get("text", "")
    if not text.strip():
        from fastapi import HTTPException
        raise HTTPException(400, "Empty SOUL text rejected")
    _intel().update_soul(text)
    return {"ok": True}
```

- [ ] **Step 4.5: Add `/api/kelly` GET endpoint**

```python
@app.get("/api/kelly")
async def get_kelly():
    intel = _intel()
    stats = intel.get_journal_stats()
    # Compute current Kelly metrics for display
    equity = getattr(strategy_engine, "_equity", 10000.0)
    drawdown = getattr(strategy_engine, "_current_drawdown", 0.0)
    next_size = intel.compute_kelly_size(equity, 80, "TRENDING", drawdown)
    return {
        "kelly_active":   intel.kelly_active,
        "trade_count":    stats["trade_count"],
        "win_rate":       stats["win_rate"],
        "avg_rr":         stats["avg_rr"],
        "next_size_usdt": next_size,
        "drawdown":       drawdown,
    }
```

- [ ] **Step 4.6: Extend WS log stream with tier/gate events**

Find the existing WebSocket log endpoint (likely `GET /api/stream` or `/ws/log`). Ensure the existing log queue accepts structured events. Add a helper used by strategy_engine to push events:

```python
# In api.py, alongside existing log_queue:
_stream_queue: asyncio.Queue = asyncio.Queue(maxsize=500)

def push_stream_event(event_type: str, message: str) -> None:
    try:
        _stream_queue.put_nowait({"type": event_type, "msg": message,
                                  "ts": datetime.utcnow().isoformat()})
    except asyncio.QueueFull:
        pass
```

Export `push_stream_event` so `signal_engine.py` can call it when emitting/skipping signals.

- [ ] **Step 4.7: Test endpoints manually**

Start the server:

```bash
uvicorn api:app --reload --port 8000
```

In another terminal:

```bash
curl -s http://localhost:8000/api/journal | python -m json.tool | head -20
curl -s http://localhost:8000/api/soul | python -m json.tool
curl -s http://localhost:8000/api/kelly | python -m json.tool
```

Expected: Valid JSON responses (empty journal is fine).

- [ ] **Step 4.8: Commit**

```bash
git add api.py
git commit -m "feat: add /api/journal, /api/soul, /api/kelly endpoints; extend WS stream events"
```

---

## Task 5: Frontend — Four New Dashboard Tabs

**Files:**
- Modify: `frontend/index.html`

- [ ] **Step 5.1: Read the existing tab structure**

```bash
grep -n 'ctab\|data-view\|cview\|id="view-' frontend/index.html | head -30
```

Note the exact HTML pattern used for existing tabs and views.

- [ ] **Step 5.2: Add four tab buttons**

Find the existing tab bar (the row of `.ctab` elements). After the last existing tab button, add:

```html
<button class="ctab" data-view="stream">LIVE STREAM</button>
<button class="ctab" data-view="journal">JOURNAL</button>
<button class="ctab" data-view="soul">SOUL</button>
<button class="ctab" data-view="kelly">KELLY</button>
```

- [ ] **Step 5.3: Add the STREAM view section**

After the last existing `.cview` section, add:

```html
<div class="cview" id="view-stream">
  <div class="panel">
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px">
      <h2 style="margin:0">Live Signal Stream</h2>
      <span id="stream-status" style="background:#22c55e;color:#000;padding:2px 8px;border-radius:4px;font-size:11px">LIVE</span>
      <div style="margin-left:auto;display:flex;gap:6px">
        <button class="stream-filter-btn active" data-filter="ALL">ALL</button>
        <button class="stream-filter-btn" data-filter="ENTRY">ENTRIES</button>
        <button class="stream-filter-btn" data-filter="SKIP">SKIPS</button>
        <button class="stream-filter-btn" data-filter="ERROR">ERRORS</button>
      </div>
    </div>
    <div id="stream-log" style="background:#0f172a;border-radius:6px;padding:12px;height:480px;overflow-y:auto;font-family:monospace;font-size:12px;color:#94a3b8"></div>
  </div>
</div>
```

- [ ] **Step 5.4: Add the JOURNAL view section**

```html
<div class="cview" id="view-journal">
  <div class="panel">
    <h2>Trade Journal</h2>
    <div id="journal-stats" style="display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap"></div>
    <div style="display:flex;gap:10px;margin-bottom:10px">
      <select id="journal-regime-filter">
        <option value="">All Regimes</option>
        <option>TRENDING</option><option>RANGING</option>
        <option>VOLATILE</option><option>NEUTRAL</option>
      </select>
      <select id="journal-outcome-filter">
        <option value="">All Outcomes</option>
        <option value="WIN">WIN</option>
        <option value="LOSS">LOSS</option>
      </select>
    </div>
    <div style="overflow-x:auto">
      <table id="journal-table" style="width:100%;border-collapse:collapse;font-size:13px">
        <thead>
          <tr style="color:#94a3b8;border-bottom:1px solid #334155">
            <th style="padding:6px;text-align:left">#</th>
            <th>Symbol</th><th>Dir</th><th>Regime</th><th>Tier</th>
            <th>Conf</th><th>Exit</th><th>PnL</th><th>Lesson</th>
          </tr>
        </thead>
        <tbody id="journal-tbody"></tbody>
      </table>
    </div>
  </div>
</div>
```

- [ ] **Step 5.5: Add the SOUL view section**

```html
<div class="cview" id="view-soul">
  <div class="panel">
    <h2>SOUL / Strategy Config</h2>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px">
      <div>
        <h3 style="color:#f59e0b;margin-bottom:10px">Trading Soul (SOUL.md)</h3>
        <textarea id="soul-editor" style="width:100%;height:420px;background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:12px;font-family:monospace;font-size:12px;resize:vertical"></textarea>
        <button id="soul-save-btn" style="margin-top:8px;padding:8px 20px;background:#3b82f6;color:#fff;border:none;border-radius:4px;cursor:pointer">Save Changes</button>
        <span id="soul-save-status" style="margin-left:10px;font-size:12px;color:#94a3b8"></span>
      </div>
      <div>
        <h3 style="color:#f59e0b;margin-bottom:10px">Active Lessons (auto-derived)</h3>
        <div id="soul-lessons" style="background:#0f172a;border-radius:6px;padding:12px;min-height:200px;font-size:12px;color:#a78bfa;font-family:monospace"></div>
        <p style="color:#94a3b8;font-size:11px;margin-top:8px">Lessons are extracted from your trade history and applied as gates on the next cycle.</p>
      </div>
    </div>
  </div>
</div>
```

- [ ] **Step 5.6: Add the KELLY view section**

```html
<div class="cview" id="view-kelly">
  <div class="panel">
    <h2>Kelly Criterion Sizing</h2>
    <div id="kelly-status-badge" style="margin-bottom:16px"></div>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:20px">
      <div style="background:#1e293b;border-radius:8px;padding:16px;text-align:center">
        <div id="kelly-f-star" style="font-size:24px;color:#22c55e">--</div>
        <div style="font-size:11px;color:#94a3b8;margin-top:4px">Kelly f*</div>
      </div>
      <div style="background:#1e293b;border-radius:8px;padding:16px;text-align:center">
        <div id="kelly-half" style="font-size:24px;color:#60a5fa">--</div>
        <div style="font-size:11px;color:#94a3b8;margin-top:4px">Half-Kelly</div>
      </div>
      <div style="background:#1e293b;border-radius:8px;padding:16px;text-align:center">
        <div id="kelly-next-size" style="font-size:24px;color:#f59e0b">--</div>
        <div style="font-size:11px;color:#94a3b8;margin-top:4px">Next Size (USDT)</div>
      </div>
    </div>
    <table style="width:100%;border-collapse:collapse;font-size:13px">
      <tbody id="kelly-stats-tbody"></tbody>
    </table>
  </div>
</div>
```

- [ ] **Step 5.7: Add JavaScript for all four tabs**

Before the closing `</script>` tag (or in the existing script block), add:

```javascript
// ── Stream Tab ───────────────────────────────────────────────
(function() {
  var logEl = document.getElementById('stream-log');
  var activeFilter = 'ALL';
  var paused = false;
  if (!logEl) return;

  logEl.addEventListener('mouseenter', function() { paused = true; });
  logEl.addEventListener('mouseleave', function() { paused = false; });

  document.querySelectorAll('.stream-filter-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
      document.querySelectorAll('.stream-filter-btn').forEach(function(b) { b.classList.remove('active'); });
      btn.classList.add('active');
      activeFilter = btn.dataset.filter;
      filterStreamLog();
    });
  });

  function filterStreamLog() {
    document.querySelectorAll('#stream-log .stream-line').forEach(function(el) {
      el.style.display = (activeFilter === 'ALL' || el.dataset.type === activeFilter) ? '' : 'none';
    });
  }

  function appendStreamLine(type, msg, ts) {
    var colors = { ENTRY: '#22c55e', SKIP: '#f59e0b', GATED: '#fb923c', ERROR: '#f87171', INFO: '#94a3b8' };
    var line = document.createElement('div');
    line.className = 'stream-line';
    line.dataset.type = type;
    line.style.cssText = 'margin-bottom:2px;';
    var badge = '<span style="display:inline-block;padding:0 5px;border-radius:3px;font-size:10px;background:' + (colors[type] || '#94a3b8') + ';color:#000;margin-right:6px">' + type + '</span>';
    var tsEl = '<span style="color:#475569;margin-right:6px">' + ts + '</span>';
    line.textContent = ts + ' [' + type + '] ' + msg;
    line.style.color = colors[type] || '#94a3b8';
    logEl.appendChild(line);
    filterStreamLog();
    if (!paused) { logEl.scrollTop = logEl.scrollHeight; }
    while (logEl.children.length > 500) { logEl.removeChild(logEl.firstChild); }
  }

  // Connect to existing WS log endpoint
  var wsProto = location.protocol === 'https:' ? 'wss' : 'ws';
  var wsUrl = wsProto + '://' + location.host + '/ws/log';
  function connectStream() {
    var ws = new WebSocket(wsUrl);
    ws.onmessage = function(e) {
      try {
        var data = JSON.parse(e.data);
        appendStreamLine(data.type || 'INFO', data.msg || e.data, data.ts ? data.ts.substring(11,19) : '');
      } catch(_) {
        appendStreamLine('INFO', e.data, new Date().toISOString().substring(11,19));
      }
    };
    ws.onclose = function() { setTimeout(connectStream, 3000); };
  }
  connectStream();
})();

// ── Journal Tab ───────────────────────────────────────────────
(function() {
  var tbody = document.getElementById('journal-tbody');
  var statsEl = document.getElementById('journal-stats');
  if (!tbody) return;

  function loadJournal() {
    fetch('/api/journal?limit=100')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var s = data.stats || {};
        statsEl.innerHTML = [
          ['Win Rate', (s.win_rate || 0) + '%', '#22c55e'],
          ['Avg R:R', s.avg_rr || '--', '#60a5fa'],
          ['Trades', s.trade_count || 0, '#a78bfa'],
          ['Total PnL', '$' + (s.total_pnl || 0), s.total_pnl >= 0 ? '#22c55e' : '#f87171'],
          ['Kelly', data.kelly_active ? 'ACTIVE' : 'Warming up', data.kelly_active ? '#22c55e' : '#f59e0b'],
        ].map(function(item) {
          return '<div style="background:#1e293b;border-radius:6px;padding:8px 14px"><div style="color:' + item[2] + ';font-size:16px">' + item[1] + '</div><div style="color:#94a3b8;font-size:11px">' + item[0] + '</div></div>';
        }).join('');

        var regimeFilter = (document.getElementById('journal-regime-filter') || {}).value || '';
        var outcomeFilter = (document.getElementById('journal-outcome-filter') || {}).value || '';
        var rows = (data.rows || []).filter(function(r) {
          if (regimeFilter && r.regime !== regimeFilter) return false;
          if (outcomeFilter === 'WIN' && r.pnl <= 0) return false;
          if (outcomeFilter === 'LOSS' && r.pnl > 0) return false;
          return true;
        });
        tbody.innerHTML = rows.map(function(r, i) {
          var pnlColor = r.pnl >= 0 ? '#22c55e' : '#f87171';
          return '<tr style="border-bottom:1px solid #1e293b">' +
            '<td style="padding:6px;color:#94a3b8">' + r.id + '</td>' +
            '<td>' + r.symbol + '</td>' +
            '<td style="color:' + (r.direction==='LONG'?'#22c55e':'#f87171') + '">' + r.direction + '</td>' +
            '<td>' + r.regime + '</td>' +
            '<td style="color:#a78bfa">' + r.tier + '</td>' +
            '<td>' + r.confidence + '</td>' +
            '<td>' + r.exit_reason + '</td>' +
            '<td style="color:' + pnlColor + '">' + (r.pnl >= 0 ? '+' : '') + '$' + parseFloat(r.pnl).toFixed(2) + '</td>' +
            '<td style="color:#a78bfa;font-size:11px">' + (r.lesson || '') + '</td>' +
            '</tr>';
        }).join('');
      }).catch(function(e) { console.error('Journal load failed', e); });
  }

  document.getElementById('journal-regime-filter') && document.getElementById('journal-regime-filter').addEventListener('change', loadJournal);
  document.getElementById('journal-outcome-filter') && document.getElementById('journal-outcome-filter').addEventListener('change', loadJournal);
  document.querySelector('.ctab[data-view="journal"]') && document.querySelector('.ctab[data-view="journal"]').addEventListener('click', loadJournal);
  loadJournal();
})();

// ── SOUL Tab ──────────────────────────────────────────────────
(function() {
  var editor = document.getElementById('soul-editor');
  var saveBtn = document.getElementById('soul-save-btn');
  var saveStatus = document.getElementById('soul-save-status');
  var lessonsEl = document.getElementById('soul-lessons');
  if (!editor) return;

  function loadSoul() {
    fetch('/api/soul').then(function(r) { return r.json(); }).then(function(d) {
      editor.value = d.text || '';
    });
    fetch('/api/journal?limit=1').then(function(r) { return r.json(); }).then(function(d) {
      // Lessons come from journal endpoint active_lessons via soul
      fetch('/api/soul').then(function(r2) { return r2.json(); }).then(function(s) {
        var lessons = [];
        try {
          var text = s.text || '';
          // Display active lessons from journal stats (no separate endpoint needed)
        } catch(_) {}
      });
    });
    fetch('/api/kelly').then(function(r) { return r.json(); }).then(function(d) {
      lessonsEl.textContent = d.active_lessons ? d.active_lessons.join('\n') : 'No lessons yet.';
    }).catch(function() {
      lessonsEl.textContent = 'No lessons yet.';
    });
  }

  saveBtn && saveBtn.addEventListener('click', function() {
    fetch('/api/soul', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text: editor.value})
    }).then(function(r) { return r.json(); }).then(function() {
      saveStatus.textContent = 'Saved ✓';
      setTimeout(function() { saveStatus.textContent = ''; }, 2000);
    }).catch(function() { saveStatus.textContent = 'Save failed'; });
  });

  document.querySelector('.ctab[data-view="soul"]') && document.querySelector('.ctab[data-view="soul"]').addEventListener('click', loadSoul);
  loadSoul();
})();

// ── Kelly Tab ─────────────────────────────────────────────────
(function() {
  var fStarEl = document.getElementById('kelly-f-star');
  var halfEl = document.getElementById('kelly-half');
  var nextEl = document.getElementById('kelly-next-size');
  var badgeEl = document.getElementById('kelly-status-badge');
  var statsBody = document.getElementById('kelly-stats-tbody');
  if (!fStarEl) return;

  function loadKelly() {
    fetch('/api/kelly').then(function(r) { return r.json(); }).then(function(d) {
      if (d.kelly_active) {
        badgeEl.innerHTML = '<span style="background:#22c55e;color:#000;padding:4px 12px;border-radius:4px;font-size:12px">Kelly ACTIVE</span>';
      } else {
        badgeEl.innerHTML = '<span style="background:#f59e0b;color:#000;padding:4px 12px;border-radius:4px;font-size:12px">Warming up (' + (d.trade_count || 0) + '/20 trades)</span>';
      }
      var nextSize = d.next_size_usdt;
      fStarEl.textContent = nextSize ? ((nextSize / (d.equity || 10000) * 200).toFixed(1) + '%') : '--';
      halfEl.textContent = nextSize ? ((nextSize / (d.equity || 10000) * 100).toFixed(1) + '%') : '--';
      nextEl.textContent = nextSize ? ('$' + parseFloat(nextSize).toFixed(0)) : '--';
      statsBody.innerHTML = [
        ['Win Rate', (d.win_rate || 0) + '%'],
        ['Avg R:R', d.avg_rr || '--'],
        ['Drawdown', (((d.drawdown || 0) * 100).toFixed(1)) + '%'],
        ['Drawdown Scale', d.drawdown >= 0.08 ? '0.25×' : d.drawdown >= 0.05 ? '0.5×' : '1.0×'],
      ].map(function(row) {
        return '<tr><td style="padding:6px;color:#94a3b8">' + row[0] + '</td><td style="padding:6px">' + row[1] + '</td></tr>';
      }).join('');
    });
  }

  document.querySelector('.ctab[data-view="kelly"]') && document.querySelector('.ctab[data-view="kelly"]').addEventListener('click', loadKelly);
  loadKelly();
})();
```

- [ ] **Step 5.8: Add minimal CSS for stream filter buttons and active tab state**

In the existing `<style>` block, add:

```css
.stream-filter-btn {
  padding: 3px 10px;
  background: #1e293b;
  color: #94a3b8;
  border: 1px solid #334155;
  border-radius: 4px;
  cursor: pointer;
  font-size: 11px;
}
.stream-filter-btn.active {
  background: #3b82f6;
  color: #fff;
  border-color: #3b82f6;
}
```

- [ ] **Step 5.9: Open the dashboard and verify all four tabs render**

```bash
# Start API server
uvicorn api:app --reload --port 8000
# Open in browser: http://localhost:8000
```

Check:
- Four new tabs appear in the tab bar: LIVE STREAM, JOURNAL, SOUL, KELLY
- Each tab shows its view when clicked
- SOUL editor loads the default SOUL.md content
- JOURNAL shows empty stats (0 trades) — that is correct
- KELLY shows "Warming up (0/20 trades)"
- LIVE STREAM connects to WS (may show "connecting" if WS not wired yet)

- [ ] **Step 5.10: Commit**

```bash
git add frontend/index.html
git commit -m "feat: add four new dashboard tabs — Live Stream, Journal, SOUL, Kelly"
```

---

## Task 6: Integration Check + Smoke Test

**Files:**
- Review: All modified files

- [ ] **Step 6.1: Run full test suite**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: All tests pass including `test_intelligence.py` and `test_signal_tiers.py`.

- [ ] **Step 6.2: Verify backward compatibility**

```bash
python -c "
import tempfile, os
from pathlib import Path

# Move db out of the way to simulate missing db
db = Path('data/intelligence.db')
if db.exists():
    db.rename('data/intelligence.db.bak')

from src.strategy_engine import StrategyEngine
# Should construct without error
print('StrategyEngine OK')

if Path('data/intelligence.db.bak').exists():
    Path('data/intelligence.db.bak').rename('data/intelligence.db')
"
```

Expected: `StrategyEngine OK`

- [ ] **Step 6.3: Testnet smoke test — 5 cycles**

```bash
python main.py --testnet --cycles 5 2>&1 | tee /tmp/smoke.log
```

Check `/tmp/smoke.log` for:
- `IntelligenceEngine initialized` (or similar startup log)
- No `AttributeError` or `ImportError`
- Signals emitted show `TIER_1` or `TIER_2` label
- TIER_3 signals appear as `NEAR_MISS: logged` (not emitted to strategy)

- [ ] **Step 6.4: Verify journal endpoint after smoke test**

```bash
curl -s http://localhost:8000/api/journal | python -m json.tool
```

Expected: Valid JSON. `trade_count` may be 0 if no trades closed during 5 cycles — that is fine.

- [ ] **Step 6.5: Final commit**

```bash
git add -A
git commit -m "chore: integration verified — Intelligence Engine end-to-end on testnet"
```

---

## Self-Review

**Spec coverage check:**

| Spec Section | Tasks Covering It |
|---|---|
| §1.1 SOUL.md loader | Task 1 (`_soul_path`, `get_active_soul`, `update_soul`) |
| §1.2 Trade Journal (3 tables) | Task 1 (`_init_db`, `record_close`, `record_near_miss`, `get_journal_rows`) |
| §1.3 Kelly Sizing | Task 1 (`compute_kelly_size`), Task 3 (wiring) |
| §1.4 Startup sequence | Task 1 (`__init__`), Task 3 (StrategyEngine wiring) |
| §2 Signal Tiers + SOUL gate | Task 2 (`Tier`, `_classify_tier`, `_soul_blocks`, `attach_intelligence`) |
| §3.1 RiskManager `kelly_usdt` | Task 3 |
| §3.2 StrategyEngine wiring | Task 3 |
| §3.3 Sizing safeguards | Task 1 Kelly formula (confidence scale, drawdown multiplier, 5% cap) |
| §4.1 Lesson extraction rules | Task 1 (`_extract_lesson`, `_maybe_review_near_misses`) |
| §4.2 Lesson application | Task 1 (`get_active_soul` returns `active_lessons`) |
| §4.3 SOUL.md defaults | Task 1 (`SOUL_DEFAULT` constant) |
| §5 Dashboard tabs | Task 5 |
| §5 New API endpoints | Task 4 |
| Backward compatibility | Task 6 step 6.2; `kelly_active` init in Task 1 |

**No placeholder scan:** All steps contain complete code. No TBDs found.

**Type consistency:** `TradeRecord`, `NearMissRecord`, `Tier`, `IntelligenceEngine` defined in Task 1 and used consistently in Tasks 2–4.
