from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from backtesting.cli import load_config


def test_load_config_parses_yaml_and_dates(tmp_path: Path):
    cfg_file = tmp_path / "bt.yaml"
    cfg_file.write_text(yaml.dump({
        "symbols": ["BTCUSDT", "ETHUSDT"],
        "primary_timeframe": "1h",
        "confirm_timeframe": "4h",
        "start_date": "2026-01-01",
        "end_date": "2026-01-31",
        "initial_capital": 50000.0,
        "taker_fee_bps": 5.0,
        "slippage_bps": 2.5,
        "fill_model": "optimistic",
        "mode": "per_symbol",
        "seed": 99
    }))

    config = load_config(cfg_file)
    assert config.symbols == ["BTCUSDT", "ETHUSDT"]
    assert config.primary_tf == "1h"
    assert config.confirm_tf == "4h"
    assert config.start == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert config.end == datetime(2026, 1, 31, tzinfo=timezone.utc)
    assert config.initial_capital == 50000.0
    assert config.taker_fee_bps == 5.0
    assert config.slippage_bps == 2.5
    assert config.fill_model == "optimistic"
    assert config.mode == "per_symbol"
    assert config.seed == 99


def test_load_config_missing_required_raises(tmp_path: Path):
    cfg_file = tmp_path / "bt.yaml"
    cfg_file.write_text(yaml.dump({
        "start_date": "2026-01-01"
        # missing symbols, end_date, etc.
    }))
    with pytest.raises(KeyError):
        load_config(cfg_file)
