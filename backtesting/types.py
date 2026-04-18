"""Core dataclasses for the backtesting engine."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Optional


_TF_MINUTES = {
    "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "2h": 120, "4h": 240, "6h": 360, "8h": 480, "12h": 720,
    "1d": 1440,
}


def tf_to_timedelta(tf: str) -> timedelta:
    if tf not in _TF_MINUTES:
        raise ValueError(f"Unsupported timeframe: {tf}")
    return timedelta(minutes=_TF_MINUTES[tf])

import sys as _sys
from pathlib import Path as _Path
_PROJECT_ROOT = str(_Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in _sys.path:
    _sys.path.insert(0, _PROJECT_ROOT)
from src.signal_engine import StrategyParams


@dataclass(frozen=True)
class Bar:
    symbol: str
    timeframe: str
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def close_time(self) -> datetime:
        return self.open_time + tf_to_timedelta(self.timeframe)


@dataclass
class Position:
    symbol: str
    direction: Literal["LONG", "SHORT"]
    qty: float
    entry_price: float
    stop_loss: float
    take_profit: float
    entry_time: datetime
    entry_fee: float
    entry_atr: float
    trade_id: int
    trailing_stop: Optional[float] = None  # active trailing stop price; None = fixed SL/TP
    trail_atr: float = 0.0                 # raw ATR at entry — used for trailing distance
    regime: str = "NEUTRAL"


@dataclass
class Fill:
    symbol: str
    side: Literal["BUY", "SELL"]
    qty: float
    price: float
    fee: float
    timestamp: datetime
    reason: Literal["ENTRY", "TP", "SL", "TRAIL", "EOD"]


@dataclass
class BacktestConfig:
    symbols: list[str]
    primary_tf: str
    confirm_tf: str
    start: datetime
    end: datetime
    initial_capital: float = 10_000.0
    taker_fee_bps: float = 4.0
    slippage_bps: float = 2.0
    fill_model: Literal["pessimistic", "optimistic"] = "pessimistic"
    mode: Literal["portfolio", "per_symbol"] = "portfolio"
    confidence_threshold: Optional[float] = None
    seed: int = 42
    strategy_params: Optional[StrategyParams] = None
