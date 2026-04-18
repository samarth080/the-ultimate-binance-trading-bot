from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock
import pandas as pd
import pytest

from backtesting.backtester import Backtester, run_per_symbol
from backtesting.types import BacktestConfig
from backtesting.data_feed import DataFeed


def _dummy_cfg():
    return BacktestConfig(
        symbols=["BTCUSDT", "ETHUSDT"],
        primary_tf="5m",
        confirm_tf="1h",
        start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )


def test_orchestrator_initialization():
    cfg = _dummy_cfg()
    feed = MagicMock()
    bt = Backtester(cfg, feed, Path("/tmp"))
    assert bt.portfolio.cash == 10_000.0


def test_orchestrator_runs_to_completion(synthetic_5m_300, synthetic_1h_300, tmp_run_dir):
    cfg = _dummy_cfg()
    # just 1 symbol for simplicity
    cfg.symbols = ["BTCUSDT"]
    feed = DataFeed(bars={
        ("BTCUSDT", "5m"): synthetic_5m_300,
        ("BTCUSDT", "1h"): synthetic_1h_300,
    }, primary_tf="5m", symbols=["BTCUSDT"], start=synthetic_5m_300["open_time"].iloc[100], end=synthetic_5m_300["open_time"].iloc[200])

    bt = Backtester(cfg, feed, tmp_run_dir)
    
    # Stub signal engine to always emit nothing
    bt.engine.analyse = MagicMock(return_value=None)
    
    trades, perf = bt.run()
    assert isinstance(trades, pd.DataFrame)
    assert "total_pnl" in perf


def test_per_symbol_mode_runs_independently(synthetic_5m_300, synthetic_1h_300, tmp_run_dir):
    cfg = _dummy_cfg()
    feed = DataFeed(bars={
        ("BTCUSDT", "5m"): synthetic_5m_300,
        ("ETHUSDT", "5m"): synthetic_5m_300,  # reuse same data for test
        ("BTCUSDT", "1h"): synthetic_1h_300,
        ("ETHUSDT", "1h"): synthetic_1h_300,
    }, primary_tf="5m", symbols=["BTCUSDT", "ETHUSDT"], start=synthetic_5m_300["open_time"].iloc[100], end=synthetic_5m_300["open_time"].iloc[200])

    trades, metrics_map = run_per_symbol(cfg, feed, tmp_run_dir)
    assert len(metrics_map) == 2
    assert "BTCUSDT" in metrics_map
    assert "ETHUSDT" in metrics_map
