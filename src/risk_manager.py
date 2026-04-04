"""
Risk Manager — ATR-based stops, Kelly position sizing, drawdown protection.

Key rules (from the world's best bots):
  1. Risk at most RISK_PER_TRADE_PCT of account equity per trade.
  2. Daily loss limit: stop trading if daily PnL drops below MAX_DAILY_LOSS_PCT.
  3. Maximum drawdown guard: halt if equity falls below DRAWDOWN_HALT_PCT of peak.
  4. Never open more than MAX_OPEN_POSITIONS at once.
  5. Only accept trades where actual R:R ≥ MIN_RR_RATIO.
"""

import logging
import json
import os
from datetime import date, datetime
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional

logger = logging.getLogger(__name__)

# ─── Config defaults (all overridable via .env) ───────────────────────────────
RISK_PER_TRADE_PCT = float(os.getenv("RISK_PER_TRADE_PCT", "0.01"))   # 1% per trade
MAX_DAILY_LOSS_PCT = float(os.getenv("MAX_DAILY_LOSS_PCT", "0.05"))   # halt at 5% daily loss
DRAWDOWN_HALT_PCT  = float(os.getenv("DRAWDOWN_HALT_PCT",  "0.10"))   # halt at 10% drawdown
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS",   "10"))     # was 3 — now 10
MIN_RR_RATIO       = float(os.getenv("MIN_RR_RATIO",       "1.5"))    # min risk:reward


@dataclass
class PositionSize:
    symbol: str
    quantity: float
    risk_amount: float     # USD at risk
    stop_distance: float   # price distance to stop
    rr_ratio: float


class RiskManager:
    """
    Stateful risk manager.  Persists daily P&L to `logs/risk_state.json`
    so it survives restarts within the same trading day.
    """

    STATE_FILE = Path("logs/risk_state.json")

    def __init__(self,
                 risk_per_trade: float = RISK_PER_TRADE_PCT,
                 max_daily_loss: float = MAX_DAILY_LOSS_PCT,
                 drawdown_halt:  float = DRAWDOWN_HALT_PCT,
                 max_positions:  int   = MAX_OPEN_POSITIONS,
                 min_rr:         float = MIN_RR_RATIO):
        self.risk_per_trade = risk_per_trade
        self.max_daily_loss = max_daily_loss
        self.drawdown_halt  = drawdown_halt
        self.max_positions  = max_positions
        self.min_rr         = min_rr
        self._state         = self._load_state()

    # ── State persistence ────────────────────────────────────────────────────

    def _load_state(self) -> dict:
        self.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        today = str(date.today())
        if self.STATE_FILE.exists():
            try:
                s = json.loads(self.STATE_FILE.read_text())
                if s.get("date") == today:
                    return s
            except Exception:
                pass
        return {
            "date":            today,
            "daily_pnl":       0.0,
            "peak_equity":     0.0,
            "open_positions":  0,
            "trades_today":    0,
            "halted":          False,
        }

    def _save_state(self):
        try:
            self.STATE_FILE.write_text(json.dumps(self._state, indent=2))
        except Exception as e:
            logger.error(f"Could not save risk state: {e}")

    # ── Public helpers ────────────────────────────────────────────────────────

    def is_trading_allowed(self) -> bool:
        """Return False and log reason if any halt condition is active."""
        if self._state["halted"]:
            logger.warning("Trading HALTED — manual halt flag is set.")
            return False
        if self._state["daily_pnl"] < 0 and abs(self._state["daily_pnl"]) / max(self._state.get("peak_equity", 1), 1) >= self.max_daily_loss:
            logger.warning(f"Daily loss limit reached ({self._state['daily_pnl']:.2f}). No more trades today.")
            self._state["halted"] = True
            self._save_state()
            return False
        if self._state["open_positions"] >= self.max_positions:
            logger.warning(f"Max open positions ({self.max_positions}) reached.")
            return False
        return True

    def compute_position_size(self, equity: float, entry_price: float,
                               stop_price: float, take_profit: float,
                               contract_size: float = 1.0,
                               step_size: float = 0.001) -> Optional[PositionSize]:
        """
        Calculate the position size that risks exactly `risk_per_trade` of equity.

        equity        — account equity in quote currency (e.g. USDT)
        entry_price   — planned entry
        stop_price    — ATR-based stop
        take_profit   — ATR-based take-profit
        contract_size — value per unit (1.0 for linear futures)
        step_size     — minimum quantity step from exchange
        """
        stop_distance = abs(entry_price - stop_price)
        tp_distance   = abs(entry_price - take_profit)

        if stop_distance == 0:
            logger.error("Stop distance is zero — cannot size position.")
            return None

        rr_ratio = tp_distance / stop_distance

        if rr_ratio < self.min_rr:
            logger.warning(f"R:R {rr_ratio:.2f} < minimum {self.min_rr} — trade rejected.")
            return None

        risk_amount = equity * self.risk_per_trade
        raw_qty     = risk_amount / (stop_distance * contract_size)

        # Align to exchange step size
        if step_size > 0:
            raw_qty = max(step_size, round(raw_qty / step_size) * step_size)

        if self._state["peak_equity"] == 0:
            self._state["peak_equity"] = equity
        elif equity > self._state["peak_equity"]:
            self._state["peak_equity"] = equity

        # Drawdown guard
        drawdown = (self._state["peak_equity"] - equity) / self._state["peak_equity"]
        if drawdown >= self.drawdown_halt:
            logger.warning(
                f"Drawdown {drawdown*100:.1f}% ≥ halt threshold {self.drawdown_halt*100:.1f}%."
                " No new trades until equity recovers."
            )
            self._state["halted"] = True
            self._save_state()
            return None

        return PositionSize(
            symbol        = "",
            quantity      = round(raw_qty, 6),
            risk_amount   = round(risk_amount, 4),
            stop_distance = round(stop_distance, 6),
            rr_ratio      = round(rr_ratio, 3),
        )

    def record_trade_open(self):
        self._state["open_positions"] = min(
            self._state["open_positions"] + 1, self.max_positions)
        self._state["trades_today"] += 1
        self._save_state()

    def record_trade_close(self, pnl: float, equity: float):
        self._state["open_positions"] = max(
            self._state["open_positions"] - 1, 0)
        self._state["daily_pnl"] = round(
            self._state["daily_pnl"] + pnl, 4)
        if equity > self._state["peak_equity"]:
            self._state["peak_equity"] = equity
        self._save_state()
        logger.info(
            f"Trade closed. PnL={pnl:+.4f}  Daily PnL={self._state['daily_pnl']:+.4f}  "
            f"Peak equity={self._state['peak_equity']:.4f}"
        )

    def update_equity(self, equity: float):
        if equity > self._state["peak_equity"]:
            self._state["peak_equity"] = equity
        self._save_state()

    def status(self) -> dict:
        return dict(self._state)

    def trailing_stop(self, entry_price: float, current_price: float,
                      current_stop: float, atr: float,
                      direction: str, trail_atr_mult: float = 1.2) -> float:
        """
        Ratchet the stop upward (for longs) or downward (for shorts).
        Returns the new stop price (never moves against the position).
        """
        if direction == "LONG":
            new_stop = current_price - trail_atr_mult * atr
            return max(new_stop, current_stop)
        else:
            new_stop = current_price + trail_atr_mult * atr
            return min(new_stop, current_stop)
