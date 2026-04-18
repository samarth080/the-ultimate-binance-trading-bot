"""Grid-search optimizer with robustness analysis and walk-forward validation."""
from __future__ import annotations

import itertools
import json
import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from backtesting.backtester import Backtester
from backtesting.data_feed import DataFeed
from backtesting.types import BacktestConfig
from src.signal_engine import StrategyParams

logger = logging.getLogger(__name__)


def generate_grid(grid_spec: dict) -> list[StrategyParams]:
    """
    Given a grid_spec dictionary of parameters to lists of values,
    returns all cartesian product permutations as StrategyParams.
    """
    keys = list(grid_spec.keys())
    values = [grid_spec[k] for k in keys]
    
    params_list = []
    for combo in itertools.product(*values):
        kwargs = dict(zip(keys, combo))
        params_list.append(StrategyParams(**kwargs))
        
    return params_list


def _run_single_config(cfg_idx: int, config: BacktestConfig,
                       bars_dict: dict, run_dir: Path) -> dict:
    """Entry point for a single thread/process to run backtest."""
    try:
        # Reconstruct feed because feed has complex states that don't pickle cleanly sometimes
        feed = DataFeed(
            bars=bars_dict,
            primary_tf=config.primary_tf,
            symbols=config.symbols,
            start=config.start,
            end=config.end
        )
        sub_dir = run_dir / f"grid_{cfg_idx}"
        sub_dir.mkdir(parents=True, exist_ok=True)
        
        bt = Backtester(config, feed, sub_dir)
        trades, metrics = bt.run()
        
        return {
            "index": cfg_idx,
            "params": asdict(config.strategy_params),
            "metrics": metrics,
        }
    except Exception as e:
        logger.error(f"Config {cfg_idx} failed: {e}")
        return {
            "index": cfg_idx,
            "params": asdict(config.strategy_params),
            "metrics": {"error": str(e)}
        }


def optimize(config: BacktestConfig, feed: DataFeed,
             grid_spec: dict, run_dir: Path, workers: int = 4) -> list[dict]:
    """Run parallel optimization grid over the given config and feed (uses Train split)."""
    grid = generate_grid(grid_spec)
    logger.info(f"Generated {len(grid)} parameter permutations. Running on {workers} workers.")
    
    # Extract raw data to pass to workers
    bars_dict = feed.bars
    
    futures = []
    results = []
    
    # We must use portfolio or per_symbol mode, usually optimizer just tests portfolio.
    with ProcessPoolExecutor(max_workers=workers) as executor:
        for idx, params in enumerate(grid):
            # Create a shallow injected config
            local_cfg = BacktestConfig(
                symbols=config.symbols,
                primary_tf=config.primary_tf,
                confirm_tf=config.confirm_tf,
                start=config.start,
                end=config.end,
                initial_capital=config.initial_capital,
                taker_fee_bps=config.taker_fee_bps,
                slippage_bps=config.slippage_bps,
                fill_model=config.fill_model,
                mode=config.mode,
                seed=config.seed,
                strategy_params=params
            )
            futures.append(executor.submit(_run_single_config, idx, local_cfg, bars_dict, run_dir))
            
        for future in as_completed(futures):
            res = future.result()
            results.append(res)
            logger.info(f"Finished {len(results)}/{len(grid)}")

    return results


def evaluate_robustness(results: list[dict], grid_spec: dict) -> list[dict]:
    """
    Ranks results by a combination of own performance and the performance of
    its nearest neighbors in the parameter grid (to penalize sharp overfit peaks).
    """
    valid_results = [r for r in results if "error" not in r["metrics"]]
    
    # Extract unique sorted values for each parameter to determine indices
    keys = list(grid_spec.keys())
    val_lists = {k: sorted(list(set(grid_spec[k]))) for k in keys}
    
    # Create lookup map
    lookup = {}
    for r in valid_results:
        idx_tuple = tuple(val_lists[k].index(r["params"][k]) for k in keys)
        lookup[idx_tuple] = r

    scored_results = []
    for r in valid_results:
        center_idx = tuple(val_lists[k].index(r["params"][k]) for k in keys)
        
        neighbors = []
        for d in range(len(keys)):
            for offset in [-1, 1]:
                neighbor_idx = list(center_idx)
                neighbor_idx[d] += offset
                
                # Check boundaries
                if 0 <= neighbor_idx[d] < len(val_lists[keys[d]]):
                    neighbor_tuple = tuple(neighbor_idx)
                    if neighbor_tuple in lookup:
                        neighbors.append(lookup[neighbor_tuple])
                        
        # Basic metric: Sharpe Ratio
        own_sharpe = r["metrics"].get("sharpe_ratio", 0.0)
        own_return = r["metrics"].get("total_return_pct", 0.0)
        
        neighbor_sharpes = [n["metrics"].get("sharpe_ratio", 0.0) for n in neighbors]
        avg_neighbor_sharpe = sum(neighbor_sharpes) / len(neighbor_sharpes) if neighbors else own_sharpe
        
        neighbor_returns = [n["metrics"].get("total_return_pct", 0.0) for n in neighbors]
        avg_neighbor_return = sum(neighbor_returns) / len(neighbor_returns) if neighbors else own_return
        
        # Stability score heavily weights the neighborhood avoiding steep cliffs
        # If neighbors are negative while own is highly positive, score drops drastically.
        robust_sharpe = (own_sharpe * 0.4) + (avg_neighbor_sharpe * 0.6)
        robust_return = (own_return * 0.4) + (avg_neighbor_return * 0.6)
        
        # Penalize if standard deviation of neighbors is huge (cliff)
        r["robustness_score"] = robust_sharpe * robust_return if robust_sharpe > 0 else 0
        r["avg_neighbor_sharpe"] = avg_neighbor_sharpe
        scored_results.append(r)
        
    scored_results.sort(key=lambda x: x["robustness_score"], reverse=True)
    return scored_results


def run_walk_forward(config: BacktestConfig, feed: DataFeed,
                     grid_spec: dict, run_dir: Path, workers: int = 4) -> list[dict]:
    """End-to-End optimization sequence over training + testing split."""
    
    # 1. Split feed into 70/30 train/test
    total_seconds = (config.end - config.start).total_seconds()
    train_end = config.start + pd.Timedelta(seconds=total_seconds * 0.7)
    
    logger.info(f"Walk-Forward Split: Train [{config.start} -> {train_end}] | Test [{train_end} -> {config.end}]")
    
    # Need to isolate bars
    train_bars = {}
    test_bars = {}
    for (sym, tf), df in feed.bars.items():
        train_bars[(sym, tf)] = df[df["open_time"] < train_end].reset_index(drop=True)
        test_bars[(sym, tf)] = df[df["open_time"] >= train_end].reset_index(drop=True)
        
    train_feed = DataFeed(train_bars, config.primary_tf, config.symbols, config.start, train_end)
    test_feed = DataFeed(test_bars, config.primary_tf, config.symbols, train_end, config.end)
    
    # 2. Run optimization over training set
    logger.info("Starting grid search on Training Data...")
    raw_results = optimize(config, train_feed, grid_spec, run_dir / "train", workers)
    
    # 3. Score robustness
    scored_results = evaluate_robustness(raw_results, grid_spec)
    top_5 = scored_results[:5]
    
    # 4. Evaluate Top 5 on Testing Set
    logger.info("Evaluating top 5 robust parameter sets on Testing set...")
    wf_results = []
    
    for i, model in enumerate(top_5):
        logger.info(f"Running pass on Top Config #{i+1}")
        params = StrategyParams(**model["params"])
        test_cfg = BacktestConfig(
            symbols=config.symbols,
            primary_tf=config.primary_tf,
            confirm_tf=config.confirm_tf,
            start=train_end,
            end=config.end,
            initial_capital=config.initial_capital,
            taker_fee_bps=config.taker_fee_bps,
            slippage_bps=config.slippage_bps,
            fill_model=config.fill_model,
            mode=config.mode,
            seed=config.seed,
            strategy_params=params
        )
        
        test_result = _run_single_config(i, test_cfg, test_feed.bars, run_dir / "test")
        
        # Verify if test sharply degraded
        train_sharpe = model["metrics"].get("sharpe_ratio", 0.0)
        test_sharpe = test_result["metrics"].get("sharpe_ratio", 0.0)
        
        overfit_flag = False
        if train_sharpe > 1.0 and test_sharpe < 0.0:
            overfit_flag = True
        elif train_sharpe > 0 and test_sharpe / train_sharpe < 0.2: # 80%+ drop
            overfit_flag = True
            
        wf_results.append({
            "rank": i + 1,
            "params": model["params"],
            "train_robustness_score": model["robustness_score"],
            "train_metrics": model["metrics"],
            "test_metrics": test_result["metrics"],
            "is_overfitted": overfit_flag
        })
        
    out_path = run_dir / "walk_forward_results.json"
    out_path.write_text(json.dumps(wf_results, indent=2))
    logger.info(f"Walk-Forward complete! Results written to {out_path}")
    
    return wf_results

