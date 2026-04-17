# Backtesting Engine — Design Spec

**Date:** 2026-04-18
**Status:** Approved (pending written-spec review)
**Owner:** samarth chatli
**Repo:** [the-ultimate-binance-trading-bot](https://github.com/samarth080/the-ultimate-binance-trading-bot)

---

## 1. Problem & goal

The bot has a production-grade signal engine ([src/signal_engine.py](../../../src/signal_engine.py)), risk manager ([src/risk_manager.py](../../../src/risk_manager.py)), and trade tracker ([src/trade_tracker.py](../../../src/trade_tracker.py)), but **no way to validate strategy profitability against historical data** before risking capital. Live performance can only be inferred from real trades, which is slow and expensive.

**Goal:** Build a professional backtesting engine that **reuses existing strategy and risk logic unchanged** and produces decision-grade performance reports for portfolio-mode and per-symbol-mode runs.

**Non-goals (deferred to future specs):**
- Parameter grid search / Bayesian optimization
- Walk-forward / cross-validation
- Funding-rate replay (v1 sets funding to 0)
- Limit/maker order simulation (live strategy is market-only)
- Web dashboard for backtest results

## 2. Constraints

- **Zero changes to `signal_engine.py`** — strategy logic is the source of truth and must not fork.
- **Minimal, additive changes elsewhere** — `RiskManager` and `TradeTracker` are reused via existing extension points (constructor args, class-level state file path).
- **No lookahead bias** — historical fetcher must never return bars whose close time is after the simulated current time.
- **Deterministic** — same config + same data → bit-identical report.

## 3. Integration analysis (existing-code reuse)

### `SignalEngine` — fully decoupled, reuse as-is

[src/signal_engine.py:460](../../../src/signal_engine.py#L460):

```python
SignalEngine(fetch_klines_fn, get_funding_rate_fn=None)
# fetch_klines_fn(symbol, interval, limit) → DataFrame[Open, High, Low, Close, Volume]
# get_funding_rate_fn(symbol) → float
```

The backtester injects a historical fetcher (mirrors live wiring at [src/strategy_engine.py:75-85](../../../src/strategy_engine.py#L75-L85)):

```python
def make_historical_fetcher(data_feed, current_time):
    def fetch_klines(symbol, interval, limit):
        return data_feed.history(symbol, interval, end=current_time, limit=limit)
    return fetch_klines
```

`signal_engine.analyse()` requests `limit=200` per timeframe → backtester needs ≥200 bars of warmup before the trading window starts.

### `RiskManager` — subclass with per-run state file

[src/risk_manager.py:45](../../../src/risk_manager.py#L45) declares `STATE_FILE = Path("logs/risk_state.json")` as a class attribute. Backtest subclass overrides it:

```python
class BacktestRiskManager(RiskManager):
    def __init__(self, run_dir: Path, **kw):
        type(self).STATE_FILE = run_dir / "risk_state.json"
        super().__init__(**kw)
```

All methods used unchanged: `is_trading_allowed()`, `compute_position_size()`, `record_trade_open()`, `record_trade_close()`, `update_equity()`, `trailing_stop()`.

### `TradeTracker` — already accepts custom DB path

[src/trade_tracker.py:49](../../../src/trade_tracker.py#L49) constructor takes `db_path`. Backtest uses `TradeTracker(db_path=run_dir / "trades.db")`. `get_stats()` covers win-rate, profit-factor, max-drawdown. `performance.py` extends with Sharpe, Sortino, CAGR, expectancy.

## 4. Module layout

```
backtesting/
├── __init__.py
├── types.py             # Bar, Fill, BacktestConfig, Position dataclasses
├── data_loader.py       # Binance REST → parquet cache; CSV import
├── data_feed.py         # In-memory time-aligned access to all symbols/TFs
├── execution_sim.py     # Entry/exit fills, fees, slippage, intra-bar SL/TP
├── portfolio.py         # PortfolioBook: positions + shared equity
├── backtester.py        # Orchestrator (portfolio mode + per-symbol wrapper)
├── performance.py       # Sharpe, Sortino, CAGR, drawdown, equity curve series
├── reporter.py          # report.json, trades.csv, equity_curve.png
└── cli.py               # `python -m backtesting.cli --config configs/backtest.yaml`

configs/
└── backtest.yaml        # symbols, period, fees, slippage, mode, capital

tests/backtesting/
├── conftest.py          # synthetic OHLCV fixtures
├── test_data_loader.py
├── test_data_feed.py    # no-lookahead invariant
├── test_execution_sim.py
├── test_portfolio.py
├── test_backtester.py   # end-to-end on fixture
└── test_performance.py
```

All net-new under `backtesting/`. No edits to existing `src/`.

## 5. Core data types (`backtesting/types.py`)

```python
@dataclass(frozen=True)
class Bar:
    symbol: str
    timeframe: str
    open_time: datetime         # bar OPEN time, UTC, tz-aware
    open: float; high: float; low: float; close: float; volume: float
    @property
    def close_time(self) -> datetime: ...   # open_time + tf_duration

@dataclass
class Position:
    symbol: str
    direction: Literal["LONG","SHORT"]
    qty: float
    entry_price: float          # post-slippage post-fee fill price
    stop_loss: float
    take_profit: float
    entry_time: datetime
    entry_fee: float
    entry_atr: float            # ATR at entry — needed for trailing stop without re-running engine
    trade_id: int               # TradeTracker row id

@dataclass
class Fill:
    symbol: str
    side: Literal["BUY","SELL"]
    qty: float
    price: float                # final fill price after slippage
    fee: float                  # absolute fee in quote ccy
    timestamp: datetime
    reason: Literal["ENTRY","TP","SL","TRAIL","EOD"]

@dataclass
class BacktestConfig:
    symbols: list[str]
    primary_tf: str             # "5m"
    confirm_tf: str             # "1h"
    start: datetime; end: datetime
    initial_capital: float = 10_000.0
    taker_fee_bps: float = 4.0
    slippage_bps: float = 2.0
    fill_model: Literal["pessimistic","optimistic"] = "pessimistic"
    mode: Literal["portfolio","per_symbol"] = "portfolio"
    confidence_threshold: float | None = None
    seed: int = 42
```

## 6. Data layer (`data_loader.py`, `data_feed.py`)

### `data_loader.py`

- `download_klines(symbol, interval, start, end, cache_dir)` — uses `binance.um_futures.UMFutures.klines(limit=1500)` in a loop, writes one parquet per `(symbol, interval)` to `data/cache/`.
- `load_csv(path)` — loads user-supplied OHLCV CSV with required columns `open_time, open, high, low, close, volume` (UTC ms epoch or ISO).
- Cache keyed by `(symbol, interval)`; on rerun, only fetches the gap between cached `max(open_time)` and requested `end`.
- Resilient to Binance rate limits: retry with backoff; honor `Retry-After`.

### `data_feed.py`

```python
class DataFeed:
    def __init__(self, bars: dict[tuple[str,str], pd.DataFrame]): ...
    @classmethod
    def load(cls, cfg: BacktestConfig, *, warmup_bars: int = 250) -> "DataFeed": ...

    def primary_close_times(self) -> list[datetime]:
        """Sorted union of primary-TF bar close times in [cfg.start, cfg.end]."""

    def bar(self, symbol: str, tf: str, t: datetime) -> Bar | None:
        """Return the bar whose close_time == t, or None."""

    def next_bar(self, symbol: str, tf: str, t: datetime) -> Bar | None:
        """First bar whose open_time > t. Used by ExecutionSimulator.entry_fill.
        Returns None if no future bar exists (end-of-data)."""

    def history(self, symbol: str, tf: str, end: datetime, limit: int) -> pd.DataFrame:
        """Last `limit` bars whose close_time <= end. Used by SignalEngine fetcher.
        Enforces no-lookahead: never returns a bar with close_time > end."""
```

**No-lookahead invariant** is the single most important property of this layer; covered by `test_data_feed.py`.

## 7. Execution simulator (`execution_sim.py`)

```python
class ExecutionSimulator:
    def __init__(self, taker_fee_bps: float, slippage_bps: float,
                 fill_model: str): ...

    def entry_fill(self, signal: Signal, qty: float, next_bar: Bar) -> Fill:
        """Fill at next_bar.open + slippage in trade direction."""

    def check_exit(self, pos: Position, bar: Bar) -> Fill | None:
        """Return Fill if SL or TP hit inside [bar.low, bar.high]; else None."""
```

**Fill rules:**
- **Entry**: at the **next primary-TF bar's open** (avoids "filled at signal close" optimism). Slippage moves price against trader: `fill = open * (1 + sign * bps/10000)` where `sign=+1` for BUY, `-1` for SELL.
- **Exit (SL or TP)**:
  - `LONG`: SL hit if `bar.low <= pos.stop_loss`; TP hit if `bar.high >= pos.take_profit`.
  - `SHORT`: SL hit if `bar.high >= pos.stop_loss`; TP hit if `bar.low <= pos.take_profit`.
  - **Both hit in same bar** + `fill_model=="pessimistic"` → assume **SL fills first** (industry-standard conservative choice).
  - Fill price = the level itself (SL or TP), shifted by slippage in the exit-side direction.
- **Trailing stop**: each bar close, recompute via `risk.trailing_stop(...)`. Updated SL applies to the **next** bar's exit check.
- **Fees**: `qty * fill_price * taker_fee_bps / 10_000`. Charged on both entry and exit, added to `pnl` cost basis.

## 8. Portfolio book (`portfolio.py`)

```python
class PortfolioBook:
    def __init__(self, initial_capital: float): ...
    def free_cash(self) -> float: ...
    def equity(self, feed: DataFeed, t: datetime) -> float:
        """cash + sum(position_market_value at last close <= t)"""
    def has_position(self, symbol: str) -> bool: ...
    def open_positions(self) -> list[Position]: ...
    def open(self, sig: Signal, size: PositionSize, fill: Fill) -> Position: ...
    def close(self, pos: Position, fill: Fill) -> tuple[float, float]:
        """Returns (realized_pnl, new_equity). Updates cash."""
```

**Rules:**
- One position per symbol max (matches live behavior in [strategy_engine.py:217](../../../src/strategy_engine.py#L217)).
- Cash updated on every fill (entry: cash -= notional + fee; exit: cash += proceeds - fee).
- `equity()` marks open positions to the last available primary-TF close at or before `t` (no peeking at future bars).

## 9. Orchestrator (`backtester.py`)

### Portfolio mode (default)

```
load DataFeed (all symbols × {primary_tf, confirm_tf}, with warmup)
risk = BacktestRiskManager(run_dir)
book = PortfolioBook(cfg.initial_capital)
tracker = TradeTracker(db_path=run_dir / "trades.db")
sim = ExecutionSimulator(...)
equity_series = []  # (t, equity) tuples for performance.py

for t in feed.primary_close_times():
    # PHASE 1: Process exits (frees capital + slots before new entries)
    for pos in list(book.open_positions()):
        bar = feed.bar(pos.symbol, cfg.primary_tf, t)
        if bar is None: continue
        fill = sim.check_exit(pos, bar)
        if fill:
            realized_pnl, equity = book.close(pos, fill)
            tracker.close_trade(pos.trade_id, fill.price, fill.reason)
            risk.record_trade_close(realized_pnl, equity)
        else:
            # Update trailing stop for next bar
            new_sl = risk.trailing_stop(pos.entry_price, bar.close, pos.stop_loss,
                                        sig_atr_for(pos), pos.direction)
            pos.stop_loss = new_sl

    # PHASE 2: Mark-to-market and equity update
    equity = book.equity(feed, t)
    risk.update_equity(equity)
    equity_series.append((t, equity))

    if not risk.is_trading_allowed():
        continue

    # PHASE 3: Generate entries — DETERMINISTIC ORDER = cfg.symbols
    engine = SignalEngine(make_historical_fetcher(feed, t), lambda s: 0.0)
    for sym in cfg.symbols:
        if book.has_position(sym): continue
        sig = engine.analyse(sym, cfg.primary_tf, cfg.confirm_tf)
        if sig is None: continue

        size = risk.compute_position_size(equity, sig.price, sig.stop_loss, sig.take_profit)
        if size is None: continue

        next_bar = feed.next_bar(sym, cfg.primary_tf, t)
        if next_bar is None: continue   # no future data — skip
        fill = sim.entry_fill(sig, size.quantity, next_bar)
        notional = fill.qty * fill.price + fill.fee
        if notional > book.free_cash(): continue   # insufficient capital

        trade_id = tracker.open_trade(...)
        pos = book.open(sig, size, fill)
        pos.trade_id = trade_id
        risk.record_trade_open()
        if not risk.is_trading_allowed(): break    # max-positions hit
```

### Per-symbol mode (`--per-symbol` flag)

Thin wrapper: for each `sym in cfg.symbols`, call portfolio runner with `cfg.symbols=[sym]` and a fresh `BacktestRiskManager` + `PortfolioBook(cfg.initial_capital)`. Aggregate per-symbol reports side-by-side. No code duplication — same loop, restricted symbol list.

### Correctness invariants

| Property | Mechanism |
|---|---|
| No lookahead | `feed.history(end=t)` filters strictly `close_time <= t` |
| Deterministic ordering | symbols processed in `cfg.symbols` order; same-`t` exits before entries |
| No double-allocation | `book.free_cash()` checked per entry; `risk.is_trading_allowed()` re-checked |
| One position per symbol | `book.has_position(sym)` short-circuits |
| Risk halts respected | `is_trading_allowed()` checked before symbol loop AND inside loop |
| Trailing stop applies next bar | mutated on bar `t`, used by `check_exit` on bar `t+1` |
| MTF alignment | `confirm_tf` bar must satisfy `close_time <= t`; the data_feed enforces this |

## 10. Performance metrics (`performance.py`)

Inputs: `equity_series: list[(datetime, float)]`, `closed_trades: list[TradeRecord]`, `cfg`.

```python
def compute_report(equity_series, closed_trades, cfg) -> dict:
    return {
        "total_return_pct": ...,
        "cagr_pct": ...,                    # ((final/initial)^(365/days)) - 1
        "sharpe_annualized": ...,           # mean(r)/std(r) * sqrt(periods_per_year)
        "sortino_annualized": ...,          # downside std only
        "max_drawdown_pct": ...,            # peak-to-trough on equity curve
        "max_drawdown_duration_bars": ...,
        "profit_factor": ...,               # gross_wins / |gross_losses|
        "win_rate_pct": ...,
        "expectancy_usd": ...,              # win_rate*avg_win - (1-win_rate)*avg_loss
        "avg_win_usd": ..., "avg_loss_usd": ...,
        "total_trades": ..., "wins": ..., "losses": ...,
        "time_in_market_pct": ...,          # bars with ≥1 open position / total bars
        "per_symbol": { sym: {... same keys ...} },
    }
```

Returns are computed from per-bar log returns of the equity series; `periods_per_year` derived from `cfg.primary_tf` (e.g. 5m = 105_120 bars/yr).

## 11. CLI & config (`cli.py`, `configs/backtest.yaml`)

```yaml
# configs/backtest.yaml
symbols: [BTCUSDT, ETHUSDT, SOLUSDT]
primary_tf: 5m
confirm_tf: 1h
start: 2025-10-18
end: 2026-04-18
initial_capital: 10000
taker_fee_bps: 4.0
slippage_bps: 2.0
fill_model: pessimistic
mode: portfolio
seed: 42
```

```bash
python -m backtesting.cli --config configs/backtest.yaml                # portfolio mode
python -m backtesting.cli --config configs/backtest.yaml --per-symbol   # per-symbol mode
python -m backtesting.cli --config configs/backtest.yaml --no-cache     # force re-download
```

## 12. Output artifacts

```
runs/<UTC_timestamp>_<git_sha7>/
├── config.yaml          # frozen config used for the run
├── report.json          # all metrics, portfolio + per_symbol
├── trades.csv           # one row per closed trade
├── equity_curve.png     # matplotlib: equity (top) + drawdown (bottom)
├── trades.db            # raw SQLite (TradeTracker)
└── risk_state.json      # final risk manager state
```

`report.json` is canonical; `trades.csv` and `equity_curve.png` are derivable views.

## 13. Validation plan

After implementation:

1. Download BTCUSDT, ETHUSDT, SOLUSDT — primary 5m, confirm 1h — last 6 months.
2. Run portfolio backtest with $10k initial capital and default fees/slippage.
3. Run same period in `--per-symbol` mode.
4. Capture both `report.json`s and equity curves.

**Acceptance criteria:**
- End-to-end run completes without error on both modes.
- Same `--seed` + same data + same config → bit-identical `report.json` (excluding wall-clock timestamps).
- Equity series is monotonically time-indexed.
- `total_return_pct` matches `(final_equity - initial_capital) / initial_capital` to 4 decimal places.
- Per-symbol pnl sum (per-symbol mode) ≈ portfolio total (within fee differences from concurrent capital allocation).

**Whether the strategy is profitable is a finding, not a pass criterion.**

## 14. Testing strategy

| Test | Covers |
|---|---|
| `test_data_feed::test_no_lookahead` | `history(end=t)` never returns close_time > t |
| `test_data_feed::test_mtf_alignment` | confirm_tf bars excluded if still open at t |
| `test_execution_sim::test_pessimistic_both_hit` | SL+TP same bar → SL wins |
| `test_execution_sim::test_slippage_direction` | slippage hurts trader on entry and exit |
| `test_execution_sim::test_fee_calc` | fee = qty * price * bps/10000 |
| `test_portfolio::test_no_double_allocation` | concurrent entries respect free_cash |
| `test_portfolio::test_one_position_per_symbol` | rejects entry if open position exists |
| `test_backtester::test_deterministic` | same seed → identical report.json |
| `test_backtester::test_max_positions_cap` | risk.max_positions never exceeded |
| `test_backtester::test_drawdown_halt` | trading stops when drawdown > halt |
| `test_performance::test_sharpe_known_series` | numerical correctness vs hand-computed |

## 15. Dependencies to add

```
# requirements.txt additions
pyarrow>=14.0          # parquet cache
matplotlib>=3.7        # equity curve
PyYAML>=6.0            # config parsing
pytest>=7.4            # tests (dev dep)
```

## 16. Risks & mitigations

| Risk | Mitigation |
|---|---|
| `signal_engine` semantics differ subtly between live (REST polling) and backtest (sliced data) | The fetcher returns the **last `limit` bars ≤ t** — identical shape to live REST response. Indicator math is pure pandas, no time dependency beyond the slice. |
| Binance API rate limits during data download | Backoff + cache; downloads are one-time per `(symbol, interval, range)` |
| `RiskManager.STATE_FILE` mutation could leak into live state if backtest crashes mid-run | `BacktestRiskManager` sets the class attr in `__init__`; live code paths instantiate `RiskManager` (parent), which resets the class attr on next live import. **Mitigation:** restore parent path in `__del__` or context-manager pattern. |
| Per-bar `SignalEngine(...)` re-instantiation overhead | Negligible — constructor only stores 2 closures. The expensive part is indicator math, which runs once per bar regardless. |
| Floating-point determinism across pandas versions | Pin pandas in `requirements.txt` for reproducible runs |

## 17. Out of scope (will fail review if added)

- Editing `signal_engine.py` for backtest reasons
- Forking the strategy logic into a "backtest version"
- Web UI for backtest results
- Live-trading code changes
- Grid search / param optimization
- Walk-forward validation
- Funding-rate replay
