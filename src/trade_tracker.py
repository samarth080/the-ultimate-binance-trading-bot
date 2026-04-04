"""
Trade Tracker — persistent SQLite-backed trade history and P&L analytics.

Records every trade open/close event and exposes performance metrics used by
the strategy engine and the risk manager (win rate, average RR, daily PnL).
"""

import logging
import sqlite3
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

DB_PATH = Path("logs/trades.db")


@dataclass
class TradeRecord:
    id:            Optional[int]
    symbol:        str
    direction:     str          # LONG / SHORT
    entry_price:   float
    stop_loss:     float
    take_profit:   float
    quantity:      float
    entry_time:    str
    exit_price:    Optional[float]  = None
    exit_time:     Optional[str]    = None
    pnl:           Optional[float]  = None
    pnl_pct:       Optional[float]  = None
    close_reason:  Optional[str]    = None   # TP / SL / MANUAL / TIMEOUT
    order_id:      Optional[str]    = None


class TradeTracker:
    """
    Lightweight SQLite trade journal.

    Usage:
        tracker = TradeTracker()
        tid = tracker.open_trade(...)
        tracker.close_trade(tid, exit_price=..., close_reason="TP")
        stats = tracker.get_stats()
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    def _init_db(self):
        with self._connect() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol       TEXT    NOT NULL,
                    direction    TEXT    NOT NULL,
                    entry_price  REAL    NOT NULL,
                    stop_loss    REAL    NOT NULL,
                    take_profit  REAL    NOT NULL,
                    quantity     REAL    NOT NULL,
                    entry_time   TEXT    NOT NULL,
                    exit_price   REAL,
                    exit_time    TEXT,
                    pnl          REAL,
                    pnl_pct      REAL,
                    close_reason TEXT,
                    order_id     TEXT
                )
            """)
            con.execute("""
                CREATE INDEX IF NOT EXISTS idx_symbol_time
                ON trades (symbol, entry_time)
            """)

    # ── Write operations ─────────────────────────────────────────────────────

    def open_trade(self, symbol: str, direction: str, entry_price: float,
                   stop_loss: float, take_profit: float, quantity: float,
                   order_id: str = "") -> int:
        """Insert a new open trade. Returns the row id."""
        with self._connect() as con:
            cur = con.execute(
                """INSERT INTO trades
                   (symbol, direction, entry_price, stop_loss, take_profit,
                    quantity, entry_time, order_id)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (symbol, direction, entry_price, stop_loss, take_profit,
                 quantity, datetime.utcnow().isoformat(), order_id)
            )
            trade_id = cur.lastrowid
        logger.info(f"Trade #{trade_id} opened: {direction} {symbol} @ {entry_price}")
        return trade_id

    def close_trade(self, trade_id: int, exit_price: float,
                    close_reason: str = "MANUAL") -> Optional[TradeRecord]:
        """
        Close an open trade and compute PnL.
        Returns the completed TradeRecord or None if trade not found.
        """
        with self._connect() as con:
            row = con.execute(
                "SELECT * FROM trades WHERE id=?", (trade_id,)
            ).fetchone()

            if not row:
                logger.error(f"Trade #{trade_id} not found")
                return None

            direction   = row["direction"]
            entry_price = row["entry_price"]
            quantity    = row["quantity"]

            if direction == "LONG":
                pnl = (exit_price - entry_price) * quantity
            else:
                pnl = (entry_price - exit_price) * quantity

            pnl_pct = (pnl / (entry_price * quantity)) * 100

            exit_time = datetime.utcnow().isoformat()
            con.execute(
                """UPDATE trades
                   SET exit_price=?, exit_time=?, pnl=?, pnl_pct=?, close_reason=?
                   WHERE id=?""",
                (exit_price, exit_time, round(pnl, 6), round(pnl_pct, 4),
                 close_reason, trade_id)
            )

        logger.info(
            f"Trade #{trade_id} closed: {close_reason} @ {exit_price} "
            f"PnL={pnl:+.4f} ({pnl_pct:+.2f}%)"
        )

        return TradeRecord(
            id          = trade_id,
            symbol      = row["symbol"],
            direction   = direction,
            entry_price = entry_price,
            stop_loss   = row["stop_loss"],
            take_profit = row["take_profit"],
            quantity    = quantity,
            entry_time  = row["entry_time"],
            exit_price  = exit_price,
            exit_time   = exit_time,
            pnl         = round(pnl, 6),
            pnl_pct     = round(pnl_pct, 4),
            close_reason= close_reason,
            order_id    = row["order_id"],
        )

    # ── Read / Analytics ─────────────────────────────────────────────────────

    def get_open_trades(self) -> List[TradeRecord]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT * FROM trades WHERE exit_price IS NULL"
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def get_closed_trades(self, limit: int = 200) -> List[TradeRecord]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT * FROM trades WHERE exit_price IS NOT NULL "
                "ORDER BY exit_time DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def get_stats(self, since: Optional[str] = None) -> Dict:
        """
        Return aggregated performance stats.
        `since` is an ISO date string (e.g. '2024-01-01'). Defaults to all time.
        """
        query = "SELECT * FROM trades WHERE exit_price IS NOT NULL"
        params: list = []
        if since:
            query += " AND exit_time >= ?"
            params.append(since)

        with self._connect() as con:
            rows = con.execute(query, params).fetchall()

        if not rows:
            return {
                "total_trades": 0, "win_rate": 0.0,
                "total_pnl": 0.0,  "avg_pnl": 0.0,
                "avg_rr": 0.0,     "max_drawdown_pct": 0.0,
                "profit_factor": 0.0,
            }

        pnls    = [r["pnl"] for r in rows if r["pnl"] is not None]
        winners = [p for p in pnls if p > 0]
        losers  = [p for p in pnls if p < 0]

        gross_profit = sum(winners) if winners else 0.0
        gross_loss   = abs(sum(losers)) if losers else 0.0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)

        # Simple drawdown: running cumsum
        cum = 0.0
        peak = 0.0
        max_dd = 0.0
        for p in pnls:
            cum += p
            if cum > peak:
                peak = cum
            dd = (peak - cum) / peak * 100 if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd

        # Average R:R from actual outcomes
        rr_list = []
        for r in rows:
            if r["pnl"] and r["stop_loss"] and r["entry_price"]:
                stop_dist = abs(r["entry_price"] - r["stop_loss"])
                tp_dist   = abs(r["take_profit"] - r["entry_price"]) if r["take_profit"] else 0
                if stop_dist > 0:
                    rr_list.append(tp_dist / stop_dist)

        return {
            "total_trades":    len(pnls),
            "wins":            len(winners),
            "losses":          len(losers),
            "win_rate":        round(len(winners) / len(pnls) * 100, 1) if pnls else 0.0,
            "total_pnl":       round(sum(pnls), 4),
            "avg_pnl":         round(sum(pnls) / len(pnls), 4) if pnls else 0.0,
            "avg_rr":          round(sum(rr_list) / len(rr_list), 3) if rr_list else 0.0,
            "max_drawdown_pct": round(max_dd, 2),
            "profit_factor":   round(profit_factor, 3),
        }

    def get_daily_pnl(self, for_date: Optional[str] = None) -> float:
        today = for_date or str(date.today())
        with self._connect() as con:
            row = con.execute(
                "SELECT SUM(pnl) as total FROM trades "
                "WHERE exit_price IS NOT NULL AND exit_time LIKE ?",
                (f"{today}%",)
            ).fetchone()
        return float(row["total"] or 0.0)

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_record(row) -> TradeRecord:
        return TradeRecord(
            id          = row["id"],
            symbol      = row["symbol"],
            direction   = row["direction"],
            entry_price = row["entry_price"],
            stop_loss   = row["stop_loss"],
            take_profit = row["take_profit"],
            quantity    = row["quantity"],
            entry_time  = row["entry_time"],
            exit_price  = row["exit_price"],
            exit_time   = row["exit_time"],
            pnl         = row["pnl"],
            pnl_pct     = row["pnl_pct"],
            close_reason= row["close_reason"],
            order_id    = row["order_id"],
        )
