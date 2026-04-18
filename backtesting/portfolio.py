"""Portfolio manager: tracks cash, positions, and current mark-to-market equity."""
from __future__ import annotations

import logging
from typing import Optional

from backtesting.types import Bar, Fill, Position

logger = logging.getLogger(__name__)


class PortfolioBook:
    def __init__(self, initial_capital: float):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions: dict[str, Position] = {}
        self.mtm_prices: dict[str, float] = {}

    def get_equity(self) -> float:
        """Calculate total account equity (cash + mtm value of open positions)."""
        equity = self.cash
        for sym, pos in self.positions.items():
            price = self.mtm_prices.get(sym, pos.entry_price)
            if pos.direction == "LONG":
                # Value of asset owned
                equity += pos.qty * price
            else:
                # Value we owe to buy back the short
                equity -= pos.qty * price
        return equity

    def get_open_positions(self) -> list[Position]:
        return list(self.positions.values())

    def get_position(self, symbol: str) -> Optional[Position]:
        return self.positions.get(symbol)

    def add_position(self, pos: Position):
        if pos.symbol in self.positions:
            logger.warning(f"Overwriting existing position for {pos.symbol} in portfolio")
        self.positions[pos.symbol] = pos
        self.mtm_prices[pos.symbol] = pos.entry_price

    def remove_position(self, symbol: str) -> Optional[Position]:
        return self.positions.pop(symbol, None)

    def process_fill(self, fill: Fill):
        """Update cash balance based on fill execution."""
        if fill.side == "BUY":
            # Cash spent to buy the asset + fees
            self.cash -= (fill.qty * fill.price + fill.fee)
        else: # SELL
            # Cash received from selling the asset - fees
            self.cash += (fill.qty * fill.price - fill.fee)

        if fill.reason != "ENTRY":
            self.remove_position(fill.symbol)

    def update_mtm(self, bars: dict[str, Bar]):
        """Update mark-to-market prices using the latest close prices."""
        for sym, bar in bars.items():
            if sym in self.positions:
                self.mtm_prices[sym] = bar.close
