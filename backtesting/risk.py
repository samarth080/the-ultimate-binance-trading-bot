"""Risk manager patched for backtesting isolation."""
import logging
from pathlib import Path

import sys as _sys
from pathlib import Path as _Path
_PROJECT_ROOT = str(_Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in _sys.path:
    _sys.path.insert(0, _PROJECT_ROOT)
from src.risk_manager import RiskManager


class BacktestRiskManager(RiskManager):
    """Overrides RiskManager state file paths to isolate backtest runs."""

    def __init__(self, run_dir: Path, **kwargs):
        self.STATE_FILE = run_dir / "risk_state.json"
        super().__init__(**kwargs)

    def _save_state(self):
        # Override to suppress unnecessary errors during tests if path isn't created
        self.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        super()._save_state()
