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


def test_history_never_returns_future_bars(synthetic_5m_300):
    """No-lookahead invariant: history(end=t) never returns close_time > t."""
    feed = DataFeed(bars={("BTCUSDT", "5m"): synthetic_5m_300})
    t = synthetic_5m_300["open_time"].iloc[100] + timedelta(minutes=5)  # close of bar 100
    hist = feed.history("BTCUSDT", "5m", end=t, limit=200)
    close_times = hist.index + timedelta(minutes=5) if hist.index.name == "open_time" else hist["open_time"] + timedelta(minutes=5)
    assert (close_times <= t).all()
    assert len(hist) == 101  # bars 0..100 inclusive


def test_history_returns_last_n_bars(synthetic_5m_300):
    feed = DataFeed(bars={("BTCUSDT", "5m"): synthetic_5m_300})
    t = synthetic_5m_300["open_time"].iloc[250] + timedelta(minutes=5)
    hist = feed.history("BTCUSDT", "5m", end=t, limit=50)
    assert len(hist) == 50
    assert hist.index[-1] == synthetic_5m_300["open_time"].iloc[250]
    assert hist.index[0] == synthetic_5m_300["open_time"].iloc[201]


def test_history_mtf_alignment_excludes_open_bar(synthetic_5m_300, synthetic_1h_300):
    """An hourly bar must NOT appear in history() until its close has passed."""
    feed = DataFeed(bars={
        ("BTCUSDT", "5m"): synthetic_5m_300,
        ("BTCUSDT", "1h"): synthetic_1h_300,
    })
    # Pick t = 1h bar 10 open + 30 minutes (mid-hour). The 1h bar at index 10 is still open.
    t = synthetic_1h_300["open_time"].iloc[10] + timedelta(minutes=30)
    hist_1h = feed.history("BTCUSDT", "1h", end=t, limit=200)
    last_open = hist_1h.index[-1]
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
