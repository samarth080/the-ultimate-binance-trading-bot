import argparse
import logging
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from datetime import datetime, timedelta, timezone
from binance.um_futures import UMFutures
from backtesting.data_loader import download_klines
from src.ml.dataset_builder import build_dataset

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s")
logger = logging.getLogger(__name__)

FEATURES = [
    "returns_1", "returns_3", "returns_5", 
    "volatility_10", "volatility_20", 
    "rsi_14", "dist_sma_20", "dist_sma_50", 
    "macd", "macd_signal", "macd_hist"
]

def map_data_and_train(symbol: str, timeframe: str = "5m", limit: int = 20000, forward_bars: int = 5):
    logger.info(f"Downloading historical data for {symbol}/{timeframe} ...")
    
    # Calculate start time based on limit
    end_time = datetime.now(timezone.utc)
    minutes_per_bar = int(timeframe[:-1]) if timeframe.endswith('m') else 60
    start_time = end_time - timedelta(minutes=minutes_per_bar * limit)
    
    # Use public client
    client = UMFutures()
    cache_dir = Path("data/cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    df = download_klines(client, symbol, timeframe, start_time, end_time, cache_dir)

    if df.empty:
        logger.error(f"Failed to fetch data for {symbol}")
        return

    logger.info("Building features and classification target...")
    df_set = build_dataset(df, forward_bars=forward_bars, min_profit_pct=0.001)

    X = df_set[FEATURES]
    y = df_set['target']
    
    # Time-series split (no shuffling to prevent leakage)
    split_idx = int(len(X) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

    logger.info(f"Training RandomForestClassifier on {len(X_train)} samples ...")
    rf = RandomForestClassifier(n_estimators=100, max_depth=6, random_state=42, n_jobs=-1)
    rf.fit(X_train, y_train)

    logger.info("Evaluating on Test Split...")
    preds = rf.predict(X_test)
    report = classification_report(y_test, preds)
    print("\n" + report + "\n")

    # Feature Importance
    importances = sorted(zip(FEATURES, rf.feature_importances_), key=lambda x: x[1], reverse=True)
    logger.info("Top Features:")
    for feat, imp in importances[:3]:
        logger.info(f" - {feat}: {imp:.4f}")

    # Save to disk
    out_dir = Path("data/models")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    model_path = out_dir / "rf_latest.joblib"
    joblib.dump(rf, model_path)
    logger.info(f"Model saved successfully to {model_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", type=str, default="BTCUSDT")
    parser.add_argument("--tf", type=str, default="5m")
    args = parser.parse_args()
    
    map_data_and_train(args.symbol, args.tf)
