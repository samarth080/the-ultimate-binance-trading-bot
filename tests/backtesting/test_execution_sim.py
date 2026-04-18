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
