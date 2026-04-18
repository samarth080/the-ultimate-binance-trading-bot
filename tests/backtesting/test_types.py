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
