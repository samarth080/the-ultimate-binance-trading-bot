from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from backtesting.data_loader import load_csv


def test_load_csv_iso_timestamps(tmp_path: Path):
    csv = tmp_path / "btc.csv"
    csv.write_text(
        "open_time,open,high,low,close,volume\n"
        "2026-01-01T00:00:00Z,50000,50100,49900,50050,1.0\n"
        "2026-01-01T00:05:00Z,50050,50200,50000,50150,2.0\n"
    )
    df = load_csv(csv)
    assert list(df.columns) == ["open_time", "open", "high", "low", "close", "volume"]
    assert len(df) == 2
    assert df["open_time"].iloc[0] == datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    assert df["close"].dtype == float


def test_load_csv_epoch_ms(tmp_path: Path):
    csv = tmp_path / "btc.csv"
    csv.write_text(
        "open_time,open,high,low,close,volume\n"
        "1767225600000,50000,50100,49900,50050,1.0\n"
    )
    df = load_csv(csv)
    assert df["open_time"].iloc[0].tzinfo is not None


def test_load_csv_missing_columns_raises(tmp_path: Path):
    csv = tmp_path / "bad.csv"
    csv.write_text("open_time,close\n2026-01-01T00:00:00Z,50000\n")
    with pytest.raises(ValueError, match="missing"):
        load_csv(csv)


from unittest.mock import MagicMock
from backtesting.data_loader import download_klines, _tf_to_ms


def _fake_kline_row(open_ms: int, close_price: float):
    # Binance klines() returns lists of 12 items; only first 6 are used here
    return [open_ms, "100", "110", "95", str(close_price), "1.0",
            open_ms + 299_999, "0", 0, "0", "0", "0"]


def test_download_klines_writes_parquet_cache(tmp_path: Path):
    client = MagicMock()
    start_ms = 1767225600000
    rows = [_fake_kline_row(start_ms + i * 300_000, 100.0 + i) for i in range(50)]
    client.klines.return_value = rows

    df = download_klines(
        client=client, symbol="BTCUSDT", interval="5m",
        start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end=datetime(2026, 1, 1, 4, 0, tzinfo=timezone.utc),
        cache_dir=tmp_path,
    )
    assert len(df) == 49
    cache_file = tmp_path / "BTCUSDT_5m.parquet"
    assert cache_file.exists()


def test_download_klines_uses_cache(tmp_path: Path):
    client = MagicMock()
    start_ms = 1767225600000
    rows = [_fake_kline_row(start_ms + i * 300_000, 100.0 + i) for i in range(10)]
    client.klines.return_value = rows

    download_klines(client, "BTCUSDT", "5m",
                    datetime(2026, 1, 1, tzinfo=timezone.utc),
                    datetime(2026, 1, 1, 0, 50, tzinfo=timezone.utc),
                    cache_dir=tmp_path)
    first_call_count = client.klines.call_count

    # Second call same range — should hit cache, no new client calls
    download_klines(client, "BTCUSDT", "5m",
                    datetime(2026, 1, 1, tzinfo=timezone.utc),
                    datetime(2026, 1, 1, 0, 50, tzinfo=timezone.utc),
                    cache_dir=tmp_path)
    assert client.klines.call_count == first_call_count


def test_tf_to_ms():
    assert _tf_to_ms("5m") == 5 * 60 * 1000
    assert _tf_to_ms("1h") == 60 * 60 * 1000
