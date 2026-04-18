"""Orchestrates the backtesting loop, integrating all modules."""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import pandas as pd

from backtesting.data_feed import DataFeed
from backtesting.execution_sim import ExecutionSimulator
from backtesting.portfolio import PortfolioBook
from backtesting.risk import BacktestRiskManager
from backtesting.types import BacktestConfig, Fill, Position
from src.signal_engine import SignalEngine
from src.trade_tracker import TradeRecord

logger = logging.getLogger(__name__)


def compute_metrics(trades_df: pd.DataFrame, final_equity: float, start_equity: float,
                    timeseries_equity: list[dict] = None) -> dict:
    if trades_df.empty:
        return {"total_trades": 0, "win_rate": 0.0, "total_pnl": 0.0, "max_drawdown_pct": 0.0, "final_equity": start_equity}
    
    total_trades = len(trades_df)
    winners = trades_df[trades_df["pnl"] > 0]
    losers = trades_df[trades_df["pnl"] <= 0]
    
    wins = len(winners)
    win_rate = wins / total_trades if total_trades > 0 else 0.0
    total_pnl = float(trades_df["pnl"].sum())
    
    return {
        "total_trades": total_trades,
        "wins": wins,
        "win_rate": round(win_rate * 100, 2),
        "total_pnl": round(total_pnl, 2),
        "final_equity": round(final_equity, 2)
    }


class Backtester:
    def __init__(self, config: BacktestConfig, feed: DataFeed, run_dir: Path):
        self.config = config
        self.feed = feed
        self.run_dir = run_dir

        self.portfolio = PortfolioBook(config.initial_capital)
        self.ex_sim = ExecutionSimulator(
            config.taker_fee_bps, config.slippage_bps, config.fill_model
        )
        self.risk_manager = BacktestRiskManager(run_dir=run_dir)

        # We construct SignalEngine directly, overriding its config
        self.engine = SignalEngine(fetch_klines_fn=self._fetch_history)

        self._trade_records: list[TradeRecord] = []
        self._next_trade_id = 1
        self.equity_curve: list[dict] = []

    def _fetch_history(self, symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
        if not hasattr(self, "_current_t"):
            raise RuntimeError("Cannot fetch history outside of bar loop.")
        return self.feed.history(symbol, timeframe, self._current_t, limit)

    def run(self) -> tuple[pd.DataFrame, dict]:
        logger.info(f"Starting {self.config.mode} backtest for {self.config.symbols}")

        times = self.feed.primary_close_times()
        if not times:
            logger.warning("No overlapping bars found.")
            return pd.DataFrame(), compute_metrics(pd.DataFrame(), self.portfolio.cash, self.portfolio.initial_capital)

        for t in times:
            self._current_t = t
            self._step(t)
            self._record_equity(t)

        self._force_close_end_of_data()

        trades_df = pd.DataFrame(self._trade_records)
        metrics = compute_metrics(trades_df, self.portfolio.get_equity(), self.portfolio.initial_capital, self.equity_curve)
        return trades_df, metrics

    def _step(self, t: datetime):
        # PHASE 1: Check exits against the bar that just closed at t.
        # This must happen BEFORE MTM update and BEFORE any entry decisions.
        mtm_bars = {}
        for sym in self.config.symbols:
            current_bar = self.feed.bar(sym, self.config.primary_tf, t)
            if current_bar:
                mtm_bars[sym] = current_bar

        for sym in self.config.symbols:
            pos = self.portfolio.get_position(sym)
            if pos is None:
                continue
            current_bar = mtm_bars.get(sym)
            if current_bar is None:
                continue
            fill = self.ex_sim.check_exit(pos, current_bar)
            if fill is not None:
                self.portfolio.process_fill(fill)
                self._record_trade_close(pos, fill)

        # PHASE 2: Update MTM with current close prices (after exits freed positions).
        self.portfolio.update_mtm(mtm_bars)

        # PHASE 2.5: Ratchet trailing stops for all open positions.
        for sym in self.config.symbols:
            pos = self.portfolio.get_position(sym)
            if pos is not None and pos.trailing_stop is not None:
                current_bar = mtm_bars.get(sym)
                if current_bar:
                    self.ex_sim.update_trailing(pos, current_bar)

        # PHASE 3: Generate entry signals and fill at the NEXT bar's open.
        # Using next_bar only here keeps entries strictly after signal confirmation.
        for sym in self.config.symbols:
            if self.portfolio.get_position(sym) is not None:
                continue  # already in a position for this symbol

            next_bar = self.feed.next_bar(sym, self.config.primary_tf, t)
            if next_bar is None:
                continue  # no future data — end of dataset

            sig = self.engine.analyse(sym, self.config.primary_tf, self.config.confirm_tf)
            if not sig or sig.direction.value not in ["LONG", "SHORT"]:
                continue

            direction = sig.direction.value
            sl = float(sig.stop_loss)
            tp = float(sig.take_profit)
            eq = self.portfolio.get_equity()

            size = self.risk_manager.compute_position_size(
                equity=eq, entry_price=float(sig.price),
                stop_price=sl, take_profit=tp, step_size=0.0
            )
            if not size or size.quantity <= 0:
                continue

            # Regime-based size adjustment (e.g. 0.5× in VOLATILE, 0.75× in RANGING)
            effective_qty = size.quantity * sig.size_factor
            if effective_qty <= 0:
                continue

            side = "BUY" if direction == "LONG" else "SELL"
            fill = self.ex_sim.entry_fill_for(side, sym, effective_qty, next_bar)
            entry_atr = abs(float(sig.price) - sl)
            new_pos = Position(
                symbol=sym, direction=direction, qty=effective_qty,
                entry_price=fill.price, stop_loss=sl, take_profit=tp,
                entry_time=fill.timestamp, entry_fee=fill.fee,
                entry_atr=entry_atr,
                trade_id=self._next_trade_id,
                trailing_stop=sl if sig.trailing else None,
                trail_atr=sig.atr if sig.trailing else 0.0,
                regime=sig.regime.value if hasattr(sig.regime, "value") else str(sig.regime),
            )
            self._next_trade_id += 1
            self.portfolio.process_fill(fill)
            self.portfolio.add_position(new_pos)

    def _record_equity(self, t: datetime):
        self.equity_curve.append({
            "timestamp": t,
            "equity": self.portfolio.get_equity()
        })

    def _record_trade_close(self, pos: Position, fill: Fill):
        pnl = (fill.price - pos.entry_price) * pos.qty
        if pos.direction == "SHORT":
            pnl = -pnl
            
        pnl_pct = (pnl / (pos.entry_price * pos.qty)) * 100
        
        tr = TradeRecord(
            id=pos.trade_id, symbol=pos.symbol, direction=pos.direction,
            entry_price=pos.entry_price, stop_loss=pos.stop_loss,
            take_profit=pos.take_profit, quantity=pos.qty,
            entry_time=pos.entry_time.isoformat(),
            exit_price=fill.price, exit_time=fill.timestamp.isoformat(),
            pnl=pnl - fill.fee - pos.entry_fee,
            pnl_pct=pnl_pct, close_reason=fill.reason, order_id=None
        )
        self._trade_records.append(asdict(tr))

    def _force_close_end_of_data(self):
        for sym, pos in list(self.portfolio.positions.items()):
            # Find last known price
            last_price = self.portfolio.mtm_prices.get(sym, pos.entry_price)
            side = "SELL" if pos.direction == "LONG" else "BUY"
            fee = abs(last_price * pos.qty) * self.config.taker_fee_bps / 10_000
            fill = Fill(sym, side, pos.qty, last_price, fee, self._current_t, "EOD")
            self.portfolio.process_fill(fill)
            self._record_trade_close(pos, fill)


def run_per_symbol(config: BacktestConfig, feed: DataFeed,
                   run_dir: Path) -> tuple[pd.DataFrame, dict]:
    """Runs a separate backtest for each symbol, resetting capital."""
    all_trades = []
    metrics_map = {}

    for sym in config.symbols:
        cfg = BacktestConfig(
            symbols=[sym], primary_tf=config.primary_tf, confirm_tf=config.confirm_tf,
            start=config.start, end=config.end, initial_capital=config.initial_capital,
            taker_fee_bps=config.taker_fee_bps, slippage_bps=config.slippage_bps,
            fill_model=config.fill_model, mode="per_symbol", seed=config.seed
        )
        sub_dir = run_dir / sym
        sub_dir.mkdir(parents=True, exist_ok=True)
        bt = Backtester(cfg, feed, sub_dir)
        trades, metric = bt.run()
        all_trades.append(trades)
        metrics_map[sym] = metric

    if all_trades:
        combined = pd.concat(all_trades, ignore_index=True)
    else:
        combined = pd.DataFrame()
    return combined, metrics_map
