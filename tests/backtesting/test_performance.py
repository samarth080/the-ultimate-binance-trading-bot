import math
from datetime import datetime, timezone

import pandas as pd
import pytest

from backtesting.performance import calculate_performance_report


def test_calculate_performance_no_trades():
    trades = pd.DataFrame(columns=["pnl", "pnl_pct", "exit_time"])
    curve = [{"timestamp": datetime(2026,1,1), "equity": 10000}]
    rep = calculate_performance_report(trades, curve, 10000)
    assert rep["total_trades"] == 0
    assert rep["sharpe_ratio"] == 0.0
    assert rep["max_drawdown_pct"] == 0.0


def test_calculate_performance_with_trades():
    trades = pd.DataFrame([
        {"pnl": 500, "pnl_pct": 5.0, "exit_time": "2026-01-02T00:00:00"},
        {"pnl": -200, "pnl_pct": -2.0, "exit_time": "2026-01-03T00:00:00"},
        {"pnl": 1000, "pnl_pct": 10.0, "exit_time": "2026-01-04T00:00:00"}
    ])
    curve = [
        {"timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc), "equity": 10000},
        {"timestamp": datetime(2026, 1, 2, tzinfo=timezone.utc), "equity": 10500},
        {"timestamp": datetime(2026, 1, 3, tzinfo=timezone.utc), "equity": 10300},
        {"timestamp": datetime(2026, 1, 4, tzinfo=timezone.utc), "equity": 11300},
    ]
    rep = calculate_performance_report(trades, curve, 10000)
    
    assert rep["total_trades"] == 3
    assert rep["win_rate"] == pytest.approx(66.67)
    assert rep["total_pnl"] == 1300.0
    # Peak at 10500, drops to 10300 = DD of 200 => 200/10500 = 1.904%
    assert rep["max_drawdown_pct"] == pytest.approx(1.9)
    # Total return 13% over 3 days. Annualized will be huge, but let's just check it computed safely.
    assert rep["cagr_pct"] > 0
    assert rep["sharpe_ratio"] > 0
