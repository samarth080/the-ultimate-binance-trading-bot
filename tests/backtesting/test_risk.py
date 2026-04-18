import json
from pathlib import Path
from backtesting.risk import BacktestRiskManager


def test_backtest_risk_manager_state_isolation(tmp_path: Path):
    run_dir = tmp_path / "run123"
    
    rm = BacktestRiskManager(run_dir=run_dir, risk_per_trade=0.01)
    # The STATE_FILE must be scoped to the run_dir
    assert rm.STATE_FILE == run_dir / "risk_state.json"
    
    rm.record_trade_open()
    rm.update_equity(10500.0)
    
    # State should be written to isolated path
    assert (run_dir / "risk_state.json").exists()
    
    with open(run_dir / "risk_state.json") as f:
        data = json.load(f)
        assert data["open_positions"] == 1
        assert data["peak_equity"] == 10500.0
