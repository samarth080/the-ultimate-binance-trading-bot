"""OHLCV ingestion: CSV import + Binance REST downloader with parquet cache."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

REQUIRED_COLS = ["open_time", "open", "high", "low", "close", "volume"]


def load_csv(path: Path) -> pd.DataFrame:
    """Load OHLCV from CSV. Required columns: open_time, open, high, low, close, volume.

    `open_time` may be ISO-8601 string OR integer epoch ms.
    Returns DataFrame with tz-aware UTC `open_time` and float OHLCV columns.
    """
    df = pd.read_csv(path)
    missing = set(REQUIRED_COLS) - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing required columns: {sorted(missing)}")

    if pd.api.types.is_numeric_dtype(df["open_time"]):
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    else:
        df["open_time"] = pd.to_datetime(df["open_time"], utc=True)

    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)

    df = df[REQUIRED_COLS].sort_values("open_time").reset_index(drop=True)
    return df


import time

_TF_TO_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
    "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000,
    "6h": 21_600_000, "8h": 28_800_000, "12h": 43_200_000, "1d": 86_400_000,
}


def _tf_to_ms(tf: str) -> int:
    if tf not in _TF_TO_MS:
        raise ValueError(f"Unsupported timeframe: {tf}")
    return _TF_TO_MS[tf]


def _cache_path(cache_dir: Path, symbol: str, interval: str) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{symbol}_{interval}.parquet"


def _read_cache(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        return pd.read_parquet(path)
    except Exception as e:
        logger.warning(f"Cache read failed at {path}: {e}; ignoring")
        return None


def _write_cache(path: Path, df: pd.DataFrame) -> None:
    df.to_parquet(path, index=False)


def _klines_to_df(rows: list) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_av", "trades", "tb_base_av", "tb_quote_av", "ignore",
    ])
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    return df[REQUIRED_COLS]


def download_klines(client, symbol: str, interval: str,
                     start: datetime, end: datetime,
                     cache_dir: Path,
                     max_per_call: int = 1500,
                     retry_max: int = 5) -> pd.DataFrame:
    """Download klines from Binance, persist to parquet cache, return rows in [start, end].

    Uses cache when present and covers the requested range; otherwise fetches
    only the missing tail beyond the cache.
    """
    cache_path = _cache_path(cache_dir, symbol, interval)
    cached = _read_cache(cache_path)

    tf_ms = _tf_to_ms(interval)
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)

    cursor = start_ms
    if cached is not None and not cached.empty:
        cached_max_ms = int(cached["open_time"].max().timestamp() * 1000)
        if cached_max_ms + tf_ms >= end_ms:
            return _slice(cached, start, end)
        cursor = cached_max_ms + tf_ms

    new_rows: list = []
    while cursor < end_ms:
        attempts = 0
        while True:
            try:
                if hasattr(client, 'get_klines'):
                    rows = client.get_klines(
                        symbol=symbol, interval=interval,
                        startTime=cursor, endTime=end_ms, limit=max_per_call,
                    )
                else:
                    rows = client.klines(
                        symbol=symbol, interval=interval,
                        startTime=cursor, endTime=end_ms, limit=max_per_call,
                    )
                break
            except Exception as e:
                attempts += 1
                if attempts >= retry_max:
                    raise
                wait = min(2 ** attempts, 30)
                logger.warning(f"klines fetch failed ({e}); retrying in {wait}s")
                time.sleep(wait)
        if not rows:
            break
        new_rows.extend(rows)
        last_open_ms = int(rows[-1][0])
        cursor = last_open_ms + tf_ms

    new_df = _klines_to_df(new_rows) if new_rows else pd.DataFrame(columns=REQUIRED_COLS)
    if cached is not None:
        full = pd.concat([cached, new_df], ignore_index=True)
        full = full.drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)
    else:
        full = new_df

    _write_cache(cache_path, full)
    return _slice(full, start, end)


def _slice(df: pd.DataFrame, start: datetime, end: datetime) -> pd.DataFrame:
    return df[(df["open_time"] >= start) & (df["open_time"] <= end)].reset_index(drop=True)
