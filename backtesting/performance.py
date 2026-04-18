"""Calculates decision-grade backtest metrics (Sharpe, CAGR, Sortino, etc.)."""
import math
from typing import Mapping

import pandas as pd
import numpy as np


def calculate_performance_report(trades: pd.DataFrame, equity_curve: list[dict],
                                  initial_capital: float, risk_free_rate: float = 0.0) -> dict:
    if trades.empty or not equity_curve:
        return _empty_report(initial_capital)

    eq_df = pd.DataFrame(equity_curve)
    eq_df = eq_df.set_index("timestamp").sort_index()

    # Calculate returns
    eq_df["return"] = eq_df["equity"].pct_change().fillna(0)

    # Time stats
    start_time = eq_df.index[0]
    end_time = eq_df.index[-1]
    duration_days = max((end_time - start_time).total_seconds() / 86400, 1)
    years = duration_days / 365.25

    # Final equity
    final_equity = eq_df["equity"].iloc[-1]
    total_return = (final_equity / initial_capital) - 1

    # CAGR
    cagr = ((final_equity / initial_capital) ** (1 / years)) - 1 if final_equity > 0 else -1

    # Drawdown
    eq_df["peak"] = eq_df["equity"].cummax()
    eq_df["drawdown"] = (eq_df["peak"] - eq_df["equity"]) / eq_df["peak"]
    max_drawdown = eq_df["drawdown"].max()

    # Daily risk metrics (converting per-bar to daily approximation is complex, 
    # but we can standard deviation of returns). Assuming equity points are recorded per bar.
    # We will resample to daily logic for Sharpe/Sortino.
    daily_returns = eq_df["equity"].resample("1D").last().dropna().pct_change().dropna()
    
    if len(daily_returns) > 1:
        mean_ret = daily_returns.mean()
        std_ret = daily_returns.std()
        
        # Annualized Sharpe (assume 365 trading days)
        sharpe = (mean_ret - (risk_free_rate/365)) / std_ret * math.sqrt(365) if std_ret != 0 else 0
        
        downside = daily_returns[daily_returns < 0]
        sortino_std = downside.std()
        sortino = (mean_ret - (risk_free_rate/365)) / sortino_std * math.sqrt(365) if pd.notna(sortino_std) and sortino_std != 0 else 0
    else:
        sharpe = 0.0
        sortino = 0.0

    # Trade stats
    wins = trades[trades["pnl"] > 0]
    losses = trades[trades["pnl"] <= 0]
    win_rate = len(wins) / len(trades)

    gross_profit = wins["pnl"].sum()
    gross_loss = abs(losses["pnl"].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    avg_win = wins["pnl"].mean() if not wins.empty else 0.0
    avg_loss = losses["pnl"].mean() if not losses.empty else 0.0

    return {
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "duration_days": round(duration_days, 1),
        "initial_capital": round(initial_capital, 2),
        "final_equity": round(final_equity, 2),
        "total_return_pct": round(total_return * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "max_drawdown_pct": round(max_drawdown * 100, 1),
        "sharpe_ratio": round(sharpe, 2),
        "sortino_ratio": round(sortino, 2),
        "profit_factor": round(profit_factor, 2),
        "total_trades": len(trades),
        "total_pnl": round(gross_profit - gross_loss, 2),
        "win_rate": round(win_rate * 100, 2),
        "avg_trade_pnl": round(trades["pnl"].mean(), 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
    }


def _empty_report(capital: float) -> dict:
    return {
        "start_time": "", "end_time": "", "duration_days": 0.0,
        "initial_capital": capital, "final_equity": capital,
        "total_return_pct": 0.0, "cagr_pct": 0.0, "max_drawdown_pct": 0.0,
        "sharpe_ratio": 0.0, "sortino_ratio": 0.0, "profit_factor": 0.0,
        "total_trades": 0, "win_rate": 0.0, "avg_trade_pnl": 0.0,
        "avg_win": 0.0, "avg_loss": 0.0
    }
