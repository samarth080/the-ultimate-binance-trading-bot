# Backtesting Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a backtesting engine that reuses `SignalEngine`, `RiskManager`, and `TradeTracker` unchanged and produces decision-grade portfolio + per-symbol performance reports.

**Architecture:** New `backtesting/` package outside `src/`. Strategy reused via injected historical fetcher into `SignalEngine`. Risk reused via subclass overriding `STATE_FILE` per run. Tracker reused via per-run `db_path`. Time-synced master loop iterates primary-TF bar close times; exits processed before entries; deterministic symbol ordering; pessimistic intra-bar SL/TP fills.

**Tech Stack:** Python 3.10+, pandas, pyarrow, matplotlib, PyYAML, pytest, binance-futures-connector (already in repo).

**Spec:** [docs/superpowers/specs/2026-04-18-backtesting-engine-design.md](../specs/2026-04-18-backtesting-engine-design.md)

---

## Task 0: Package skeleton + dependencies

**Files:**
- Create: `backtesting/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/backtesting/__init__.py`
- Create: `configs/.gitkeep`
- Create: `runs/.gitkeep`
- Create: `data/cache/.gitkeep`
- Modify: `requirements.txt`
- Modify: `.gitignore`

- [ ] **Step 1: Create directories and empty package files**

```bash
mkdir -p backtesting tests/backtesting configs runs data/cache
touch backtesting/__init__.py tests/__init__.py tests/backtesting/__init__.py
touch configs/.gitkeep runs/.gitkeep data/cache/.gitkeep
```

- [ ] **Step 2: Add dependencies to requirements.txt**

Append to `requirements.txt`:

```
pyarrow>=14.0
matplotlib>=3.7
PyYAML>=6.0
pytest>=7.4
```

- [ ] **Step 3: Update .gitignore**

Append to `.gitignore`:

```
# Backtesting outputs
runs/*
!runs/.gitkeep
data/cache/*
!data/cache/.gitkeep
```

- [ ] **Step 4: Install new deps and verify**

Run: `pip install -r requirements.txt`
Run: `python -c "import pyarrow, matplotlib, yaml, pytest; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add backtesting/ tests/ configs/ runs/ data/ requirements.txt .gitignore
git commit -m "scaffold: add backtesting package skeleton and deps"
```

---

## Task 1: Core types in `backtesting/types.py`

**Files:**
- Create: `backtesting/types.py`
- Create: `tests/backtesting/test_types.py`

- [ ] **Step 1: Write failing test**

`tests/backtesting/test_types.py`:

```python
from datetime import datetime, timezone
from backtesting.types import Bar, Position, Fill, BacktestConfig


def test_bar_close_time_5m():
    b = Bar(symbol="BTCUSDT", timeframe="5m",
            open_time=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
            open=100, high=110, low=95, close=105, volume=1.0)
    assert b.close_time == datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc)


def test_bar_close_time_1h():
    b = Bar(symbol="BTCUSDT", timeframe="1h",
            open_time=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
            open=100, high=110, low=95, close=105, volume=1.0)
    assert b.close_time == datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)


def test_position_construction():
    p = Position(symbol="BTCUSDT", direction="LONG", qty=0.01,
                 entry_price=50000, stop_loss=49000, take_profit=52000,
                 entry_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
                 entry_fee=2.0, entry_atr=500.0, trade_id=1)
    assert p.symbol == "BTCUSDT"
    assert p.direction == "LONG"


def test_fill_construction():
    f = Fill(symbol="BTCUSDT", side="BUY", qty=0.01, price=50000.0,
             fee=2.0, timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
             reason="ENTRY")
    assert f.reason == "ENTRY"


def test_config_defaults():
    cfg = BacktestConfig(
        symbols=["BTCUSDT"], primary_tf="5m", confirm_tf="1h",
        start=datetime(2025, 10, 1, tzinfo=timezone.utc),
        end=datetime(2026, 4, 1, tzinfo=timezone.utc),
    )
    assert cfg.initial_capital == 10_000.0
    assert cfg.taker_fee_bps == 4.0
    assert cfg.slippage_bps == 2.0
    assert cfg.fill_model == "pessimistic"
    assert cfg.mode == "portfolio"
    assert cfg.seed == 42
```

- [ ] **Step 2: Run test — verify FAIL**

Run: `pytest tests/backtesting/test_types.py -v`
Expected: ImportError (module doesn't exist)

- [ ] **Step 3: Implement `backtesting/types.py`**

```python
"""Core dataclasses for the backtesting engine."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal


_TF_MINUTES = {
    "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "2h": 120, "4h": 240, "6h": 360, "8h": 480, "12h": 720,
    "1d": 1440,
}


def tf_to_timedelta(tf: str) -> timedelta:
    if tf not in _TF_MINUTES:
        raise ValueError(f"Unsupported timeframe: {tf}")
    return timedelta(minutes=_TF_MINUTES[tf])


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
    confidence_threshold: float | None = None
    seed: int = 42
```

- [ ] **Step 4: Run test — verify PASS**

Run: `pytest tests/backtesting/test_types.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backtesting/types.py tests/backtesting/test_types.py
git commit -m "feat(backtesting): add core dataclasses (Bar, Position, Fill, BacktestConfig)"
```

---

## Task 2: Test fixtures in `conftest.py`

**Files:**
- Create: `tests/backtesting/conftest.py`

- [ ] **Step 1: Implement fixtures**

```python
"""Shared fixtures for backtesting tests."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def tmp_run_dir(tmp_path) -> Path:
    d = tmp_path / "run"
    d.mkdir()
    return d


def _make_klines(start: datetime, n: int, tf_minutes: int,
                 base_price: float = 100.0, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    times = [start + timedelta(minutes=tf_minutes * i) for i in range(n)]
    closes = base_price + np.cumsum(rng.normal(0, 0.5, size=n))
    opens = np.roll(closes, 1)
    opens[0] = base_price
    highs = np.maximum(opens, closes) + rng.uniform(0.1, 0.8, size=n)
    lows = np.minimum(opens, closes) - rng.uniform(0.1, 0.8, size=n)
    vols = rng.uniform(10, 100, size=n)
    return pd.DataFrame({
        "open_time": times,
        "open": opens, "high": highs, "low": lows, "close": closes,
        "volume": vols,
    })


@pytest.fixture
def synthetic_5m_300() -> pd.DataFrame:
    """300 bars of 5m OHLCV starting 2026-01-01 UTC. Deterministic (seed=0)."""
    return _make_klines(
        start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        n=300, tf_minutes=5, base_price=50000.0, seed=0,
    )


@pytest.fixture
def synthetic_1h_300() -> pd.DataFrame:
    """300 bars of 1h OHLCV starting 2026-01-01 UTC."""
    return _make_klines(
        start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        n=300, tf_minutes=60, base_price=50000.0, seed=1,
    )


@pytest.fixture
def make_klines():
    """Factory exposed to tests that need custom klines."""
    return _make_klines
```

- [ ] **Step 2: Smoke test the fixtures**

Run: `pytest tests/backtesting/conftest.py --collect-only`
Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add tests/backtesting/conftest.py
git commit -m "test(backtesting): add synthetic OHLCV fixtures"
```

---

## Task 3: `data_loader.py` — CSV import

**Files:**
- Create: `backtesting/data_loader.py`
- Create: `tests/backtesting/test_data_loader.py`

- [ ] **Step 1: Write failing test**

`tests/backtesting/test_data_loader.py`:

```python
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from backtesting.data_loader import load_csv


def test_load_csv_iso_timestamps(tmp_path: Path):
    csv = tmp_path / "btc.csv"
    csv.write_text(
        "open_time,open,high,low,close,volume\n"
        "2026-01-01T00:00:00Z,50000,50100,49900,50050,1.0\n"
        "2026-01-01T00:05:00Z,50050,50200,50000,50150,2.0\n"
    )
    df = load_csv(csv)
    assert list(df.columns) == ["open_time", "open", "high", "low", "close", "volume"]
    assert len(df) == 2
    assert df["open_time"].iloc[0] == datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    assert df["close"].dtype == float


def test_load_csv_epoch_ms(tmp_path: Path):
    csv = tmp_path / "btc.csv"
    csv.write_text(
        "open_time,open,high,low,close,volume\n"
        "1767225600000,50000,50100,49900,50050,1.0\n"
    )
    df = load_csv(csv)
    assert df["open_time"].iloc[0].tzinfo is not None


def test_load_csv_missing_columns_raises(tmp_path: Path):
    csv = tmp_path / "bad.csv"
    csv.write_text("open_time,close\n2026-01-01T00:00:00Z,50000\n")
    with pytest.raises(ValueError, match="missing"):
        load_csv(csv)
```

- [ ] **Step 2: Run — verify FAIL**

Run: `pytest tests/backtesting/test_data_loader.py -v`
Expected: ImportError

- [ ] **Step 3: Implement `load_csv`**

`backtesting/data_loader.py`:

```python
"""OHLCV ingestion: CSV import + Binance REST downloader with parquet cache."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

REQUIRED_COLS = ["open_time", "open", "high", "low", "close", "volume"]


def load_csv(path: Path) -> pd.DataFrame:
    """Load OHLCV from CSV. Required columns: open_time, open, high, low, close, volume.

    `open_time` may be ISO-8601 string OR integer epoch ms.
    Returns DataFrame with tz-aware UTC `open_time` and float OHLCV columns.
    """
    df = pd.read_csv(path)
    missing = set(REQUIRED_COLS) - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing required columns: {sorted(missing)}")

    if pd.api.types.is_numeric_dtype(df["open_time"]):
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    else:
        df["open_time"] = pd.to_datetime(df["open_time"], utc=True)

    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df[REQUIRED_COLS].sort_values("open_time").reset_index(drop=True)
    return df
```

- [ ] **Step 4: Run — verify PASS**

Run: `pytest tests/backtesting/test_data_loader.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backtesting/data_loader.py tests/backtesting/test_data_loader.py
git commit -m "feat(backtesting): CSV OHLCV loader with schema validation"
```

---

## Task 4: `data_loader.py` — Binance downloader with parquet cache

**Files:**
- Modify: `backtesting/data_loader.py`
- Modify: `tests/backtesting/test_data_loader.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/backtesting/test_data_loader.py`:

```python
from unittest.mock import MagicMock

from backtesting.data_loader import download_klines, _tf_to_ms


def _fake_kline_row(open_ms: int, close_price: float):
    # Binance klines() returns lists of 12 items; only first 6 are used here
    return [open_ms, "100", "110", "95", str(close_price), "1.0",
            open_ms + 299_999, "0", 0, "0", "0", "0"]


def test_download_klines_writes_parquet_cache(tmp_path: Path):
    client = MagicMock()
    start_ms = 1767225600000
    rows = [_fake_kline_row(start_ms + i * 300_000, 100.0 + i) for i in range(50)]
    client.klines.return_value = rows

    df = download_klines(
        client=client, symbol="BTCUSDT", interval="5m",
        start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end=datetime(2026, 1, 1, 4, 0, tzinfo=timezone.utc),
        cache_dir=tmp_path,
    )
    assert len(df) == 50
    cache_file = tmp_path / "BTCUSDT_5m.parquet"
    assert cache_file.exists()


def test_download_klines_uses_cache(tmp_path: Path):
    client = MagicMock()
    start_ms = 1767225600000
    rows = [_fake_kline_row(start_ms + i * 300_000, 100.0 + i) for i in range(10)]
    client.klines.return_value = rows

    download_klines(client, "BTCUSDT", "5m",
                    datetime(2026, 1, 1, tzinfo=timezone.utc),
                    datetime(2026, 1, 1, 0, 50, tzinfo=timezone.utc),
                    cache_dir=tmp_path)
    first_call_count = client.klines.call_count

    # Second call same range — should hit cache, no new client calls
    download_klines(client, "BTCUSDT", "5m",
                    datetime(2026, 1, 1, tzinfo=timezone.utc),
                    datetime(2026, 1, 1, 0, 50, tzinfo=timezone.utc),
                    cache_dir=tmp_path)
    assert client.klines.call_count == first_call_count


def test_tf_to_ms():
    assert _tf_to_ms("5m") == 5 * 60 * 1000
    assert _tf_to_ms("1h") == 60 * 60 * 1000
```

- [ ] **Step 2: Run — verify FAIL**

Run: `pytest tests/backtesting/test_data_loader.py -v`
Expected: ImportError on `download_klines`

- [ ] **Step 3: Implement downloader**

Append to `backtesting/data_loader.py`:

```python
import time

_TF_TO_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
    "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000,
    "6h": 21_600_000, "8h": 28_800_000, "12h": 43_200_000, "1d": 86_400_000,
}


def _tf_to_ms(tf: str) -> int:
    if tf not in _TF_TO_MS:
        raise ValueError(f"Unsupported timeframe: {tf}")
    return _TF_TO_MS[tf]


def _cache_path(cache_dir: Path, symbol: str, interval: str) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{symbol}_{interval}.parquet"


def _read_cache(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        return pd.read_parquet(path)
    except Exception as e:
        logger.warning(f"Cache read failed at {path}: {e}; ignoring")
        return None


def _write_cache(path: Path, df: pd.DataFrame) -> None:
    df.to_parquet(path, index=False)


def _klines_to_df(rows: list) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_av", "trades", "tb_base_av", "tb_quote_av", "ignore",
    ])
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df[REQUIRED_COLS]


def download_klines(client, symbol: str, interval: str,
                     start: datetime, end: datetime,
                     cache_dir: Path,
                     max_per_call: int = 1500,
                     retry_max: int = 5) -> pd.DataFrame:
    """Download klines from Binance, persist to parquet cache, return rows in [start, end].

    Uses cache when present and covers the requested range; otherwise fetches
    only the missing tail beyond the cache.
    """
    cache_path = _cache_path(cache_dir, symbol, interval)
    cached = _read_cache(cache_path)

    tf_ms = _tf_to_ms(interval)
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)

    cursor = start_ms
    if cached is not None and not cached.empty:
        cached_max_ms = int(cached["open_time"].max().timestamp() * 1000)
        if cached_max_ms + tf_ms >= end_ms:
            return _slice(cached, start, end)
        cursor = cached_max_ms + tf_ms

    new_rows: list = []
    while cursor < end_ms:
        attempts = 0
        while True:
            try:
                rows = client.klines(
                    symbol, interval,
                    startTime=cursor, endTime=end_ms, limit=max_per_call,
                )
                break
            except Exception as e:
                attempts += 1
                if attempts >= retry_max:
                    raise
                wait = min(2 ** attempts, 30)
                logger.warning(f"klines fetch failed ({e}); retrying in {wait}s")
                time.sleep(wait)
        if not rows:
            break
        new_rows.extend(rows)
        last_open_ms = int(rows[-1][0])
        cursor = last_open_ms + tf_ms

    new_df = _klines_to_df(new_rows) if new_rows else pd.DataFrame(columns=REQUIRED_COLS)
    if cached is not None:
        full = pd.concat([cached, new_df], ignore_index=True)
        full = full.drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)
    else:
        full = new_df

    _write_cache(cache_path, full)
    return _slice(full, start, end)


def _slice(df: pd.DataFrame, start: datetime, end: datetime) -> pd.DataFrame:
    return df[(df["open_time"] >= start) & (df["open_time"] <= end)].reset_index(drop=True)
```

- [ ] **Step 4: Run — verify PASS**

Run: `pytest tests/backtesting/test_data_loader.py -v`
Expected: 6 passed total (3 from Task 3 + 3 new)

- [ ] **Step 5: Commit**

```bash
git add backtesting/data_loader.py tests/backtesting/test_data_loader.py
git commit -m "feat(backtesting): Binance kline downloader with parquet cache + gap-fill"
```

---

## Task 5: `data_feed.py` — bar access + master timeline

**Files:**
- Create: `backtesting/data_feed.py`
- Create: `tests/backtesting/test_data_feed.py`

- [ ] **Step 1: Write failing test**

```python
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from backtesting.data_feed import DataFeed
from backtesting.types import Bar


def test_bar_returns_matching_close_time(synthetic_5m_300):
    feed = DataFeed(bars={("BTCUSDT", "5m"): synthetic_5m_300})
    # close_time of bar at index 10: open_time[10] + 5m
    target_close = synthetic_5m_300["open_time"].iloc[10] + timedelta(minutes=5)
    bar = feed.bar("BTCUSDT", "5m", target_close)
    assert bar is not None
    assert bar.close == pytest.approx(synthetic_5m_300["close"].iloc[10])


def test_bar_returns_none_for_unknown_time(synthetic_5m_300):
    feed = DataFeed(bars={("BTCUSDT", "5m"): synthetic_5m_300})
    bar = feed.bar("BTCUSDT", "5m", datetime(2099, 1, 1, tzinfo=timezone.utc))
    assert bar is None


def test_next_bar_returns_first_bar_after_t(synthetic_5m_300):
    feed = DataFeed(bars={("BTCUSDT", "5m"): synthetic_5m_300})
    t = synthetic_5m_300["open_time"].iloc[10]
    nxt = feed.next_bar("BTCUSDT", "5m", t)
    assert nxt is not None
    assert nxt.open_time == synthetic_5m_300["open_time"].iloc[11]


def test_next_bar_at_end_returns_none(synthetic_5m_300):
    feed = DataFeed(bars={("BTCUSDT", "5m"): synthetic_5m_300})
    last_t = synthetic_5m_300["open_time"].iloc[-1]
    assert feed.next_bar("BTCUSDT", "5m", last_t) is None


def test_primary_close_times_in_range(synthetic_5m_300):
    feed = DataFeed(
        bars={("BTCUSDT", "5m"): synthetic_5m_300},
        primary_tf="5m", symbols=["BTCUSDT"],
        start=synthetic_5m_300["open_time"].iloc[100] + timedelta(minutes=5),
        end=synthetic_5m_300["open_time"].iloc[200] + timedelta(minutes=5),
    )
    times = feed.primary_close_times()
    assert len(times) == 101
    assert times == sorted(times)
```

- [ ] **Step 2: Run — verify FAIL**

Run: `pytest tests/backtesting/test_data_feed.py -v`
Expected: ImportError

- [ ] **Step 3: Implement DataFeed (without history yet)**

`backtesting/data_feed.py`:

```python
"""Time-aligned in-memory access to OHLCV across symbols and timeframes."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from backtesting.types import Bar, BacktestConfig, tf_to_timedelta


@dataclass
class DataFeed:
    bars: dict[tuple[str, str], pd.DataFrame]
    primary_tf: str = "5m"
    symbols: list[str] | None = None
    start: datetime | None = None
    end: datetime | None = None

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
```

- [ ] **Step 4: Run — verify PASS**

Run: `pytest tests/backtesting/test_data_feed.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backtesting/data_feed.py tests/backtesting/test_data_feed.py
git commit -m "feat(backtesting): DataFeed with bar/next_bar/primary_close_times"
```

---

## Task 6: `data_feed.py` — `history()` with no-lookahead invariant (CRITICAL)

**Files:**
- Modify: `backtesting/data_feed.py`
- Modify: `tests/backtesting/test_data_feed.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/backtesting/test_data_feed.py`:

```python
def test_history_never_returns_future_bars(synthetic_5m_300):
    """No-lookahead invariant: history(end=t) never returns close_time > t."""
    feed = DataFeed(bars={("BTCUSDT", "5m"): synthetic_5m_300})
    t = synthetic_5m_300["open_time"].iloc[100] + timedelta(minutes=5)  # close of bar 100
    hist = feed.history("BTCUSDT", "5m", end=t, limit=200)
    close_times = hist["open_time"] + timedelta(minutes=5)
    assert (close_times <= t).all()
    assert len(hist) == 101  # bars 0..100 inclusive


def test_history_returns_last_n_bars(synthetic_5m_300):
    feed = DataFeed(bars={("BTCUSDT", "5m"): synthetic_5m_300})
    t = synthetic_5m_300["open_time"].iloc[250] + timedelta(minutes=5)
    hist = feed.history("BTCUSDT", "5m", end=t, limit=50)
    assert len(hist) == 50
    assert hist["open_time"].iloc[-1] == synthetic_5m_300["open_time"].iloc[250]
    assert hist["open_time"].iloc[0] == synthetic_5m_300["open_time"].iloc[201]


def test_history_mtf_alignment_excludes_open_bar(synthetic_5m_300, synthetic_1h_300):
    """An hourly bar must NOT appear in history() until its close has passed."""
    feed = DataFeed(bars={
        ("BTCUSDT", "5m"): synthetic_5m_300,
        ("BTCUSDT", "1h"): synthetic_1h_300,
    })
    # Pick t = 1h bar 10 open + 30 minutes (mid-hour). The 1h bar at index 10 is still open.
    t = synthetic_1h_300["open_time"].iloc[10] + timedelta(minutes=30)
    hist_1h = feed.history("BTCUSDT", "1h", end=t, limit=200)
    last_open = hist_1h["open_time"].iloc[-1]
    # Last 1h bar must be the one whose close is <= t. close = open + 1h.
    # open[10] + 1h > t (open[10] + 30m). So last bar must be bar 9 (open[9] + 1h <= t).
    assert last_open == synthetic_1h_300["open_time"].iloc[9]


def test_history_returns_dataframe_with_signal_engine_columns(synthetic_5m_300):
    """SignalEngine expects DataFrame columns Open/High/Low/Close/Volume (capitalized)."""
    feed = DataFeed(bars={("BTCUSDT", "5m"): synthetic_5m_300})
    t = synthetic_5m_300["open_time"].iloc[100] + timedelta(minutes=5)
    hist = feed.history("BTCUSDT", "5m", end=t, limit=50)
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        assert col in hist.columns
```

- [ ] **Step 2: Run — verify FAIL**

Run: `pytest tests/backtesting/test_data_feed.py -v`
Expected: AttributeError on `history` method

- [ ] **Step 3: Implement `history()`**

Add to `DataFeed` class in `backtesting/data_feed.py`:

```python
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
```

- [ ] **Step 4: Run — verify PASS**

Run: `pytest tests/backtesting/test_data_feed.py -v`
Expected: 9 passed (5 from Task 5 + 4 new)

- [ ] **Step 5: Commit**

```bash
git add backtesting/data_feed.py tests/backtesting/test_data_feed.py
git commit -m "feat(backtesting): DataFeed.history with no-lookahead and MTF alignment"
```

---

## Task 7: `execution_sim.py` — `entry_fill()` with slippage + fees

**Files:**
- Create: `backtesting/execution_sim.py`
- Create: `tests/backtesting/test_execution_sim.py`

- [ ] **Step 1: Write failing tests**

```python
from datetime import datetime, timezone

import pytest

from backtesting.execution_sim import ExecutionSimulator
from backtesting.types import Bar, Position


def _bar(open_=100.0, high=110.0, low=95.0, close=105.0):
    return Bar(symbol="BTCUSDT", timeframe="5m",
               open_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
               open=open_, high=high, low=low, close=close, volume=1.0)


def test_entry_fill_long_includes_positive_slippage():
    sim = ExecutionSimulator(taker_fee_bps=4.0, slippage_bps=10.0,
                             fill_model="pessimistic")
    next_bar = _bar(open_=100.0)
    fill = sim.entry_fill_for(side="BUY", symbol="BTCUSDT", qty=1.0, next_bar=next_bar)
    # 10 bps adverse for BUY => 100 * 1.001 = 100.1
    assert fill.price == pytest.approx(100.1)
    assert fill.fee == pytest.approx(100.1 * 1.0 * 4.0 / 10_000)
    assert fill.reason == "ENTRY"
    assert fill.side == "BUY"


def test_entry_fill_short_includes_negative_slippage():
    sim = ExecutionSimulator(taker_fee_bps=4.0, slippage_bps=10.0,
                             fill_model="pessimistic")
    next_bar = _bar(open_=100.0)
    fill = sim.entry_fill_for(side="SELL", symbol="BTCUSDT", qty=1.0, next_bar=next_bar)
    # 10 bps adverse for SELL => 100 * 0.999 = 99.9
    assert fill.price == pytest.approx(99.9)


def test_entry_fee_zero_when_bps_zero():
    sim = ExecutionSimulator(taker_fee_bps=0.0, slippage_bps=0.0,
                             fill_model="pessimistic")
    fill = sim.entry_fill_for(side="BUY", symbol="X", qty=2.0, next_bar=_bar(open_=50.0))
    assert fill.price == 50.0
    assert fill.fee == 0.0
```

- [ ] **Step 2: Run — verify FAIL**

Run: `pytest tests/backtesting/test_execution_sim.py -v`
Expected: ImportError

- [ ] **Step 3: Implement entry_fill**

`backtesting/execution_sim.py`:

```python
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
```

- [ ] **Step 4: Run — verify PASS**

Run: `pytest tests/backtesting/test_execution_sim.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backtesting/execution_sim.py tests/backtesting/test_execution_sim.py
git commit -m "feat(backtesting): ExecutionSimulator entry fills with slippage + fees"
```

---

## Task 8: `execution_sim.py` — `check_exit()` intra-bar SL/TP

**Files:**
- Modify: `backtesting/execution_sim.py`
- Modify: `tests/backtesting/test_execution_sim.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/backtesting/test_execution_sim.py`:

```python
def _long_pos(sl: float, tp: float):
    return Position(symbol="BTCUSDT", direction="LONG", qty=1.0,
                    entry_price=100.0, stop_loss=sl, take_profit=tp,
                    entry_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    entry_fee=0.0, entry_atr=2.0, trade_id=1)


def _short_pos(sl: float, tp: float):
    return Position(symbol="BTCUSDT", direction="SHORT", qty=1.0,
                    entry_price=100.0, stop_loss=sl, take_profit=tp,
                    entry_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    entry_fee=0.0, entry_atr=2.0, trade_id=2)


def test_check_exit_long_sl_only():
    sim = ExecutionSimulator(0, 0, "pessimistic")
    pos = _long_pos(sl=95.0, tp=120.0)
    fill = sim.check_exit(pos, _bar(open_=98, high=99, low=94, close=97))
    assert fill is not None
    assert fill.reason == "SL"
    assert fill.price == pytest.approx(95.0)
    assert fill.side == "SELL"


def test_check_exit_long_tp_only():
    sim = ExecutionSimulator(0, 0, "pessimistic")
    pos = _long_pos(sl=80.0, tp=110.0)
    fill = sim.check_exit(pos, _bar(open_=100, high=115, low=99, close=112))
    assert fill is not None
    assert fill.reason == "TP"
    assert fill.price == pytest.approx(110.0)


def test_check_exit_long_both_pessimistic_picks_sl():
    sim = ExecutionSimulator(0, 0, "pessimistic")
    pos = _long_pos(sl=95.0, tp=110.0)
    # Bar where both SL=95 and TP=110 are inside [94, 115]
    fill = sim.check_exit(pos, _bar(open_=100, high=115, low=94, close=108))
    assert fill is not None
    assert fill.reason == "SL"


def test_check_exit_short_sl_when_high_breaches():
    sim = ExecutionSimulator(0, 0, "pessimistic")
    pos = _short_pos(sl=105.0, tp=90.0)
    fill = sim.check_exit(pos, _bar(open_=100, high=106, low=99, close=104))
    assert fill is not None
    assert fill.reason == "SL"
    assert fill.side == "BUY"
    assert fill.price == pytest.approx(105.0)


def test_check_exit_neither_returns_none():
    sim = ExecutionSimulator(0, 0, "pessimistic")
    pos = _long_pos(sl=80.0, tp=120.0)
    assert sim.check_exit(pos, _bar(open_=100, high=110, low=95, close=105)) is None


def test_check_exit_applies_slippage_and_fee():
    sim = ExecutionSimulator(taker_fee_bps=4.0, slippage_bps=10.0,
                             fill_model="pessimistic")
    pos = _long_pos(sl=95.0, tp=120.0)
    fill = sim.check_exit(pos, _bar(open_=98, high=99, low=94, close=97))
    # Long exit = SELL; slippage adverse for SELL => 95 * 0.999 = 94.905
    assert fill.price == pytest.approx(94.905)
    assert fill.fee == pytest.approx(94.905 * 1.0 * 4.0 / 10_000)
```

- [ ] **Step 2: Run — verify FAIL**

Run: `pytest tests/backtesting/test_execution_sim.py -v`
Expected: AttributeError on `check_exit`

- [ ] **Step 3: Implement `check_exit`**

Add to `ExecutionSimulator` class in `backtesting/execution_sim.py`:

```python
    def check_exit(self, pos: Position, bar: Bar) -> Optional[Fill]:
        """Return Fill if SL or TP hit inside bar; else None.

        Pessimistic model: if both SL and TP are inside the bar's range
        in the same candle, assume SL fills first.
        """
        long = pos.direction == "LONG"
        sl_hit = (bar.low <= pos.stop_loss) if long else (bar.high >= pos.stop_loss)
        tp_hit = (bar.high >= pos.take_profit) if long else (bar.low <= pos.take_profit)

        if not sl_hit and not tp_hit:
            return None

        # Resolve which fires
        if sl_hit and tp_hit:
            picked = "SL" if self.fill_model == "pessimistic" else "TP"
        elif sl_hit:
            picked = "SL"
        else:
            picked = "TP"

        target_price = pos.stop_loss if picked == "SL" else pos.take_profit
        exit_side: Literal["BUY", "SELL"] = "SELL" if long else "BUY"
        fill_price = _apply_slippage(target_price, self.slippage_bps, exit_side)
        fee = _fee(fill_price, pos.qty, self.taker_fee_bps)

        return Fill(symbol=pos.symbol, side=exit_side, qty=pos.qty,
                    price=fill_price, fee=fee, timestamp=bar.close_time,
                    reason=picked)
```

- [ ] **Step 4: Run — verify PASS**

Run: `pytest tests/backtesting/test_execution_sim.py -v`
Expected: 9 passed (3 from Task 7 + 6 new)

- [ ] **Step 5: Commit**

```bash
git add backtesting/execution_sim.py tests/backtesting/test_execution_sim.py
git commit -m "feat(backtesting): intra-bar SL/TP exit simulation with pessimistic fill"
```

---

## Task 9: `portfolio.py` — PortfolioBook

**Files:**
- Create: `backtesting/portfolio.py`
- Create: `tests/backtesting/test_portfolio.py`

- [ ] **Step 1: Write failing tests**

```python
from datetime import datetime, timezone

import pandas as pd
import pytest

from backtesting.data_feed import DataFeed
from backtesting.portfolio import PortfolioBook
from backtesting.types import Bar, Fill, Position


def _fill(symbol="BTCUSDT", side="BUY", qty=1.0, price=100.0, fee=0.04):
    return Fill(symbol=symbol, side=side, qty=qty, price=price, fee=fee,
                timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), reason="ENTRY")


def _open_long(book, symbol="BTCUSDT", qty=1.0, price=100.0,
               sl=95.0, tp=110.0, atr=2.0, trade_id=1):
    fill = _fill(symbol=symbol, side="BUY", qty=qty, price=price)
    return book.open_long(symbol=symbol, qty=qty, entry_fill=fill,
                          stop_loss=sl, take_profit=tp, atr=atr,
                          trade_id=trade_id)


def test_initial_state():
    book = PortfolioBook(initial_capital=10_000.0)
    assert book.cash == 10_000.0
    assert book.free_cash() == 10_000.0
    assert book.open_positions() == []
    assert not book.has_position("BTCUSDT")


def test_open_long_deducts_cash_and_fee():
    book = PortfolioBook(10_000.0)
    pos = _open_long(book, qty=1.0, price=100.0)
    assert pos.symbol == "BTCUSDT"
    # 1.0 * 100 + 0.04 fee
    assert book.cash == pytest.approx(10_000.0 - 100.04)


def test_one_position_per_symbol():
    book = PortfolioBook(10_000.0)
    _open_long(book, trade_id=1)
    with pytest.raises(ValueError, match="already has a position"):
        _open_long(book, trade_id=2)


def test_no_double_allocation_via_free_cash():
    book = PortfolioBook(150.0)
    _open_long(book, symbol="BTCUSDT", qty=1.0, price=100.0)
    # free_cash now ~ 49.96 — caller must check before second entry
    assert book.free_cash() < 100.0


def test_close_returns_pnl_and_credits_cash():
    book = PortfolioBook(10_000.0)
    pos = _open_long(book, qty=1.0, price=100.0)
    exit_fill = Fill(symbol="BTCUSDT", side="SELL", qty=1.0, price=110.0,
                     fee=0.044, timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
                     reason="TP")
    realized_pnl, equity = book.close(pos, exit_fill)
    # PnL = (110 - 100) * 1 - entry_fee - exit_fee = 10 - 0.04 - 0.044
    assert realized_pnl == pytest.approx(10.0 - 0.04 - 0.044)
    assert book.has_position("BTCUSDT") is False


def test_equity_marks_to_market():
    book = PortfolioBook(10_000.0)
    _open_long(book, symbol="BTCUSDT", qty=1.0, price=100.0)
    df = pd.DataFrame({
        "open_time": [datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)],
        "open": [100.0], "high": [120.0], "low": [99.0], "close": [115.0],
        "volume": [1.0],
    })
    feed = DataFeed(bars={("BTCUSDT", "5m"): df}, primary_tf="5m")
    t = df["open_time"].iloc[0] + pd.Timedelta(minutes=5)
    eq = book.equity(feed, t, primary_tf="5m")
    # cash + market_value = (10000 - 100.04) + (1 * 115)
    assert eq == pytest.approx(10_000.0 - 100.04 + 115.0)
```

- [ ] **Step 2: Run — verify FAIL**

Run: `pytest tests/backtesting/test_portfolio.py -v`
Expected: ImportError

- [ ] **Step 3: Implement PortfolioBook**

`backtesting/portfolio.py`:

```python
"""PortfolioBook: tracks cash and open positions for the backtester."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from backtesting.data_feed import DataFeed
from backtesting.types import Fill, Position


class PortfolioBook:
    def __init__(self, initial_capital: float):
        self.initial_capital = float(initial_capital)
        self.cash: float = float(initial_capital)
        self._positions: dict[str, Position] = {}

    def free_cash(self) -> float:
        return self.cash

    def has_position(self, symbol: str) -> bool:
        return symbol in self._positions

    def open_positions(self) -> list[Position]:
        return list(self._positions.values())

    def open_long(self, symbol: str, qty: float, entry_fill: Fill,
                  stop_loss: float, take_profit: float, atr: float,
                  trade_id: int) -> Position:
        return self._open(symbol, "LONG", qty, entry_fill, stop_loss,
                          take_profit, atr, trade_id)

    def open_short(self, symbol: str, qty: float, entry_fill: Fill,
                   stop_loss: float, take_profit: float, atr: float,
                   trade_id: int) -> Position:
        return self._open(symbol, "SHORT", qty, entry_fill, stop_loss,
                          take_profit, atr, trade_id)

    def _open(self, symbol, direction, qty, entry_fill, sl, tp, atr, trade_id):
        if symbol in self._positions:
            raise ValueError(f"{symbol} already has a position")
        notional = qty * entry_fill.price
        self.cash -= notional + entry_fill.fee
        pos = Position(symbol=symbol, direction=direction, qty=qty,
                       entry_price=entry_fill.price, stop_loss=sl,
                       take_profit=tp, entry_time=entry_fill.timestamp,
                       entry_fee=entry_fill.fee, entry_atr=atr,
                       trade_id=trade_id)
        self._positions[symbol] = pos
        return pos

    def close(self, pos: Position, exit_fill: Fill) -> tuple[float, float]:
        """Returns (realized_pnl, equity_after_close). Removes position."""
        if pos.symbol not in self._positions:
            raise ValueError(f"No open position for {pos.symbol}")
        proceeds = pos.qty * exit_fill.price
        if pos.direction == "LONG":
            gross = (exit_fill.price - pos.entry_price) * pos.qty
            self.cash += proceeds - exit_fill.fee
        else:
            gross = (pos.entry_price - exit_fill.price) * pos.qty
            # SHORT: we already debited cash on entry (qty * entry_price); on close
            # we credit (entry + gross) - fee = (qty * exit_price flipped to gain).
            self.cash += pos.qty * pos.entry_price + gross - exit_fill.fee
        realized = gross - pos.entry_fee - exit_fill.fee
        del self._positions[pos.symbol]
        return realized, self.cash

    def equity(self, feed: DataFeed, t: datetime, primary_tf: str) -> float:
        """Mark-to-market: cash + sum of position market values at last close <= t."""
        total = self.cash
        for pos in self._positions.values():
            bar = feed.bar(pos.symbol, primary_tf, t)
            if bar is None:
                # No bar at exactly t for this symbol — use last close from history
                hist = feed.history(pos.symbol, primary_tf, end=t, limit=1)
                if len(hist) == 0:
                    continue
                mark_price = float(hist["Close"].iloc[-1])
            else:
                mark_price = bar.close
            if pos.direction == "LONG":
                total += pos.qty * mark_price
            else:
                # SHORT: paid pos.qty * entry_price into book on entry; mark gain = (entry-mark)*qty
                total += pos.qty * pos.entry_price + (pos.entry_price - mark_price) * pos.qty
        return total
```

- [ ] **Step 4: Run — verify PASS**

Run: `pytest tests/backtesting/test_portfolio.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backtesting/portfolio.py tests/backtesting/test_portfolio.py
git commit -m "feat(backtesting): PortfolioBook with cash/MTM equity and one-position-per-symbol"
```

---

## Task 10: `BacktestRiskManager` subclass

**Files:**
- Create: `backtesting/risk.py`
- Create: `tests/backtesting/test_risk.py`

- [ ] **Step 1: Write failing test**

```python
import sys
from pathlib import Path

import pytest

# RiskManager lives in src/risk_manager.py — make src importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from risk_manager import RiskManager
from backtesting.risk import BacktestRiskManager


def test_state_file_isolated_per_run(tmp_path):
    rm = BacktestRiskManager(run_dir=tmp_path)
    assert rm.STATE_FILE == tmp_path / "risk_state.json"
    rm.record_trade_open()
    assert (tmp_path / "risk_state.json").exists()


def test_two_runs_do_not_share_state(tmp_path):
    a = tmp_path / "run_a"; a.mkdir()
    b = tmp_path / "run_b"; b.mkdir()
    rm_a = BacktestRiskManager(run_dir=a)
    rm_a.record_trade_open()
    rm_b = BacktestRiskManager(run_dir=b)
    assert rm_b.status()["open_positions"] == 0


def test_class_attribute_restored_on_close(tmp_path):
    """After context-manager exit, RiskManager.STATE_FILE returns to default."""
    original = RiskManager.STATE_FILE
    with BacktestRiskManager(run_dir=tmp_path):
        assert RiskManager.STATE_FILE != original
    assert RiskManager.STATE_FILE == original


def test_compute_position_size_reused(tmp_path):
    """The inherited sizing logic still works."""
    rm = BacktestRiskManager(run_dir=tmp_path)
    size = rm.compute_position_size(equity=10_000.0, entry_price=100.0,
                                     stop_price=99.0, take_profit=102.0)
    assert size is not None
    assert size.quantity > 0
```

- [ ] **Step 2: Run — verify FAIL**

Run: `pytest tests/backtesting/test_risk.py -v`
Expected: ImportError

- [ ] **Step 3: Implement BacktestRiskManager**

`backtesting/risk.py`:

```python
"""BacktestRiskManager: subclass of live RiskManager with isolated state file."""
from __future__ import annotations

import sys
from pathlib import Path

# Make src/risk_manager.py importable
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from risk_manager import RiskManager  # noqa: E402


class BacktestRiskManager(RiskManager):
    """Run-isolated RiskManager.

    Overrides the class-level STATE_FILE to a per-run path so backtests
    never read or write the live `logs/risk_state.json`. Acts as a context
    manager that restores the original class attribute on exit.
    """

    def __init__(self, run_dir: Path, **kwargs):
        self._original_state_file = RiskManager.STATE_FILE
        # Override at the CLASS level so super().__init__ sees the new path
        RiskManager.STATE_FILE = run_dir / "risk_state.json"
        super().__init__(**kwargs)

    # Allow `with BacktestRiskManager(...)` for guaranteed cleanup
    def __enter__(self) -> "BacktestRiskManager":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        RiskManager.STATE_FILE = self._original_state_file

    def close(self) -> None:
        RiskManager.STATE_FILE = self._original_state_file
```

- [ ] **Step 4: Run — verify PASS**

Run: `pytest tests/backtesting/test_risk.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backtesting/risk.py tests/backtesting/test_risk.py
git commit -m "feat(backtesting): BacktestRiskManager with isolated per-run state"
```

---

## Task 11: `backtester.py` — portfolio-mode orchestrator

**Files:**
- Create: `backtesting/backtester.py`
- Create: `tests/backtesting/test_backtester.py`

- [ ] **Step 1: Write end-to-end failing test**

```python
"""End-to-end smoke + invariants test for the portfolio-mode backtester.

The strategy here is a stub that always emits a LONG signal whenever called —
this lets us verify the orchestrator's flow (ordering, capital, max_positions,
exits-before-entries) independently of SignalEngine's confluence logic.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from backtesting.backtester import run_portfolio
from backtesting.data_feed import DataFeed
from backtesting.types import BacktestConfig
from backtesting.signal_stub import AlwaysLongSignalEngine  # added in step 3 of this task


def _build_feed(make_klines, symbols, n_5m=200, n_1h=20):
    bars = {}
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i, s in enumerate(symbols):
        bars[(s, "5m")] = make_klines(start=start, n=n_5m, tf_minutes=5,
                                       base_price=100.0 + i * 10, seed=i)
        bars[(s, "1h")] = make_klines(start=start, n=n_1h, tf_minutes=60,
                                       base_price=100.0 + i * 10, seed=i + 100)
    return bars


def test_end_to_end_completes(tmp_path, make_klines):
    bars = _build_feed(make_klines, ["BTCUSDT", "ETHUSDT"], n_5m=200, n_1h=20)
    cfg = BacktestConfig(
        symbols=["BTCUSDT", "ETHUSDT"], primary_tf="5m", confirm_tf="1h",
        start=datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc),
        end=datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
        initial_capital=10_000.0,
    )
    feed = DataFeed(bars=bars, primary_tf="5m", symbols=cfg.symbols,
                    start=cfg.start, end=cfg.end)

    with patch("backtesting.backtester.SignalEngine", AlwaysLongSignalEngine):
        result = run_portfolio(cfg, feed=feed, run_dir=tmp_path)

    assert "equity_series" in result
    assert "closed_trades" in result
    assert len(result["equity_series"]) > 0
    assert result["final_equity"] > 0


def test_deterministic_same_seed(tmp_path, make_klines):
    bars = _build_feed(make_klines, ["BTCUSDT"], n_5m=120, n_1h=12)
    cfg = BacktestConfig(
        symbols=["BTCUSDT"], primary_tf="5m", confirm_tf="1h",
        start=datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc),
        end=datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc),
        initial_capital=10_000.0, seed=42,
    )
    feed = DataFeed(bars=bars, primary_tf="5m", symbols=cfg.symbols,
                    start=cfg.start, end=cfg.end)

    with patch("backtesting.backtester.SignalEngine", AlwaysLongSignalEngine):
        a = run_portfolio(cfg, feed=feed, run_dir=tmp_path / "a")
        b = run_portfolio(cfg, feed=feed, run_dir=tmp_path / "b")

    assert a["final_equity"] == pytest.approx(b["final_equity"])
    assert len(a["closed_trades"]) == len(b["closed_trades"])


def test_max_positions_cap_respected(tmp_path, make_klines):
    """With max_positions=1, only one symbol can hold a position at a time."""
    bars = _build_feed(make_klines, ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
                        n_5m=200, n_1h=20)
    cfg = BacktestConfig(
        symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"], primary_tf="5m",
        confirm_tf="1h",
        start=datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc),
        end=datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
        initial_capital=10_000.0,
    )
    feed = DataFeed(bars=bars, primary_tf="5m", symbols=cfg.symbols,
                    start=cfg.start, end=cfg.end)

    with patch("backtesting.backtester.SignalEngine", AlwaysLongSignalEngine):
        result = run_portfolio(cfg, feed=feed, run_dir=tmp_path,
                                max_positions_override=1)

    # At every snapshot, open_positions <= 1
    snaps = result["snapshots"]
    assert all(s["open_positions"] <= 1 for s in snaps)
```

- [ ] **Step 2: Add the stub module**

`backtesting/signal_stub.py`:

```python
"""Test-only stub: emits a LONG signal on every call.

Allows orchestrator tests to run without exercising the full SignalEngine.
The stub mirrors SignalEngine's interface (constructor + analyse method).
"""
from datetime import datetime
from typing import Callable, Optional

import sys
from pathlib import Path
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from signal_engine import Signal, SignalDirection  # noqa: E402


class AlwaysLongSignalEngine:
    def __init__(self, fetch_klines_fn: Callable, get_funding_rate_fn=None):
        self._fetch = fetch_klines_fn

    def analyse(self, symbol: str, primary_tf: str = "5m",
                confirm_tf: str = "1h") -> Optional[Signal]:
        df = self._fetch(symbol, primary_tf, 50)
        if len(df) < 2:
            return None
        price = float(df["Close"].iloc[-1])
        atr = max(0.5, abs(price - float(df["Close"].iloc[-2])) + 0.5)
        return Signal(
            direction=SignalDirection.LONG,
            confidence=80.0,
            timeframe=primary_tf,
            symbol=symbol,
            price=price,
            atr=atr,
            stop_loss=round(price - 1.6 * atr, 6),
            take_profit=round(price + 2.8 * atr, 6),
            indicators={"price": price, "atr": atr},
            reasons=["stub"],
        )
```

- [ ] **Step 3: Run — verify FAIL**

Run: `pytest tests/backtesting/test_backtester.py -v`
Expected: ImportError on `backtesting.backtester`

- [ ] **Step 4: Implement orchestrator**

`backtesting/backtester.py`:

```python
"""Portfolio-mode backtester orchestrator.

Reuses SignalEngine (via injected historical fetcher), BacktestRiskManager
(per-run isolated state), TradeTracker (per-run SQLite), PortfolioBook,
ExecutionSimulator, and DataFeed.

Loop semantics per primary-TF close time `t`:
  1. Process exits for open positions (frees capital + slots)
  2. Mark-to-market and update equity
  3. If trading allowed: generate signals in cfg.symbols order, open positions
     subject to free_cash and max_positions
"""
from __future__ import annotations

import logging
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

from backtesting.data_feed import DataFeed
from backtesting.execution_sim import ExecutionSimulator
from backtesting.portfolio import PortfolioBook
from backtesting.risk import BacktestRiskManager
from backtesting.types import BacktestConfig

# Make src importable for SignalEngine + TradeTracker
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from signal_engine import SignalEngine  # noqa: E402
from trade_tracker import TradeTracker  # noqa: E402

logger = logging.getLogger(__name__)


def _make_historical_fetcher(feed: DataFeed, current_time: datetime) -> Callable:
    def fetch_klines(symbol: str, interval: str, limit: int = 200) -> pd.DataFrame:
        return feed.history(symbol, interval, end=current_time, limit=limit)
    return fetch_klines


def run_portfolio(cfg: BacktestConfig, feed: DataFeed, run_dir: Path,
                   *, max_positions_override: Optional[int] = None) -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    random.seed(cfg.seed)

    risk_kwargs = {}
    if max_positions_override is not None:
        risk_kwargs["max_positions"] = max_positions_override

    with BacktestRiskManager(run_dir=run_dir, **risk_kwargs) as risk:
        book = PortfolioBook(initial_capital=cfg.initial_capital)
        tracker = TradeTracker(db_path=run_dir / "trades.db")
        sim = ExecutionSimulator(
            taker_fee_bps=cfg.taker_fee_bps,
            slippage_bps=cfg.slippage_bps,
            fill_model=cfg.fill_model,
        )

        equity_series: list[tuple[datetime, float]] = []
        snapshots: list[dict] = []
        timeline = feed.primary_close_times()

        for t in timeline:
            # PHASE 1: exits
            for pos in list(book.open_positions()):
                bar = feed.bar(pos.symbol, cfg.primary_tf, t)
                if bar is None:
                    continue
                fill = sim.check_exit(pos, bar)
                if fill is None:
                    # Update trailing stop for the next bar
                    new_sl = risk.trailing_stop(
                        entry_price=pos.entry_price,
                        current_price=bar.close,
                        current_stop=pos.stop_loss,
                        atr=pos.entry_atr,
                        direction=pos.direction,
                    )
                    pos.stop_loss = new_sl
                    continue
                realized_pnl, _ = book.close(pos, fill)
                tracker.close_trade(pos.trade_id, fill.price, fill.reason)
                risk.record_trade_close(realized_pnl, book.cash)

            # PHASE 2: equity / MTM
            equity = book.equity(feed, t, primary_tf=cfg.primary_tf)
            risk.update_equity(equity)
            equity_series.append((t, equity))

            if not risk.is_trading_allowed():
                snapshots.append({"t": t, "equity": equity,
                                   "open_positions": len(book.open_positions()),
                                   "halted": True})
                continue

            # PHASE 3: entries (deterministic order = cfg.symbols)
            engine = SignalEngine(
                fetch_klines_fn=_make_historical_fetcher(feed, t),
                get_funding_rate_fn=lambda s: 0.0,
            )
            for sym in cfg.symbols:
                if book.has_position(sym):
                    continue
                if not risk.is_trading_allowed():
                    break
                sig = engine.analyse(sym, cfg.primary_tf, cfg.confirm_tf)
                if sig is None:
                    continue

                size = risk.compute_position_size(
                    equity=equity, entry_price=sig.price,
                    stop_price=sig.stop_loss, take_profit=sig.take_profit,
                )
                if size is None or size.quantity <= 0:
                    continue

                next_bar = feed.next_bar(sym, cfg.primary_tf, t)
                if next_bar is None:
                    continue
                side = "BUY" if sig.direction.value == "LONG" else "SELL"
                fill = sim.entry_fill_for(side=side, symbol=sym,
                                           qty=size.quantity, next_bar=next_bar)
                notional = fill.qty * fill.price + fill.fee
                if notional > book.free_cash():
                    continue

                trade_id = tracker.open_trade(
                    symbol=sym, direction=sig.direction.value,
                    entry_price=fill.price, stop_loss=sig.stop_loss,
                    take_profit=sig.take_profit, quantity=fill.qty,
                    order_id=f"BT-{trade_id_seq()}",
                )
                if sig.direction.value == "LONG":
                    pos = book.open_long(sym, fill.qty, fill,
                                          sig.stop_loss, sig.take_profit,
                                          atr=sig.atr, trade_id=trade_id)
                else:
                    pos = book.open_short(sym, fill.qty, fill,
                                           sig.stop_loss, sig.take_profit,
                                           atr=sig.atr, trade_id=trade_id)
                risk.record_trade_open()

            snapshots.append({"t": t, "equity": equity,
                               "open_positions": len(book.open_positions()),
                               "halted": False})

        closed_trades = tracker.get_closed_trades(limit=10**9)
        return {
            "equity_series": equity_series,
            "snapshots": snapshots,
            "closed_trades": closed_trades,
            "final_equity": equity_series[-1][1] if equity_series else cfg.initial_capital,
            "stats": tracker.get_stats(),
        }


_seq = 0


def trade_id_seq() -> int:
    global _seq
    _seq += 1
    return _seq
```

- [ ] **Step 5: Run — verify PASS**

Run: `pytest tests/backtesting/test_backtester.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add backtesting/backtester.py backtesting/signal_stub.py tests/backtesting/test_backtester.py
git commit -m "feat(backtesting): portfolio-mode orchestrator with end-to-end tests"
```

---

## Task 12: Per-symbol mode wrapper

**Files:**
- Modify: `backtesting/backtester.py`
- Modify: `tests/backtesting/test_backtester.py`

- [ ] **Step 1: Add failing test**

Append to `tests/backtesting/test_backtester.py`:

```python
def test_per_symbol_runs_isolated(tmp_path, make_klines):
    bars = _build_feed(make_klines, ["BTCUSDT", "ETHUSDT"], n_5m=120, n_1h=12)
    cfg = BacktestConfig(
        symbols=["BTCUSDT", "ETHUSDT"], primary_tf="5m", confirm_tf="1h",
        start=datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc),
        end=datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc),
        initial_capital=10_000.0, mode="per_symbol",
    )
    feed = DataFeed(bars=bars, primary_tf="5m", symbols=cfg.symbols,
                    start=cfg.start, end=cfg.end)
    from backtesting.backtester import run_per_symbol
    with patch("backtesting.backtester.SignalEngine", AlwaysLongSignalEngine):
        result = run_per_symbol(cfg, feed=feed, run_dir=tmp_path)
    assert set(result["per_symbol"].keys()) == {"BTCUSDT", "ETHUSDT"}
    for sym in ["BTCUSDT", "ETHUSDT"]:
        sub = result["per_symbol"][sym]
        assert sub["final_equity"] > 0
```

- [ ] **Step 2: Run — verify FAIL**

Run: `pytest tests/backtesting/test_backtester.py::test_per_symbol_runs_isolated -v`
Expected: ImportError on `run_per_symbol`

- [ ] **Step 3: Implement per_symbol wrapper**

Append to `backtesting/backtester.py`:

```python
def run_per_symbol(cfg: BacktestConfig, feed: DataFeed, run_dir: Path) -> dict:
    """Run portfolio backtester independently per symbol with fresh capital."""
    out = {"per_symbol": {}}
    for sym in cfg.symbols:
        sub_dir = run_dir / sym
        sub_cfg = BacktestConfig(
            symbols=[sym], primary_tf=cfg.primary_tf, confirm_tf=cfg.confirm_tf,
            start=cfg.start, end=cfg.end, initial_capital=cfg.initial_capital,
            taker_fee_bps=cfg.taker_fee_bps, slippage_bps=cfg.slippage_bps,
            fill_model=cfg.fill_model, mode="portfolio",
            confidence_threshold=cfg.confidence_threshold, seed=cfg.seed,
        )
        out["per_symbol"][sym] = run_portfolio(sub_cfg, feed=feed, run_dir=sub_dir)
    return out
```

- [ ] **Step 4: Run — verify PASS**

Run: `pytest tests/backtesting/test_backtester.py -v`
Expected: 4 passed total

- [ ] **Step 5: Commit**

```bash
git add backtesting/backtester.py tests/backtesting/test_backtester.py
git commit -m "feat(backtesting): per-symbol mode wrapper running isolated runs"
```

---

## Task 13: `performance.py` — Sharpe, Sortino, CAGR, drawdown

**Files:**
- Create: `backtesting/performance.py`
- Create: `tests/backtesting/test_performance.py`

- [ ] **Step 1: Write failing tests**

```python
import math
from datetime import datetime, timedelta, timezone

import pytest

from backtesting.performance import (
    annualized_sharpe, max_drawdown, cagr_pct, build_report,
)


def _series(values, tf_minutes=5, start=datetime(2026, 1, 1, tzinfo=timezone.utc)):
    return [(start + timedelta(minutes=tf_minutes * i), v) for i, v in enumerate(values)]


def test_max_drawdown_simple():
    eq = _series([100, 110, 120, 90, 95, 130])
    dd, dur = max_drawdown(eq)
    # Peak 120 -> trough 90 = 25% drawdown
    assert dd == pytest.approx(25.0, abs=0.01)
    assert dur == 1  # 1 bar from peak (idx 2) to trough (idx 3)


def test_max_drawdown_monotonic_up():
    eq = _series([100, 105, 110, 115])
    dd, _ = max_drawdown(eq)
    assert dd == 0.0


def test_cagr_one_year_double():
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=365)
    eq = [(start, 100.0), (end, 200.0)]
    assert cagr_pct(eq) == pytest.approx(100.0, abs=0.5)


def test_sharpe_constant_returns_zero_std():
    eq = _series([100.0] * 10)
    # Constant -> std=0 -> Sharpe defined as 0 by convention
    assert annualized_sharpe(eq, primary_tf="5m") == 0.0


def test_sharpe_known_series_positive():
    # Strictly increasing returns => positive Sharpe
    eq = _series([100, 101, 102, 103, 104, 105])
    s = annualized_sharpe(eq, primary_tf="5m")
    assert s > 0


def test_build_report_sums_consistent():
    eq = _series([10_000, 10_500, 11_000, 10_200, 11_500])
    closed = []  # no trades; metrics still computable
    report = build_report(eq, closed, initial_capital=10_000.0,
                           primary_tf="5m")
    assert report["total_return_pct"] == pytest.approx(15.0)
    assert "max_drawdown_pct" in report
    assert "cagr_pct" in report
    assert "sharpe_annualized" in report
    assert report["total_trades"] == 0
```

- [ ] **Step 2: Run — verify FAIL**

Run: `pytest tests/backtesting/test_performance.py -v`
Expected: ImportError

- [ ] **Step 3: Implement metrics**

`backtesting/performance.py`:

```python
"""Performance metrics: Sharpe, Sortino, CAGR, drawdown, expectancy."""
from __future__ import annotations

import math
from datetime import datetime
from typing import Iterable

import numpy as np

# Bars per year for common Binance timeframes (used for Sharpe annualization)
_BARS_PER_YEAR = {
    "1m": 525_600, "3m": 175_200, "5m": 105_120, "15m": 35_040,
    "30m": 17_520, "1h": 8_760, "2h": 4_380, "4h": 2_190,
    "6h": 1_460, "8h": 1_095, "12h": 730, "1d": 365,
}


def _equity_values(equity_series: Iterable[tuple[datetime, float]]) -> np.ndarray:
    return np.array([v for _, v in equity_series], dtype=float)


def _log_returns(values: np.ndarray) -> np.ndarray:
    if len(values) < 2:
        return np.array([], dtype=float)
    return np.diff(np.log(values))


def annualized_sharpe(equity_series, primary_tf: str,
                       risk_free_per_bar: float = 0.0) -> float:
    values = _equity_values(equity_series)
    rets = _log_returns(values) - risk_free_per_bar
    if len(rets) == 0 or rets.std(ddof=1) == 0:
        return 0.0
    bars_yr = _BARS_PER_YEAR.get(primary_tf, 8_760)
    return float(rets.mean() / rets.std(ddof=1) * math.sqrt(bars_yr))


def annualized_sortino(equity_series, primary_tf: str) -> float:
    values = _equity_values(equity_series)
    rets = _log_returns(values)
    if len(rets) == 0:
        return 0.0
    downside = rets[rets < 0]
    if len(downside) == 0 or downside.std(ddof=1) == 0:
        return 0.0
    bars_yr = _BARS_PER_YEAR.get(primary_tf, 8_760)
    return float(rets.mean() / downside.std(ddof=1) * math.sqrt(bars_yr))


def max_drawdown(equity_series) -> tuple[float, int]:
    """Returns (max_drawdown_pct, duration_in_bars_from_peak_to_trough)."""
    values = _equity_values(equity_series)
    if len(values) == 0:
        return 0.0, 0
    peaks = np.maximum.accumulate(values)
    drawdowns = (peaks - values) / np.where(peaks == 0, 1, peaks)
    idx_trough = int(np.argmax(drawdowns))
    if drawdowns[idx_trough] == 0:
        return 0.0, 0
    idx_peak = int(np.argmax(values[: idx_trough + 1]))
    return float(drawdowns[idx_trough] * 100.0), idx_trough - idx_peak


def cagr_pct(equity_series) -> float:
    if len(equity_series) < 2:
        return 0.0
    start_t, start_v = equity_series[0]
    end_t, end_v = equity_series[-1]
    if start_v <= 0 or end_v <= 0:
        return 0.0
    days = max((end_t - start_t).total_seconds() / 86_400.0, 1e-9)
    years = days / 365.0
    if years <= 0:
        return 0.0
    return float(((end_v / start_v) ** (1.0 / years) - 1.0) * 100.0)


def build_report(equity_series, closed_trades, initial_capital: float,
                 primary_tf: str) -> dict:
    values = _equity_values(equity_series)
    final = float(values[-1]) if len(values) else float(initial_capital)
    total_return_pct = (final - initial_capital) / initial_capital * 100.0

    pnls = [t.pnl for t in closed_trades if getattr(t, "pnl", None) is not None]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_w = sum(wins) if wins else 0.0
    gross_l = abs(sum(losses)) if losses else 0.0
    profit_factor = (gross_w / gross_l) if gross_l > 0 else (gross_w if gross_w > 0 else 0.0)
    avg_win = (sum(wins) / len(wins)) if wins else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    win_rate = (len(wins) / len(pnls)) if pnls else 0.0
    expectancy = win_rate * avg_win - (1 - win_rate) * avg_loss

    dd_pct, dd_dur = max_drawdown(equity_series)

    return {
        "initial_capital": float(initial_capital),
        "final_equity": final,
        "total_return_pct": round(total_return_pct, 4),
        "cagr_pct": round(cagr_pct(equity_series), 4),
        "sharpe_annualized": round(annualized_sharpe(equity_series, primary_tf), 4),
        "sortino_annualized": round(annualized_sortino(equity_series, primary_tf), 4),
        "max_drawdown_pct": round(dd_pct, 4),
        "max_drawdown_duration_bars": dd_dur,
        "profit_factor": round(profit_factor, 4),
        "win_rate_pct": round(win_rate * 100.0, 2),
        "avg_win_usd": round(avg_win, 4),
        "avg_loss_usd": round(avg_loss, 4),
        "expectancy_usd": round(expectancy, 4),
        "total_trades": len(pnls),
        "wins": len(wins),
        "losses": len(losses),
    }
```

- [ ] **Step 4: Run — verify PASS**

Run: `pytest tests/backtesting/test_performance.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backtesting/performance.py tests/backtesting/test_performance.py
git commit -m "feat(backtesting): performance metrics (Sharpe, Sortino, CAGR, drawdown, PF)"
```

---

## Task 14: `reporter.py` — JSON, CSV, PNG outputs

**Files:**
- Create: `backtesting/reporter.py`
- Create: `tests/backtesting/test_reporter.py`

- [ ] **Step 1: Write failing tests**

```python
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backtesting.reporter import write_report


def _equity():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [(start + timedelta(minutes=5 * i), 10_000.0 + i * 10.0) for i in range(20)]


def test_writes_all_artifacts(tmp_path: Path):
    write_report(
        run_dir=tmp_path,
        report={"initial_capital": 10_000, "final_equity": 10_190,
                 "total_return_pct": 1.9, "max_drawdown_pct": 0.0,
                 "sharpe_annualized": 1.5, "cagr_pct": 100.0,
                 "total_trades": 0, "wins": 0, "losses": 0,
                 "profit_factor": 0.0, "win_rate_pct": 0.0,
                 "expectancy_usd": 0.0, "avg_win_usd": 0.0,
                 "avg_loss_usd": 0.0, "sortino_annualized": 0.0,
                 "max_drawdown_duration_bars": 0},
        equity_series=_equity(),
        closed_trades=[],
    )
    assert (tmp_path / "report.json").exists()
    assert (tmp_path / "trades.csv").exists()
    assert (tmp_path / "equity_curve.png").exists()


def test_report_json_round_trip(tmp_path: Path):
    rpt = {"final_equity": 11_000.0, "total_return_pct": 10.0}
    write_report(run_dir=tmp_path, report=rpt, equity_series=_equity(),
                  closed_trades=[])
    loaded = json.loads((tmp_path / "report.json").read_text())
    assert loaded["final_equity"] == 11_000.0


def test_trades_csv_has_header_only_when_empty(tmp_path: Path):
    write_report(run_dir=tmp_path, report={}, equity_series=_equity(),
                  closed_trades=[])
    content = (tmp_path / "trades.csv").read_text().strip().splitlines()
    assert len(content) == 1  # header only
    assert "symbol" in content[0]
```

- [ ] **Step 2: Run — verify FAIL**

Run: `pytest tests/backtesting/test_reporter.py -v`
Expected: ImportError

- [ ] **Step 3: Implement reporter**

`backtesting/reporter.py`:

```python
"""Output writer: report.json + trades.csv + equity_curve.png."""
from __future__ import annotations

import csv
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless; no GUI required
import matplotlib.pyplot as plt
import numpy as np


_TRADE_COLS = ["id", "symbol", "direction", "entry_price", "stop_loss",
                "take_profit", "quantity", "entry_time", "exit_price",
                "exit_time", "pnl", "pnl_pct", "close_reason", "order_id"]


def write_report(run_dir: Path, report: dict, equity_series: list,
                  closed_trades: list) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(run_dir / "report.json", report)
    _write_trades_csv(run_dir / "trades.csv", closed_trades)
    _write_equity_png(run_dir / "equity_curve.png", equity_series)


def _write_json(path: Path, report: dict) -> None:
    path.write_text(json.dumps(report, indent=2, default=str))


def _write_trades_csv(path: Path, closed_trades: list) -> None:
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_TRADE_COLS)
        w.writeheader()
        for t in closed_trades:
            row = asdict(t) if is_dataclass(t) else dict(t)
            w.writerow({k: row.get(k) for k in _TRADE_COLS})


def _write_equity_png(path: Path, equity_series: list) -> None:
    if not equity_series:
        # Write empty placeholder so callers always have a file
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, "no data", ha="center", va="center")
        fig.savefig(path)
        plt.close(fig)
        return
    times = [t for t, _ in equity_series]
    eq = np.array([v for _, v in equity_series], dtype=float)
    peaks = np.maximum.accumulate(eq)
    dd = (peaks - eq) / np.where(peaks == 0, 1, peaks) * 100.0

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True,
                                     gridspec_kw={"height_ratios": [3, 1]})
    ax1.plot(times, eq, linewidth=1.2)
    ax1.set_title("Equity curve")
    ax1.set_ylabel("Equity (USD)")
    ax1.grid(True, alpha=0.3)

    ax2.fill_between(times, 0, dd, color="red", alpha=0.4)
    ax2.invert_yaxis()
    ax2.set_ylabel("Drawdown (%)")
    ax2.set_xlabel("Time")
    ax2.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
```

- [ ] **Step 4: Run — verify PASS**

Run: `pytest tests/backtesting/test_reporter.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backtesting/reporter.py tests/backtesting/test_reporter.py
git commit -m "feat(backtesting): reporter writes report.json + trades.csv + equity_curve.png"
```

---

## Task 15: CLI + YAML config

**Files:**
- Create: `backtesting/cli.py`
- Create: `configs/backtest.yaml`
- Create: `tests/backtesting/test_cli.py`

- [ ] **Step 1: Write failing tests**

```python
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backtesting.cli import load_config


def test_load_config_basic(tmp_path: Path):
    cfg_path = tmp_path / "bt.yaml"
    cfg_path.write_text(
        "symbols: [BTCUSDT, ETHUSDT]\n"
        "primary_tf: 5m\n"
        "confirm_tf: 1h\n"
        "start: 2025-10-01\n"
        "end: 2026-04-01\n"
        "initial_capital: 5000\n"
        "taker_fee_bps: 4.0\n"
        "slippage_bps: 2.0\n"
        "fill_model: pessimistic\n"
        "mode: portfolio\n"
        "seed: 7\n"
    )
    cfg = load_config(cfg_path)
    assert cfg.symbols == ["BTCUSDT", "ETHUSDT"]
    assert cfg.primary_tf == "5m"
    assert cfg.start == datetime(2025, 10, 1, tzinfo=timezone.utc)
    assert cfg.end == datetime(2026, 4, 1, tzinfo=timezone.utc)
    assert cfg.initial_capital == 5_000.0
    assert cfg.seed == 7


def test_load_config_minimal_uses_defaults(tmp_path: Path):
    cfg_path = tmp_path / "bt.yaml"
    cfg_path.write_text(
        "symbols: [BTCUSDT]\n"
        "primary_tf: 5m\n"
        "confirm_tf: 1h\n"
        "start: 2025-10-01\n"
        "end: 2026-04-01\n"
    )
    cfg = load_config(cfg_path)
    assert cfg.initial_capital == 10_000.0
    assert cfg.fill_model == "pessimistic"
    assert cfg.mode == "portfolio"
```

- [ ] **Step 2: Run — verify FAIL**

Run: `pytest tests/backtesting/test_cli.py -v`
Expected: ImportError

- [ ] **Step 3: Implement CLI + config loader**

`backtesting/cli.py`:

```python
"""Backtesting CLI: parses YAML config, downloads data, runs backtest, writes report."""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from backtesting.backtester import run_per_symbol, run_portfolio
from backtesting.data_feed import DataFeed
from backtesting.data_loader import download_klines, load_csv
from backtesting.performance import build_report
from backtesting.reporter import write_report
from backtesting.types import BacktestConfig, tf_to_timedelta

logger = logging.getLogger(__name__)


def _coerce_dt(v: Any) -> datetime:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str):
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    raise ValueError(f"Cannot parse datetime: {v!r}")


def load_config(path: Path) -> BacktestConfig:
    raw = yaml.safe_load(Path(path).read_text())
    raw["start"] = _coerce_dt(raw["start"])
    raw["end"] = _coerce_dt(raw["end"])
    return BacktestConfig(**raw)


def _git_sha7() -> str:
    try:
        out = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                       stderr=subprocess.DEVNULL).decode().strip()
        return out or "nogit"
    except Exception:
        return "nogit"


def _build_feed(cfg: BacktestConfig, cache_dir: Path,
                 use_cache: bool) -> DataFeed:
    """Download both timeframes for all symbols and assemble a DataFeed.

    Pulls extra warmup bars (300) before cfg.start so SignalEngine has the
    history it needs at the first iteration.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from binance.um_futures import UMFutures  # noqa: E402
    import os
    client = UMFutures(
        key=os.getenv("BINANCE_API_KEY") or "",
        secret=os.getenv("BINANCE_SECRET_KEY") or "",
    )

    bars = {}
    warmup = 300
    for sym in cfg.symbols:
        for tf in {cfg.primary_tf, cfg.confirm_tf}:
            warmup_start = cfg.start - tf_to_timedelta(tf) * warmup
            df = download_klines(client, sym, tf, warmup_start, cfg.end,
                                  cache_dir=cache_dir if use_cache else cache_dir.parent / "_nocache_temp")
            bars[(sym, tf)] = df

    return DataFeed(bars=bars, primary_tf=cfg.primary_tf, symbols=cfg.symbols,
                     start=cfg.start, end=cfg.end)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="backtesting")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--per-symbol", action="store_true",
                        help="Run each symbol with its own equity pool")
    parser.add_argument("--no-cache", action="store_true",
                        help="Force re-download of klines")
    parser.add_argument("--cache-dir", type=Path, default=Path("data/cache"))
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                         format="[%(asctime)s] %(name)s %(levelname)s: %(message)s")

    cfg = load_config(args.config)
    if args.per_symbol:
        cfg = BacktestConfig(**{**cfg.__dict__, "mode": "per_symbol"})

    run_id = f"{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}_{_git_sha7()}"
    run_dir = args.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Freeze config for the run
    (run_dir / "config.yaml").write_text(yaml.safe_dump({
        **cfg.__dict__,
        "start": cfg.start.isoformat(), "end": cfg.end.isoformat(),
    }, sort_keys=False))

    feed = _build_feed(cfg, args.cache_dir, use_cache=not args.no_cache)

    if cfg.mode == "per_symbol":
        result = run_per_symbol(cfg, feed=feed, run_dir=run_dir)
        # Aggregate per-symbol reports
        per_sym = {}
        for sym, sub in result["per_symbol"].items():
            sub_report = build_report(sub["equity_series"], sub["closed_trades"],
                                       initial_capital=cfg.initial_capital,
                                       primary_tf=cfg.primary_tf)
            per_sym[sym] = sub_report
            write_report(run_dir=run_dir / sym, report=sub_report,
                          equity_series=sub["equity_series"],
                          closed_trades=sub["closed_trades"])
        write_report(run_dir=run_dir, report={"per_symbol": per_sym},
                      equity_series=[], closed_trades=[])
    else:
        result = run_portfolio(cfg, feed=feed, run_dir=run_dir)
        report = build_report(result["equity_series"], result["closed_trades"],
                               initial_capital=cfg.initial_capital,
                               primary_tf=cfg.primary_tf)
        write_report(run_dir=run_dir, report=report,
                      equity_series=result["equity_series"],
                      closed_trades=result["closed_trades"])

    print(f"Run complete: {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

`configs/backtest.yaml`:

```yaml
symbols: [BTCUSDT, ETHUSDT, SOLUSDT]
primary_tf: 5m
confirm_tf: 1h
start: 2025-10-18
end: 2026-04-18
initial_capital: 10000
taker_fee_bps: 4.0
slippage_bps: 2.0
fill_model: pessimistic
mode: portfolio
seed: 42
```

- [ ] **Step 4: Run — verify PASS**

Run: `pytest tests/backtesting/test_cli.py -v`
Expected: 2 passed

- [ ] **Step 5: Run full test suite to confirm nothing regressed**

Run: `pytest tests/backtesting/ -v`
Expected: all tests pass (~40 total)

- [ ] **Step 6: Commit**

```bash
git add backtesting/cli.py configs/backtest.yaml tests/backtesting/test_cli.py
git commit -m "feat(backtesting): CLI + YAML config + sample backtest.yaml"
```

---

## Task 16: Validation run on real data

**Files:**
- Create: `runs/.gitkeep` (already exists from Task 0)
- Create: `docs/superpowers/specs/2026-04-18-backtesting-validation-run.md`

- [ ] **Step 1: Verify Binance creds are present**

Run: `python -c "import os; print('OK' if os.getenv('BINANCE_API_KEY') else 'MISSING'); print('OK' if os.getenv('BINANCE_SECRET_KEY') else 'MISSING')"`
Expected: `OK` on both lines.

If `MISSING`: set `BINANCE_API_KEY` and `BINANCE_SECRET_KEY` in `.env` (read-only API keys are sufficient for klines).

- [ ] **Step 2: Run portfolio-mode backtest**

Run: `python -m backtesting.cli --config configs/backtest.yaml`
Expected: console output ending with `Run complete: runs/<timestamp>_<sha>` and the run directory containing `report.json`, `trades.csv`, `equity_curve.png`, `trades.db`, `risk_state.json`, `config.yaml`.

- [ ] **Step 3: Run per-symbol mode**

Run: `python -m backtesting.cli --config configs/backtest.yaml --per-symbol`
Expected: completes, run directory contains one subdirectory per symbol with its own `report.json`, plus a top-level `report.json` with `per_symbol` aggregation.

- [ ] **Step 4: Determinism check**

Run portfolio backtest twice in succession (use `--no-cache` to ensure fresh data first time, then re-run normally):

```bash
python -m backtesting.cli --config configs/backtest.yaml
python -m backtesting.cli --config configs/backtest.yaml
```

Diff the two `report.json` files (excluding any wall-clock timestamp keys):

Run: `python -c "import json,sys; from pathlib import Path; runs=sorted(Path('runs').iterdir())[-2:]; a=json.loads((runs[0]/'report.json').read_text()); b=json.loads((runs[1]/'report.json').read_text()); print('MATCH' if a==b else 'MISMATCH'); print('a:',a.get('final_equity'),'b:',b.get('final_equity'))"`
Expected: `MATCH`

- [ ] **Step 5: Capture results in a validation note**

Create `docs/superpowers/specs/2026-04-18-backtesting-validation-run.md` with:

```markdown
# Backtesting Engine — Validation Run

**Date:** 2026-04-18
**Config:** [configs/backtest.yaml](../../../configs/backtest.yaml)
**Symbols:** BTCUSDT, ETHUSDT, SOLUSDT
**Period:** 2025-10-18 → 2026-04-18 (6 months)
**Capital:** $10,000

## Portfolio mode result

Paste the contents of `runs/<id>/report.json` here.

## Per-symbol mode result

Paste each `runs/<id>/<SYMBOL>/report.json` here.

## Determinism

Two runs with same config produced bit-identical `report.json`: PASS / FAIL

## Equity curve

![Portfolio equity](../../../runs/<id>/equity_curve.png)
```

Replace `<id>` with the actual run identifier.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/specs/2026-04-18-backtesting-validation-run.md
git commit -m "docs: capture initial backtesting validation run results"
```

---

## Self-review checklist (run before declaring complete)

| Spec section | Tasks |
|---|---|
| §3 Integration analysis (SignalEngine reuse) | Task 11 (orchestrator wires fetcher) |
| §3 RiskManager subclass | Task 10 |
| §3 TradeTracker reuse | Task 11 (uses `db_path`) |
| §4 Module layout | Tasks 0–15 |
| §5 Core types | Task 1 |
| §6 data_loader (CSV + downloader) | Tasks 3, 4 |
| §6 data_feed (bar/next_bar/timeline) | Task 5 |
| §6 history with no-lookahead | Task 6 |
| §7 entry fills + slippage + fees | Task 7 |
| §7 intra-bar SL/TP pessimistic | Task 8 |
| §8 PortfolioBook | Task 9 |
| §9 Portfolio orchestrator + invariants | Task 11 |
| §9 Per-symbol mode | Task 12 |
| §10 Performance metrics | Task 13 |
| §11 CLI + config | Task 15 |
| §12 Output artifacts | Task 14 |
| §13 Validation plan | Task 16 |
| §14 Testing strategy | Tasks 5, 6, 7, 8, 9, 10, 11, 13 |
| §15 Dependencies | Task 0 |

---

## Out of scope (do not add)

- Grid search / parameter optimization
- Walk-forward / cross-validation
- Funding-rate replay
- Maker/limit fills
- Streamlit / web dashboard
- Edits to `src/signal_engine.py`, `src/strategy_engine.py`, or any live code path
