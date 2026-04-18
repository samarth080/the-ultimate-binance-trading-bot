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
        wins   = [r for r in rows if r["pnl"] > 0]
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
        drawdown_mult = 1.0
        if current_drawdown >= 0.08:
            drawdown_mult = 0.25
        elif current_drawdown >= 0.05:
            drawdown_mult = 0.5
        f *= drawdown_mult
        hard_cap = equity * 0.05 * drawdown_mult
        return min(equity * f, hard_cap)

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
