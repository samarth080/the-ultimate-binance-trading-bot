"""Report generator: JSON metrics, CSV trades list, PNG equity curve."""
import json
import logging
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

logger = logging.getLogger(__name__)


def save_report(trades: pd.DataFrame, metrics: dict,
                equity_curve: list[dict], out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. JSON
    metrics_path = out_dir / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2))
    logger.info(f"Saved metrics to {metrics_path}")

    # 2. CSV
    trades_path = out_dir / "trades.csv"
    if not trades.empty:
        trades.to_csv(trades_path, index=False)
        logger.info(f"Saved {len(trades)} trades to {trades_path}")
    else:
        trades_path.write_text("No trades executed.\n")

    # 3. Plot
    if equity_curve:
        plot_path = out_dir / "equity_curve.png"
        df = pd.DataFrame(equity_curve)
        
        plt.figure(figsize=(10, 5))
        plt.plot(pd.to_datetime(df["timestamp"]), df["equity"], label="Equity", color="blue")
        plt.title("Backtest Equity Curve")
        plt.xlabel("Time")
        plt.ylabel("USD")
        plt.grid(True, linestyle="--", alpha=0.6)
        plt.legend()
        plt.tight_layout()
        plt.savefig(plot_path)
        plt.close()
        logger.info(f"Saved equity curve to {plot_path}")
