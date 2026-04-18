import json
from pathlib import Path

import pandas as pd
import pytest

from backtesting.reporter import save_report


def test_save_report_generates_files(tmp_path: Path):
    trades = pd.DataFrame([
        {"id": 1, "symbol": "BTCUSDT", "pnl": 100, "close_reason": "TP"}
    ])
    metrics = {"total_trades": 1, "total_pnl": 100.0}
    curve = [
        {"timestamp": "2026-01-01T00:00:00Z", "equity": 10000},
        {"timestamp": "2026-01-01T01:00:00Z", "equity": 10100},
    ]

    save_report(trades, metrics, curve, tmp_path)

    # Verify JSON
    assert (tmp_path / "metrics.json").exists()
    with open(tmp_path / "metrics.json") as f:
        m = json.load(f)
        assert m["total_trades"] == 1

    # Verify CSV
    assert (tmp_path / "trades.csv").exists()
    df = pd.read_csv(tmp_path / "trades.csv")
    assert len(df) == 1

    # Verify PNG
    assert (tmp_path / "equity_curve.png").exists()
