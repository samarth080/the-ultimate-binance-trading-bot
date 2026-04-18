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
