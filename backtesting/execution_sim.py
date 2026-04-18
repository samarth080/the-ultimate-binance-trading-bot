"""Trade execution simulator: entry/exit fills with slippage, fees, intra-bar SL/TP."""
from __future__ import annotations

from typing import Literal, Optional

from backtesting.types import Bar, Fill, Position


def _apply_slippage(price: float, bps: float, side: Literal["BUY", "SELL"]) -> float:
    sign = 1 if side == "BUY" else -1
    return price * (1 + sign * bps / 10_000)


def _fee(price: float, qty: float, bps: float) -> float:
    return abs(price * qty) * bps / 10_000


class ExecutionSimulator:
    def __init__(self, taker_fee_bps: float, slippage_bps: float,
                 fill_model: Literal["pessimistic", "optimistic"]):
        self.taker_fee_bps = taker_fee_bps
        self.slippage_bps = slippage_bps
        self.fill_model = fill_model

    def entry_fill_for(self, side: Literal["BUY", "SELL"], symbol: str,
                        qty: float, next_bar: Bar) -> Fill:
        price = _apply_slippage(next_bar.open, self.slippage_bps, side)
        fee = _fee(price, qty, self.taker_fee_bps)
        return Fill(symbol=symbol, side=side, qty=qty, price=price, fee=fee,
                    timestamp=next_bar.open_time, reason="ENTRY")

    def update_trailing(self, pos: Position, bar: Bar) -> None:
        """Ratchet the trailing stop in the profitable direction. Mutates pos in place.

        Trail distance = pos.entry_atr (the ATR-based stop distance set at entry).
        The stop only moves in the favorable direction — never against the trade.
        """
        if pos.trailing_stop is None:
            return
        # Trail at 1.5×ATR — tighter than the 2.5×ATR entry stop, locks in profit faster
        trail_dist = pos.trail_atr * 1.5 if pos.trail_atr > 0 else pos.entry_atr
        if pos.direction == "LONG":
            new_trail = bar.close - trail_dist
            if new_trail > pos.trailing_stop:
                pos.trailing_stop = new_trail
        else:
            new_trail = bar.close + trail_dist
            if new_trail < pos.trailing_stop:
                pos.trailing_stop = new_trail

    def check_exit(self, pos: Position, bar: Bar) -> Optional[Fill]:
        """Return Fill if SL/TP/trailing stop hit inside bar; else None.

        Pessimistic model: if both SL and TP are inside the bar's range
        in the same candle, assume SL fills first.
        """
        long = pos.direction == "LONG"

        # Trailing stop takes precedence over fixed SL when active
        effective_sl = pos.trailing_stop if pos.trailing_stop is not None else pos.stop_loss

        sl_hit = (bar.low <= effective_sl)    if long else (bar.high >= effective_sl)
        tp_hit = (bar.high >= pos.take_profit) if long else (bar.low <= pos.take_profit)

        if not sl_hit and not tp_hit:
            return None

        if sl_hit and tp_hit:
            picked = "SL" if self.fill_model == "pessimistic" else "TP"
        elif sl_hit:
            picked = "TRAIL" if pos.trailing_stop is not None else "SL"
        else:
            picked = "TP"

        target_price = effective_sl if picked in ("SL", "TRAIL") else pos.take_profit
        exit_side: Literal["BUY", "SELL"] = "SELL" if long else "BUY"
        fill_price = _apply_slippage(target_price, self.slippage_bps, exit_side)
        fee = _fee(fill_price, pos.qty, self.taker_fee_bps)

        return Fill(symbol=pos.symbol, side=exit_side, qty=pos.qty,
                    price=fill_price, fee=fee, timestamp=bar.close_time,
                    reason=picked)
