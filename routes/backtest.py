"""Backtest route — runs the backtesting engine and returns metrics + equity curve."""
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, HTTPException, Request
from fastapi.routing import APIRouter
from pydantic import BaseModel

from auth import require_auth
from shared import limiter, api_log, get_client

router = APIRouter()


class BacktestRequest(BaseModel):
    symbols:         list[str] = ["BTCUSDT"]
    primary_tf:      str       = "5m"
    confirm_tf:      str       = "1h"
    start_date:      str       = "2024-01-01"
    end_date:        str       = "2024-03-01"
    initial_capital: float     = 10_000.0


@router.post("/api/backtest/run")
@limiter.limit("3/minute")
async def run_backtest(request: Request, body: BacktestRequest, _: str = Depends(require_auth)):
    from backtesting.types import BacktestConfig
    from backtesting.data_loader import download_klines, _tf_to_ms
    from backtesting.data_feed import DataFeed
    from backtesting.backtester import Backtester
    from backtesting.performance import calculate_performance_report

    try:
        start = datetime.fromisoformat(body.start_date).replace(tzinfo=timezone.utc)
        end   = datetime.fromisoformat(body.end_date).replace(tzinfo=timezone.utc)
    except ValueError as e:
        raise HTTPException(400, f"Invalid date format: {e}")

    if end <= start:
        raise HTTPException(400, "end_date must be after start_date")
    if (end - start).days > 180:
        raise HTTPException(400, "Date range cannot exceed 180 days")

    cfg = BacktestConfig(
        symbols=body.symbols, primary_tf=body.primary_tf, confirm_tf=body.confirm_tf,
        start=start, end=end, initial_capital=body.initial_capital, mode="portfolio",
    )

    client    = get_client()
    cache_dir = Path("data/cache")
    bars      = {}
    for sym in cfg.symbols:
        for tf in [cfg.primary_tf, cfg.confirm_tf]:
            pad_ms  = _tf_to_ms(tf) * 200
            padded  = datetime.fromtimestamp(start.timestamp() - pad_ms / 1000, tz=timezone.utc)
            bars[(sym, tf)] = download_klines(client, sym, tf, padded, end, cache_dir)

    feed = DataFeed(
        bars=bars, primary_tf=cfg.primary_tf, symbols=cfg.symbols, start=start, end=end)

    with tempfile.TemporaryDirectory() as tmp:
        bt = Backtester(config=cfg, feed=feed, run_dir=Path(tmp))
        trades_df, _ = bt.run()

    metrics = calculate_performance_report(trades_df, bt.equity_curve, body.initial_capital)
    equity_curve = [
        {
            "t": pt["timestamp"].isoformat()
                 if hasattr(pt["timestamp"], "isoformat") else str(pt["timestamp"]),
            "v": round(pt["equity"], 2),
        }
        for pt in bt.equity_curve
    ]
    return {"metrics": metrics, "equity_curve": equity_curve, "trade_count": len(trades_df)}
