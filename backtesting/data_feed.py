"""Time-aligned in-memory access to OHLCV across symbols and timeframes."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pandas as pd

from backtesting.types import Bar, tf_to_timedelta


@dataclass
class DataFeed:
    bars: dict[tuple[str, str], pd.DataFrame]
    primary_tf: str = "5m"
    symbols: Optional[list[str]] = None
    start: Optional[datetime] = None
    end: Optional[datetime] = None

    def _df(self, symbol: str, tf: str) -> Optional[pd.DataFrame]:
        return self.bars.get((symbol, tf))

    def bar(self, symbol: str, tf: str, t: datetime) -> Optional[Bar]:
        df = self._df(symbol, tf)
        if df is None:
            return None
        target_open = t - tf_to_timedelta(tf)
        match = df[df["open_time"] == target_open]
        if match.empty:
            return None
        row = match.iloc[0]
        return Bar(symbol=symbol, timeframe=tf, open_time=row["open_time"],
                   open=float(row["open"]), high=float(row["high"]),
                   low=float(row["low"]), close=float(row["close"]),
                   volume=float(row["volume"]))

    def next_bar(self, symbol: str, tf: str, t: datetime) -> Optional[Bar]:
        df = self._df(symbol, tf)
        if df is None:
            return None
        future = df[df["open_time"] > t]
        if future.empty:
            return None
        row = future.iloc[0]
        return Bar(symbol=symbol, timeframe=tf, open_time=row["open_time"],
                   open=float(row["open"]), high=float(row["high"]),
                   low=float(row["low"]), close=float(row["close"]),
                   volume=float(row["volume"]))

    def primary_close_times(self) -> list[datetime]:
        if self.symbols is None or self.start is None or self.end is None:
            raise ValueError("primary_close_times requires symbols/start/end on the feed")
        tf_delta = tf_to_timedelta(self.primary_tf)
        all_times: set[datetime] = set()
        for sym in self.symbols:
            df = self._df(sym, self.primary_tf)
            if df is None:
                continue
            close_times = df["open_time"] + tf_delta
            mask = (close_times >= self.start) & (close_times <= self.end)
            all_times.update(close_times[mask].tolist())
        return sorted(all_times)

    def history(self, symbol: str, tf: str, end: datetime,
                limit: int) -> pd.DataFrame:
        """Last `limit` bars whose close_time <= end.

        Returns DataFrame with capitalized columns Open/High/Low/Close/Volume to
        match the contract that SignalEngine's `analyse_timeframe` expects.
        Enforces no-lookahead: never returns a bar with close_time > end.
        """
        df = self._df(symbol, tf)
        if df is None:
            return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
        tf_delta = tf_to_timedelta(tf)
        max_open_time = end - tf_delta
        eligible = df[df["open_time"] <= max_open_time]
        tail = eligible.tail(limit).copy()
        tail = tail.rename(columns={
            "open": "Open", "high": "High", "low": "Low",
            "close": "Close", "volume": "Volume",
        })
        tail = tail.set_index("open_time")
        return tail[["Open", "High", "Low", "Close", "Volume"]]
