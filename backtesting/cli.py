"""CLI entrypoint for the backtesting engine."""
import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path

import yaml

from backtesting.types import BacktestConfig
from backtesting.data_loader import download_klines, _tf_to_ms
from backtesting.data_feed import DataFeed
from backtesting.backtester import Backtester, run_per_symbol
from backtesting.reporter import save_report

import os
from binance.um_futures import UMFutures

logger = logging.getLogger(__name__)


def load_config(path: Path) -> BacktestConfig:
    with open(path) as f:
        raw = yaml.safe_load(f)

    return BacktestConfig(
        symbols=raw["symbols"],
        primary_tf=raw["primary_timeframe"],
        confirm_tf=raw["confirm_timeframe"],
        start=datetime.fromisoformat(raw["start_date"].replace("Z", "+00:00")).replace(tzinfo=timezone.utc),
        end=datetime.fromisoformat(raw["end_date"].replace("Z", "+00:00")).replace(tzinfo=timezone.utc),
        initial_capital=raw.get("initial_capital", 10_000.0),
        taker_fee_bps=raw.get("taker_fee_bps", 4.0),
        slippage_bps=raw.get("slippage_bps", 2.0),
        fill_model=raw.get("fill_model", "pessimistic"),
        mode=raw.get("mode", "portfolio"),
        seed=raw.get("seed", 42)
    )


def main():
    parser = argparse.ArgumentParser(description="Backtesting Engine")
    parser.add_argument("--config", type=Path, required=True, help="Path to backtest.yaml")
    parser.add_argument("--optimize", action="store_true", help="Run hyperparameter optimization grid")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    cfg = load_config(args.config)
    
    # 1. Prepare run directory
    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = Path(f"runs/bt_{run_timestamp}")
    run_dir.mkdir(parents=True, exist_ok=True)
    
    # Optional: Save copy of config
    with open(run_dir / "config.yaml", "w") as f:
        yaml.dump(cfg.__dict__, f)

    # 2. Download Data
    client = UMFutures(
        key=os.getenv("BINANCE_API_KEY", ""),
        secret=os.getenv("BINANCE_SECRET_KEY", ""),
    )
    cache_dir = Path("data/cache")
    bars = {}
    
    logger.info("Downloading historical data...")
    for sym in cfg.symbols:
        for tf in [cfg.primary_tf, cfg.confirm_tf]:
            # pad start to give indicators warmup (200 bars)
            tf_ms = _tf_to_ms(tf)
            pad_ms = tf_ms * 200
            padded_start = datetime.fromtimestamp(cfg.start.timestamp() - (pad_ms/1000), tz=timezone.utc)
            
            df = download_klines(client, sym, tf, padded_start, cfg.end, cache_dir)
            bars[(sym, tf)] = df
            logger.info(f"Loaded {len(df)} rows for {sym}/{tf}")

    feed = DataFeed(bars=bars, primary_tf=cfg.primary_tf, symbols=cfg.symbols, start=cfg.start, end=cfg.end)

    # 3. Run execution
    if getattr(args, "optimize", False):
        from backtesting.optimizer import run_walk_forward
        
        # Load optimize_grid
        with open(args.config) as f:
            raw = yaml.safe_load(f)
        grid_spec = raw.get("optimize_grid", {})
        if not grid_spec:
            logger.error("optimize_grid not found in config! Add it to run optimization.")
            return

        run_walk_forward(cfg, feed, grid_spec, run_dir, workers=4)
        
    elif cfg.mode == "portfolio":
        bt = Backtester(cfg, feed, run_dir)
        trades, metrics = bt.run()
        save_report(trades, metrics, bt.equity_curve, run_dir)
    elif cfg.mode == "per_symbol":
        trades, metrics_map = run_per_symbol(cfg, feed, run_dir)
        
        # Save a global metrics overview
        (run_dir / "summary.yaml").write_text(yaml.dump(metrics_map))
        
        # Save total trades csv
        if not trades.empty:
            trades.to_csv(run_dir / "all_trades.csv", index=False)
            logger.info(f"Saved {len(trades)} trades across all symbols.")

    logger.info(f"Backtest/Optimization complete. Results saved to {run_dir}")


if __name__ == "__main__":
    main()
