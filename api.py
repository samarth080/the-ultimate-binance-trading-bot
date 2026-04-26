"""
Binance Bot API Server
FastAPI wrapper around the existing bot modules.

Requirements:
  pip install fastapi uvicorn[standard] slowapi

Usage (from project root):
  python api.py
  Then open http://localhost:8000
"""
import asyncio
import logging
import os
import secrets
import sys
from collections import deque
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
from typing import Any, Dict, List, Optional

# ── Load .env BEFORE importing bot modules (they call sys.exit if keys missing) ──
from dotenv import find_dotenv, load_dotenv

_dotenv = find_dotenv(usecwd=True)
load_dotenv(_dotenv or (Path(__file__).parent / ".env"))

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, field_validator, model_validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import uvicorn

from backtesting.types import BacktestConfig
from backtesting.data_loader import download_klines, _tf_to_ms
from backtesting.data_feed import DataFeed
from backtesting.backtester import Backtester
from backtesting.performance import calculate_performance_report

# Add src/ to path so bot modules are importable
sys.path.insert(0, str(Path(__file__).parent / "src"))

# ── Rate limiter (keyed by client IP) ─────────────────────────────────────────
# These limits apply ONLY to HTTP UI requests (manual button clicks).
# Automated paths (strategy engine, news auto-trade, TWAP sub-orders) call
# Binance directly and are NOT subject to these limits.
#
# The real ceiling is Binance's own limits (300 orders/10s on futures).
# These limits exist solely to catch runaway browser loops or scripts — not
# to restrict legitimate trading.
#
# Override any limit via .env:  RATE_TRADE=120/minute  RATE_SIGNAL=60/minute
_RATE_TRADE  = os.getenv("RATE_TRADE",  "120/minute")   # manual order endpoints
_RATE_SIGNAL = os.getenv("RATE_SIGNAL", "60/minute")    # ML / signal reads
_RATE_TWAP   = os.getenv("RATE_TWAP",   "20/minute")    # TWAP (spawns sub-orders)
_RATE_READ   = os.getenv("RATE_READ",   "120/minute")   # stats / news / logs

limiter = Limiter(key_func=get_remote_address)

# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(title="Binance Bot API", version="1.0.0", docs_url=None, redoc_url=None)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS — restrict to localhost only ─────────────────────────────────────────
# Why: allow_origins=["*"] lets any webpage on the internet trigger trades by
# making cross-origin requests.  We only serve a local dashboard, so lock it.
_ALLOWED_ORIGINS = [o.strip() for o in
                    os.getenv("ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ── Optional API-key auth for all /api/* routes ───────────────────────────────
# Set UI_API_KEY in .env to require this header from the browser.
# Why: without auth, anyone on your LAN (or port-forwarded internet) can trade.
_UI_API_KEY: Optional[str] = os.getenv("UI_API_KEY") or None

async def _require_auth(request: Request):
    """Dependency — call on every trading endpoint."""
    if _UI_API_KEY is None:
        return  # auth disabled (local-only use)
    provided = request.headers.get("X-API-Key", "")
    # secrets.compare_digest prevents timing attacks
    if not provided or not secrets.compare_digest(provided, _UI_API_KEY):
        raise HTTPException(401, "Unauthorized")

# ── In-memory log buffer ───────────────────────────────────────────────────────
log_buffer: deque = deque(maxlen=500)
_active_ws: List[WebSocket] = []


class _WSLogHandler(logging.Handler):
    """Appends records to the in-memory buffer for WebSocket delivery."""

    def emit(self, record: logging.LogRecord) -> None:
        entry = {
            "ts": datetime.now().strftime("%H:%M:%S"),
            "level": record.levelname,
            "msg": self.format(record),
        }
        log_buffer.append(entry)


_ws_handler = _WSLogHandler()
_ws_handler.setFormatter(logging.Formatter("%(name)s › %(message)s"))
_ws_handler.setLevel(logging.INFO)
logging.getLogger().addHandler(_ws_handler)
logging.getLogger().setLevel(logging.INFO)

api_log = logging.getLogger("bnce-api")

# ── Input validation helpers ───────────────────────────────────────────────────
# Why: never trust client-supplied strings — sanitize before they reach the
# exchange or logs.  A malformed symbol or negative quantity must be rejected
# here, not inside Binance's SDK where the error message leaks internals.

import re as _re
_SYMBOL_RE = _re.compile(r'^[A-Z0-9]{3,20}$')
_VALID_SIDES = {"BUY", "SELL"}
_MAX_QUANTITY  = 1_000.0   # hard upper cap — prevents accidental full-balance wipes
_MAX_PRICE     = 10_000_000.0

def _clean_symbol(v: str) -> str:
    v = v.upper().strip()
    if not _SYMBOL_RE.match(v):
        raise HTTPException(400, f"Invalid symbol — must be 3-20 uppercase alphanumeric characters")
    return v

def _clean_side(v: str) -> str:
    v = v.upper().strip()
    if v not in _VALID_SIDES:
        raise ValueError(f"Side must be BUY or SELL, got '{v}'")
    return v

def _positive(v: float, name: str = "value") -> float:
    if v <= 0:
        raise ValueError(f"{name} must be positive, got {v}")
    if v > _MAX_PRICE:
        raise ValueError(f"{name} {v} exceeds maximum allowed {_MAX_PRICE}")
    return v

def _safe_qty(v: float) -> float:
    if v <= 0:
        raise ValueError(f"quantity must be positive, got {v}")
    if v > _MAX_QUANTITY:
        raise ValueError(f"quantity {v} exceeds safety cap of {_MAX_QUANTITY}")
    return v

# ── Pydantic request models (with full validation) ────────────────────────────

class MarketOrderReq(BaseModel):
    symbol:   str
    side:     str
    quantity: float
    dry_run:  bool = False

    @field_validator("symbol")
    @classmethod
    def val_symbol(cls, v): return _clean_symbol(v)

    @field_validator("side")
    @classmethod
    def val_side(cls, v): return _clean_side(v)

    @field_validator("quantity")
    @classmethod
    def val_qty(cls, v): return _safe_qty(v)


class LimitOrderReq(BaseModel):
    symbol:   str
    side:     str
    quantity: float
    price:    float
    dry_run:  bool = False

    @field_validator("symbol")
    @classmethod
    def val_symbol(cls, v): return _clean_symbol(v)

    @field_validator("side")
    @classmethod
    def val_side(cls, v): return _clean_side(v)

    @field_validator("quantity")
    @classmethod
    def val_qty(cls, v): return _safe_qty(v)

    @field_validator("price")
    @classmethod
    def val_price(cls, v): return _positive(v, "price")


class OCOOrderReq(BaseModel):
    symbol:           str
    side:             str
    quantity:         float
    price:            float
    stop_price:       float
    stop_limit_price: float
    dry_run:          bool = False

    @field_validator("symbol")
    @classmethod
    def val_symbol(cls, v): return _clean_symbol(v)

    @field_validator("side")
    @classmethod
    def val_side(cls, v): return _clean_side(v)

    @field_validator("quantity")
    @classmethod
    def val_qty(cls, v): return _safe_qty(v)

    @field_validator("price", "stop_price", "stop_limit_price")
    @classmethod
    def val_prices(cls, v): return _positive(v, "price field")


class StopLimitOrderReq(BaseModel):
    symbol:     str
    side:       str
    quantity:   float
    stop_price: float
    price:      float
    dry_run:    bool = False

    @field_validator("symbol")
    @classmethod
    def val_symbol(cls, v): return _clean_symbol(v)

    @field_validator("side")
    @classmethod
    def val_side(cls, v): return _clean_side(v)

    @field_validator("quantity")
    @classmethod
    def val_qty(cls, v): return _safe_qty(v)

    @field_validator("price", "stop_price")
    @classmethod
    def val_prices(cls, v): return _positive(v, "price field")


class TWAPOrderReq(BaseModel):
    symbol:           str
    side:             str
    total_quantity:   float
    parts:            int
    interval_seconds: int
    dry_run:          bool = False

    @field_validator("symbol")
    @classmethod
    def val_symbol(cls, v): return _clean_symbol(v)

    @field_validator("side")
    @classmethod
    def val_side(cls, v): return _clean_side(v)

    @field_validator("total_quantity")
    @classmethod
    def val_qty(cls, v): return _safe_qty(v)

    @field_validator("parts")
    @classmethod
    def val_parts(cls, v):
        # Why: unbounded parts = unlimited orders; cap at 20 per TWAP run
        if not (1 <= v <= 20):
            raise ValueError("parts must be between 1 and 20")
        return v

    @field_validator("interval_seconds")
    @classmethod
    def val_interval(cls, v):
        # Why: minimum 5s prevents accidental burst; max 1h keeps it sane
        if not (5 <= v <= 3600):
            raise ValueError("interval_seconds must be between 5 and 3600")
        return v


def _get_client():
    """Return a Binance UMFutures client using env vars."""
    from binance.um_futures import UMFutures
    use_testnet = os.getenv("USE_TESTNET", "true").lower() == "true"
    base_url = "https://testnet.binancefuture.com" if use_testnet else "https://fapi.binance.com"
    return UMFutures(
        key=os.getenv("BINANCE_API_KEY"),
        secret=os.getenv("BINANCE_SECRET_KEY"),
        base_url=base_url,
    )


class BacktestRequest(BaseModel):
    symbols: list[str] = ["BTCUSDT"]
    primary_tf: str = "5m"
    confirm_tf: str = "1h"
    start_date: str = "2024-01-01"
    end_date: str = "2024-03-01"
    initial_capital: float = 10_000.0


@app.post("/api/backtest/run")
@limiter.limit("3/minute")
async def run_backtest(request: Request, body: BacktestRequest):
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
        symbols=body.symbols,
        primary_tf=body.primary_tf,
        confirm_tf=body.confirm_tf,
        start=start,
        end=end,
        initial_capital=body.initial_capital,
        mode="portfolio",
    )

    client = _get_client()
    cache_dir = Path("data/cache")
    bars = {}

    for sym in cfg.symbols:
        for tf in [cfg.primary_tf, cfg.confirm_tf]:
            pad_ms  = _tf_to_ms(tf) * 200
            padded  = datetime.fromtimestamp(start.timestamp() - pad_ms / 1000, tz=timezone.utc)
            bars[(sym, tf)] = download_klines(client, sym, tf, padded, end, cache_dir)

    feed = DataFeed(
        bars=bars, primary_tf=cfg.primary_tf,
        symbols=cfg.symbols, start=start, end=end,
    )

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


# ── Lazy bot singletons ────────────────────────────────────────────────────────
_market_bot = None
_limit_bot  = None

# ── Trade Tracker singleton ───────────────────────────────────────────────────
_tracker = None

# ── IntelligenceEngine singleton ─────────────────────────────────────────────
_intel_engine = None

def _get_intel():
    global _intel_engine
    if _intel_engine is None:
        try:
            from intelligence import IntelligenceEngine
            _intel_engine = IntelligenceEngine()
            api_log.info("IntelligenceEngine ready")
        except Exception as exc:
            api_log.warning(f"IntelligenceEngine unavailable: {exc}")
            raise HTTPException(503, "IntelligenceEngine unavailable")
    return _intel_engine


# ── News engine singleton ─────────────────────────────────────────────────────
_news_engine = None

def _get_news_engine():
    global _news_engine
    if _news_engine is None:
        try:
            from news_engine import NewsEngine
            _news_engine = NewsEngine(
                on_signal    = _news_auto_execute,
                default_symbol = "BTCUSDT",
                auto_trade   = False,   # off by default, toggled via API
            )
            _news_engine.start()
            api_log.info("NewsEngine started")
        except Exception as e:
            api_log.warning(f"NewsEngine unavailable: {e}")
    return _news_engine


def _news_auto_execute(sig):
    """
    Called by NewsEngine when auto_trade=True and |score| >= threshold.

    Flow:
      1. Risk gate — checks daily loss / drawdown / open-position limits
      2. Entry — MARKET order ~$150 notional
      3. TP   — LIMIT order on opposite side, price scaled by news score
      4. SL   — background thread monitors mark price, fires MARKET if hit
         (Binance testnet blocks native STOP_MARKET, so we simulate it)

    TP/SL sizing:
      score 30–49  → TP +1.0%, SL -0.6%  (weak signal, tight target)
      score 50–74  → TP +1.5%, SL -0.8%
      score 75–100 → TP +2.0%, SL -1.0%  (strong signal, wider target)
    """
    import threading, time
    notifier = _get_notifier()

    try:
        from risk_manager import RiskManager
        rm = RiskManager()
        if not rm.is_trading_allowed():
            api_log.warning(
                f"NEWS AUTO-TRADE blocked by RiskManager: {sig.direction} {sig.symbol}"
            )
            return

        from binance.um_futures import UMFutures
        use_testnet = os.getenv("USE_TESTNET", "true").lower() == "true"
        base_url = "https://testnet.binancefuture.com" if use_testnet else "https://fapi.binance.com"
        client = UMFutures(
            key=os.getenv("BINANCE_API_KEY"),
            secret=os.getenv("BINANCE_SECRET_KEY"),
            base_url=base_url,
        )

        mark_px = float(client.ticker_price(symbol=sig.symbol)["price"])
        if mark_px <= 0:
            api_log.error("NEWS AUTO-TRADE: invalid mark price, aborting")
            return

        qty = round(150.0 / mark_px, 3)
        if qty <= 0:
            return

        # ── Step 1: Entry ────────────────────────────────────────────────────
        result = client.new_order(
            symbol=sig.symbol,
            side=sig.direction,
            type="MARKET",
            quantity=qty,
        )
        avg = float(result.get("avgPrice") or 0)
        if avg == 0:
            avg = mark_px
        _record_fill(sig.symbol, sig.direction, qty, avg, str(result.get("orderId", "")))
        rm.record_trade_open()
        api_log.info(
            f"NEWS AUTO-TRADE ENTRY: {sig.direction} {qty} {sig.symbol} @ {avg:.2f} "
            f"| score={sig.score:+.0f} | '{sig.headline[:50]}'"
        )

        # ── TP/SL levels scaled by signal strength ───────────────────────────
        abs_score = abs(sig.score)
        if abs_score >= 75:
            tp_pct, sl_pct = 0.020, 0.010
        elif abs_score >= 50:
            tp_pct, sl_pct = 0.015, 0.008
        else:
            tp_pct, sl_pct = 0.010, 0.006

        is_long = sig.direction == "BUY"
        exit_side = "SELL" if is_long else "BUY"

        if is_long:
            tp_price = round(avg * (1 + tp_pct), 2)
            sl_price = round(avg * (1 - sl_pct), 2)
        else:
            tp_price = round(avg * (1 - tp_pct), 2)
            sl_price = round(avg * (1 + sl_pct), 2)

        # ── Step 2: Take-Profit — LIMIT order on opposite side ───────────────
        tp_order_id = None
        try:
            tp_result = client.new_order(
                symbol=sig.symbol,
                side=exit_side,
                type="LIMIT",
                quantity=qty,
                price=str(tp_price),
                timeInForce="GTC",
                reduceOnly="true",
            )
            tp_order_id = tp_result.get("orderId")
            api_log.info(
                f"NEWS AUTO-TRADE TP SET: {exit_side} {qty} {sig.symbol} "
                f"@ {tp_price:.2f} (id={tp_order_id})"
            )
        except Exception as e:
            api_log.error(f"NEWS AUTO-TRADE: TP order failed: {e}")

        notifier.order_filled(sig.symbol, sig.direction, qty, avg, str(result.get("orderId", "")))
        notifier.signal_alert(sig.symbol, sig.direction, avg, sl_price, tp_price,
                               abs(sig.score), [sig.headline[:80]])

        # ── Step 3: Stop-Loss — background monitor thread ────────────────────
        # Testnet blocks STOP_MARKET; we poll mark price and fire MARKET when hit.
        # IMPORTANT: every exit path calls rm.record_trade_close() so the open-
        # position counter decrements and the next signal can be accepted.
        def _sl_monitor():
            api_log.info(
                f"NEWS AUTO-TRADE SL MONITOR: watching {sig.symbol} "
                f"sl={sl_price:.2f} tp={tp_price:.2f}"
            )

            def _exit(reason: str, exit_price: float):
                """Cancel TP, fire exit MARKET, decrement risk counter."""
                if tp_order_id:
                    try:
                        client.cancel_order(symbol=sig.symbol, orderId=tp_order_id)
                    except Exception:
                        pass
                try:
                    client.new_order(
                        symbol=sig.symbol, side=exit_side,
                        type="MARKET", quantity=qty, reduceOnly="true",
                    )
                except Exception as e:
                    api_log.error(f"NEWS exit order failed ({reason}): {e}")
                # Always decrement — even if the exit order itself fails the
                # position is being closed, so the slot must free up.
                rm.record_trade_close(pnl=0.0, equity=exit_price * qty)
                pnl_v = ((exit_price - avg) if is_long else (avg - exit_price)) * qty
                pnl_p = pnl_v / (avg * qty) * 100 if avg * qty > 0 else 0.0
                notifier.trade_closed(sig.symbol, sig.direction, pnl_v, pnl_p)
                api_log.info(f"NEWS AUTO-TRADE CLOSED ({reason}): {sig.symbol}")

            deadline = time.time() + 3600  # 1h max hold
            while time.time() < deadline:
                try:
                    mark = float(client.mark_price(symbol=sig.symbol)["markPrice"])
                    sl_hit = (is_long and mark <= sl_price) or (not is_long and mark >= sl_price)
                    tp_hit = (is_long and mark >= tp_price) or (not is_long and mark <= tp_price)

                    if sl_hit:
                        api_log.info(
                            f"NEWS AUTO-TRADE SL HIT: mark={mark:.2f} sl={sl_price:.2f}"
                        )
                        _exit("SL", mark)
                        return

                    if tp_hit:
                        api_log.info(
                            f"NEWS AUTO-TRADE TP HIT: mark={mark:.2f} tp={tp_price:.2f}"
                        )
                        # TP LIMIT likely already filled; still decrement counter
                        rm.record_trade_close(pnl=0.0, equity=mark * qty)
                        pnl_v = ((mark - avg) if is_long else (avg - mark)) * qty
                        pnl_p = pnl_v / (avg * qty) * 100 if avg * qty > 0 else 0.0
                        notifier.trade_closed(sig.symbol, sig.direction, pnl_v, pnl_p)
                        return

                except Exception as e:
                    api_log.error(f"NEWS SL monitor error: {e}")
                time.sleep(5)

            # 1h timeout
            api_log.warning(f"NEWS AUTO-TRADE TIMEOUT: closing {sig.symbol} at market")
            try:
                mark = float(client.mark_price(symbol=sig.symbol)["markPrice"])
            except Exception:
                mark = avg
            _exit("TIMEOUT", mark)

        threading.Thread(target=_sl_monitor, daemon=True,
                         name=f"news-sl-{sig.symbol}").start()

    except Exception as e:
        api_log.error(f"News auto-execute failed: {e}")
        notifier.error_alert(f"News auto-trade error: {str(e)[:100]}")

def _get_tracker():
    global _tracker
    if _tracker is None:
        try:
            from trade_tracker import TradeTracker
            mode = os.getenv("BINANCE_MODE", "live").lower()
            if mode == "paper":
                _tracker = TradeTracker(db_path=Path("data/db/paper_trades.db"))
                api_log.info("TradeTracker connected to PAPER mode DB")
            else:
                _tracker = TradeTracker()
                api_log.info("TradeTracker connected to LIVE mode DB")
        except Exception as exc:
            api_log.warning(f"TradeTracker unavailable: {exc}")
    return _tracker


# ── Telegram notifier singleton ────────────────────────────────────────────────
_notifier_inst = None

def _get_notifier():
    global _notifier_inst
    if _notifier_inst is None:
        try:
            from notifications import TelegramNotifier
            _notifier_inst = TelegramNotifier()
            if _notifier_inst.enabled:
                api_log.info("Telegram notifier enabled")
            else:
                api_log.info("Telegram notifier loaded but disabled (no token/chat_id in .env)")
        except Exception as e:
            api_log.warning(f"TelegramNotifier unavailable: {e}")

            class _Noop:
                def send_async(self, *a, **k): pass
                def signal_alert(self, *a, **k): pass
                def order_filled(self, *a, **k): pass
                def trade_closed(self, *a, **k): pass
                def error_alert(self, *a, **k): pass
                def daily_summary(self, *a, **k): pass

            _notifier_inst = _Noop()
    return _notifier_inst


async def _daily_summary_loop():
    """Send Telegram daily P&L summary at 23:55 UTC, once per day."""
    from datetime import timezone
    sent_date = ""
    while True:
        await asyncio.sleep(60)
        now = datetime.now(timezone.utc)
        today = str(now.date())
        if now.hour == 23 and now.minute >= 55 and sent_date != today:
            try:
                from trade_tracker import TradeTracker
                from risk_manager import RiskManager
                tracker = TradeTracker()
                rm = RiskManager()
                state = rm.status()
                stats = tracker.get_stats(since=today)
                _get_notifier().daily_summary(
                    pnl=state.get("daily_pnl", 0),
                    trades=stats.get("total_trades", 0),
                    win_rate=stats.get("win_rate", 0),
                    equity=state.get("peak_equity", 0),
                )
                sent_date = today
                api_log.info("Daily Telegram summary sent")
            except Exception as e:
                api_log.error(f"Daily summary failed: {e}")


def _record_fill(symbol: str, side: str, quantity: float,
                 avg_price: float, order_id: str = ""):
    """
    Record a filled order in the TradeTracker.
    - BUY  → open a LONG (or close an open SHORT for this symbol)
    - SELL → open a SHORT (or close an open LONG for this symbol)
    This makes manual UI orders visible in Trade Stats.
    """
    tracker = _get_tracker()
    if tracker is None:
        return

    try:
        symbol = symbol.upper()
        side   = side.upper()

        # Binance testnet often returns avgPrice="0" for market orders.
        # Fall back to the live ticker so the entry price is meaningful.
        if avg_price == 0:
            try:
                from binance.um_futures import UMFutures
                client = UMFutures(
                    key=os.getenv("BINANCE_API_KEY"),
                    secret=os.getenv("BINANCE_SECRET_KEY"),
                    base_url="https://testnet.binancefuture.com"
                    if os.getenv("USE_TESTNET", "true").lower() == "true"
                    else "https://fapi.binance.com",
                )
                avg_price = float(client.ticker_price(symbol=symbol)["price"])
            except Exception:
                pass   # keep 0 rather than crash

        # Find any open trade for this symbol to see if this is a close
        open_trades = [t for t in tracker.get_open_trades() if t.symbol == symbol]

        if open_trades:
            existing = open_trades[0]
            is_close = (
                (existing.direction == "LONG"  and side == "SELL") or
                (existing.direction == "SHORT" and side == "BUY")
            )
            if is_close:
                tracker.close_trade(existing.id, avg_price, close_reason="MANUAL")
                api_log.info(f"TradeTracker: closed {existing.direction} #{existing.id} @ {avg_price}")
                return

        # Opening a new position
        direction = "LONG" if side == "BUY" else "SHORT"
        tid = tracker.open_trade(
            symbol      = symbol,
            direction   = direction,
            entry_price = avg_price,
            stop_loss   = 0.0,
            take_profit = 0.0,
            quantity    = quantity,
            order_id    = str(order_id),
        )
        api_log.info(f"TradeTracker: opened {direction} #{tid} {symbol} @ {avg_price}")

    except Exception as exc:
        api_log.warning(f"TradeTracker record_fill error: {exc}")


def _market() :
    global _market_bot
    if _market_bot is None:
        try:
            from market_orders import MarketOrderBot
            _market_bot = MarketOrderBot()
            api_log.info("MarketOrderBot ready")
        except SystemExit:
            raise HTTPException(503, "Bot exited during init — check API keys / .env")
        except Exception as exc:
            api_log.error(f"MarketOrderBot init failed: {exc}")
            raise HTTPException(503, str(exc))
    return _market_bot


def _limit():
    global _limit_bot
    if _limit_bot is None:
        try:
            from limit_orders import LimitOrderBot
            _limit_bot = LimitOrderBot()
            api_log.info("LimitOrderBot ready")
        except SystemExit:
            raise HTTPException(503, "Bot exited during init — check API keys / .env")
        except Exception as exc:
            api_log.error(f"LimitOrderBot init failed: {exc}")
            raise HTTPException(503, str(exc))
    return _limit_bot


# ── Endpoints ──────────────────────────────────────────────────────────────────

# Validated intervals for ML/signal endpoints — whitelist prevents open-ended
# string injection into the Binance klines API call.
_VALID_INTERVALS = {"1m","3m","5m","15m","30m","1h","2h","4h","6h","8h","12h","1d","3d","1w","1M"}

def _safe_interval(v: str) -> str:
    if v not in _VALID_INTERVALS:
        raise HTTPException(400, f"Invalid interval '{v}'. Must be one of: {', '.join(sorted(_VALID_INTERVALS))}")
    return v

def _safe_limit(v: int, lo: int = 1, hi: int = 200) -> int:
    if not (lo <= v <= hi):
        raise HTTPException(400, f"limit must be {lo}–{hi}")
    return v


@app.get("/api/status")
@limiter.limit(_RATE_READ)
async def status(request: Request):
    api_key = os.getenv("BINANCE_API_KEY", "")
    secret  = os.getenv("BINANCE_SECRET_KEY", "")
    testnet = os.getenv("USE_TESTNET", "true").lower() == "true"
    mode    = os.getenv("BINANCE_MODE", "live").lower()
    
    api_log.info(f"Status check — testnet={testnet} mode={mode}")
    return {
        "api_key_set":    bool(api_key),
        "secret_key_set": bool(secret),
        "testnet":        testnet,
        "mode":           mode,
        "timestamp":      datetime.now().isoformat(),
    }


@app.post("/api/order/market")
@limiter.limit(_RATE_TRADE)
async def market_order(request: Request, req: MarketOrderReq):
    await _require_auth(request)
    api_log.info(f"MARKET {req.side} {req.quantity} {req.symbol} dry={req.dry_run}")
    bot = _market()
    if req.dry_run:
        sym = bot.validate_symbol(req.symbol.upper())
        qty = bot.validate_quantity(req.symbol.upper(), req.quantity) if sym else False
        return {"dry_run": True, "symbol_valid": sym, "quantity_valid": qty}
    result = bot.place_market_order(req.symbol, req.side, req.quantity)
    if not result:
        raise HTTPException(400, "Order failed — see logs")
    avg_price = float(result.get("avgPrice") or result.get("price") or 0)
    _record_fill(req.symbol, req.side, req.quantity, avg_price, result.get("orderId",""))
    return {"success": True, "order": result}


@app.post("/api/order/limit")
@limiter.limit(_RATE_TRADE)
async def limit_order(request: Request, req: LimitOrderReq):
    await _require_auth(request)
    api_log.info(f"LIMIT {req.side} {req.quantity} {req.symbol} @ {req.price} dry={req.dry_run}")
    bot = _limit()
    if req.dry_run:
        sym   = bot.validate_symbol(req.symbol.upper())
        qty   = bot.validate_quantity(req.symbol.upper(), req.quantity) if sym else False
        price = bot.validate_price(req.symbol.upper(), req.price)       if sym else False
        return {"dry_run": True, "symbol_valid": sym, "quantity_valid": qty, "price_valid": price}
    result = bot.place_limit_order(req.symbol, req.side, req.quantity, req.price)
    if not result:
        raise HTTPException(400, "Order failed — see logs")
    order_status = result.get("status", "")
    if order_status in ("FILLED", "PARTIALLY_FILLED"):
        _record_fill(req.symbol, req.side, req.quantity, req.price, result.get("orderId",""))
    return {"success": True, "order": result}


@app.post("/api/order/oco")
@limiter.limit(_RATE_TRADE)
async def oco_order(request: Request, req: OCOOrderReq):
    await _require_auth(request)
    api_log.info(f"OCO {req.side} {req.quantity} {req.symbol} dry={req.dry_run}")
    try:
        from advanced.oco import BinanceOCOBot
        bot = BinanceOCOBot()
        result = bot.place_oco_order(
            req.symbol, req.side, req.quantity,
            req.price, req.stop_price, req.stop_limit_price,
            dry_run=req.dry_run,
        )
        return {"success": True, "dry_run": req.dry_run, "legs": result}
    except SystemExit:
        raise HTTPException(503, "OCO bot could not connect — check keys")
    except Exception as exc:
        api_log.error(f"OCO error: {exc}")
        # Why: never echo raw exc to client — it may contain internal paths or Binance internals
        raise HTTPException(500, "OCO order failed — see server logs")


@app.post("/api/order/stop_limit")
@limiter.limit(_RATE_TRADE)
async def stop_limit_order(request: Request, req: StopLimitOrderReq):
    await _require_auth(request)
    api_log.info(f"STOP-LIMIT {req.side} {req.quantity} {req.symbol} stop={req.stop_price} lim={req.price}")

    notional = req.quantity * req.price
    if notional < 100:
        min_qty = round(100 / req.price * 1.05, 3)
        raise HTTPException(
            400,
            f"Order notional ${notional:.2f} is below the $100 Binance Futures minimum. "
            f"Increase quantity to at least {min_qty} at this price."
        )

    try:
        from binance.um_futures import UMFutures
        from advanced.stop_limit_orders import StopLimitOrderHandler
        import threading, time

        _use_testnet = os.getenv("USE_TESTNET", "true").lower() == "true"
        _base_url = "https://testnet.binancefuture.com" if _use_testnet else "https://fapi.binance.com"
        client = UMFutures(
            key=os.getenv("BINANCE_API_KEY"),
            secret=os.getenv("BINANCE_SECRET_KEY"),
            base_url=_base_url,
        )
        handler = StopLimitOrderHandler(client, api_log)

        if req.dry_run:
            valid = handler.validate_stop_limit_params(
                req.symbol.upper(), req.side.upper(),
                req.quantity, req.stop_price, req.price,
            )
            return {"dry_run": True, "valid": valid, "notional": round(notional, 2)}

        symbol_u = req.symbol.upper()
        side_u   = req.side.upper()
        stop_px  = req.stop_price
        qty      = req.quantity

        def _monitor_stop():
            sell_side = side_u == "SELL"
            api_log.info(f"STP monitor started: {symbol_u} {side_u} qty={qty} stop={stop_px}")
            deadline = time.time() + 3600
            while time.time() < deadline:
                try:
                    mark = float(client.mark_price(symbol=symbol_u)["markPrice"])
                    triggered = (sell_side and mark <= stop_px) or (not sell_side and mark >= stop_px)
                    if triggered:
                        api_log.info(f"STP triggered: mark={mark} crossed stop={stop_px} — firing MARKET")
                        client.new_order(symbol=symbol_u, side=side_u, type="MARKET", quantity=qty)
                        return
                except Exception as e:
                    api_log.error(f"STP monitor error: {e}")
                time.sleep(5)
            api_log.warning(f"STP monitor timed out for {symbol_u}")

        threading.Thread(target=_monitor_stop, daemon=True).start()
        return {
            "success": True,
            "type": "STOP_MONITORED",
            "symbol": symbol_u,
            "side": side_u,
            "quantity": qty,
            "stop_price": stop_px,
            "limit_price": req.price,
            "note": "Testnet: server monitors mark price and fires MARKET when stop is hit",
        }
    except HTTPException:
        raise
    except Exception as exc:
        msg = str(exc)
        if "-4164" in msg or "notional" in msg.lower():
            min_qty = round(100 / req.price * 1.05, 3)
            raise HTTPException(
                400,
                f"Notional too small (${notional:.2f} < $100 minimum). "
                f"Use quantity ≥ {min_qty} at this price."
            )
        api_log.error(f"Stop-limit error: {exc}")
        raise HTTPException(500, "Stop-limit order failed — see server logs")


@app.post("/api/order/twap")
@limiter.limit(_RATE_TWAP)
async def twap_order(request: Request, req: TWAPOrderReq):
    await _require_auth(request)
    part_qty = req.total_quantity / req.parts
    api_log.info(f"TWAP {req.parts}× {part_qty:.6f} {req.symbol} every {req.interval_seconds}s dry={req.dry_run}")

    if req.dry_run:
        return {
            "dry_run": True,
            "plan": f"{req.parts} orders × {part_qty:.6f} {req.symbol} every {req.interval_seconds}s",
        }

    bot = _market()
    executed, errors = 0, []
    total_value = 0.0
    for i in range(req.parts):
        api_log.info(f"TWAP [{i+1}/{req.parts}] {req.side} {part_qty} {req.symbol}")
        result = bot.place_market_order(req.symbol, req.side, part_qty)
        if result:
            executed += 1
            fill_price = float(result.get("avgPrice") or result.get("price") or 0)
            total_value += fill_price * part_qty
        else:
            errors.append(f"part {i+1} failed")
        if i < req.parts - 1:
            await asyncio.sleep(req.interval_seconds)

    if executed > 0:
        avg_fill = total_value / (part_qty * executed)
        _record_fill(req.symbol, req.side, part_qty * executed, avg_fill)

    return {"success": executed == req.parts, "parts_executed": executed, "errors": errors}


@app.get("/api/ml/analyze")
@limiter.limit(_RATE_SIGNAL)
async def ml_analyze(request: Request, symbol: str = "BTCUSDT", interval: str = "1m"):
    symbol   = _clean_symbol(symbol)
    interval = _safe_interval(interval)
    try:
        import pandas as pd
        from binance.um_futures import UMFutures

        client = UMFutures(
            key=os.getenv("BINANCE_API_KEY"),
            secret=os.getenv("BINANCE_SECRET_KEY"),
            base_url="https://testnet.binancefuture.com",
        )

        klines = client.klines(symbol, interval, limit=50)
        cols = ["OpenTime","Open","High","Low","Close","Volume",
                "CloseTime","QuoteVol","Trades","TakerBase","TakerQuote","Ignore"]
        df = pd.DataFrame(klines, columns=cols)
        for c in ["Open","High","Low","Close","Volume"]:
            df[c] = pd.to_numeric(df[c])

        close   = df["Close"]
        current = float(close.iloc[-1])
        pct_chg = (current - float(close.iloc[0])) / float(close.iloc[0]) * 100

        sma5  = float(close.rolling(5).mean().iloc[-1])
        sma10 = float(close.rolling(10).mean().iloc[-1])
        sma20 = float(close.rolling(20).mean().iloc[-1])
        ema12 = float(close.ewm(span=12, adjust=False).mean().iloc[-1])
        ema26 = float(close.ewm(span=26, adjust=False).mean().iloc[-1])
        macd  = ema12 - ema26

        delta = close.diff()
        gain  = delta.where(delta > 0, 0).rolling(14).mean()
        loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi   = float(100 - 100 / (1 + (gain / loss).iloc[-1]))

        std20    = close.rolling(20).std()
        sma20s   = close.rolling(20).mean()
        bb_upper = float((sma20s + std20 * 2).iloc[-1])
        bb_lower = float((sma20s - std20 * 2).iloc[-1])

        avg_vol   = float(df["Volume"].rolling(10).mean().iloc[-1])
        vol_ratio = float(df["Volume"].iloc[-1]) / avg_vol if avg_vol else 1.0

        candles = [
            {"o": float(r.Open), "h": float(r.High),
             "l": float(r.Low),  "c": float(r.Close), "v": float(r.Volume)}
            for _, r in df.tail(30).iterrows()
        ]

        # New Machine Learning Predictor Hooks:
        ml_prob = 0.5
        ml_action = "NEUTRAL"
        try:
            from ml.predictor import MLPredictor
            predictor = MLPredictor()
            if predictor.enabled:
                ml_prob = predictor.predict_up_probability(df)
                if ml_prob > 0.65: ml_action = "BULLISH"
                elif ml_prob < 0.35: ml_action = "BEARISH"
        except Exception as e:
            api_log.warning(f"ML Predictor fallback triggered inside /api/ml/analyze: {e}")

        api_log.info(f"ML {symbol}: ${current:,.2f} RSI={rsi:.1f} PROB={ml_prob*100:.1f}%")

        return {
            "symbol":          symbol,
            "price":           current,
            "price_change_pct": pct_chg,
            "indicators": {
                "sma_5": sma5, "sma_10": sma10, "sma_20": sma20,
                "ema_12": ema12, "ema_26": ema26, "macd": macd,
                "rsi": rsi, "bb_upper": bb_upper, "bb_lower": bb_lower,
                "volume_ratio": vol_ratio,
            },
            "signals": {
                "sma5":   "BULLISH"    if current > sma5   else "BEARISH",
                "sma20":  "BULLISH"    if current > sma20  else "BEARISH",
                "rsi":    "OVERBOUGHT" if rsi > 70  else ("OVERSOLD" if rsi < 30 else "NEUTRAL"),
                "macd":   "BULLISH"    if macd > 0  else "BEARISH",
                "bb":     "OVERBOUGHT" if current > bb_upper else ("OVERSOLD" if current < bb_lower else "NEUTRAL"),
                "volume": "HIGH"       if vol_ratio > 1.5 else ("LOW" if vol_ratio < 0.5 else "NORMAL"),
            },
            "ml_probability": round(ml_prob * 100, 2),
            "ml_action": ml_action,
            "candles": candles,
            "ts": datetime.now().isoformat(),
        }
    except Exception as exc:
        api_log.error(f"ML analysis failed: {exc}")
        raise HTTPException(500, "Analysis failed — see server logs")


@app.get("/api/signal")
@limiter.limit(_RATE_SIGNAL)
async def signal_scan(request: Request, symbol: str = "BTCUSDT", primary_tf: str = "5m", confirm_tf: str = "1h"):
    """Run the advanced multi-timeframe signal engine."""
    symbol     = _clean_symbol(symbol)
    primary_tf = _safe_interval(primary_tf)
    confirm_tf = _safe_interval(confirm_tf)
    try:
        import pandas as pd
        from binance.um_futures import UMFutures
        from signal_engine import SignalEngine

        client = UMFutures(
            key=os.getenv("BINANCE_API_KEY"),
            secret=os.getenv("BINANCE_SECRET_KEY"),
            base_url="https://testnet.binancefuture.com" if os.getenv("USE_TESTNET","true").lower()=="true" else "https://fapi.binance.com",
        )

        def fetch_klines(sym, interval, limit=200):
            raw = client.klines(sym, interval, limit=limit)
            cols = ["OpenTime","Open","High","Low","Close","Volume",
                    "CloseTime","QuoteVol","Trades","TakerBase","TakerQuote","Ignore"]
            df = pd.DataFrame(raw, columns=cols)
            for c in ["Open","High","Low","Close","Volume"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            return df

        def get_funding_rate(sym: str) -> float:
            info = client.mark_price(symbol=sym)
            return float(info.get("lastFundingRate", 0))

        engine = SignalEngine(fetch_klines, get_funding_rate)
        sig = engine.analyse(symbol.upper(), primary_tf, confirm_tf)

        if sig is None:
            return {
                "symbol": symbol.upper(), "has_signal": False,
                "primary_tf": primary_tf, "confirm_tf": confirm_tf,
                "message": "No high-confidence signal at this time",
            }

        return {
            "symbol":      sig.symbol,
            "has_signal":  True,
            "direction":   sig.direction.value,
            "confidence":  sig.confidence,
            "price":       sig.price,
            "stop_loss":   sig.stop_loss,
            "take_profit": sig.take_profit,
            "atr":         sig.atr,
            "primary_tf":  sig.timeframe,
            "confirm_tf":  confirm_tf,
            "reasons":     sig.reasons,
            "indicators":  {k: round(v, 6) if isinstance(v, float) else v
                            for k, v in sig.indicators.items()
                            if isinstance(v, (int, float, str, type(None)))},
            "ts": datetime.now().isoformat(),
        }
    except Exception as exc:
        api_log.error(f"Signal scan failed: {exc}")
        raise HTTPException(500, "Signal scan failed — see server logs")


@app.get("/api/stats")
@limiter.limit(_RATE_READ)
async def trade_stats(request: Request):
    """Return trade statistics from the SQLite tracker, including open positions."""
    try:
        from trade_tracker import TradeTracker
        from binance.um_futures import UMFutures

        tracker   = TradeTracker()
        stats     = tracker.get_stats()
        open_list = tracker.get_open_trades()
        recent    = tracker.get_closed_trades(limit=10)

        # Fetch current prices to compute unrealised PnL for open positions
        current_prices: dict = {}
        try:
            client = UMFutures(
                key=os.getenv("BINANCE_API_KEY"),
                secret=os.getenv("BINANCE_SECRET_KEY"),
                base_url="https://testnet.binancefuture.com"
                if os.getenv("USE_TESTNET", "true").lower() == "true"
                else "https://fapi.binance.com",
            )
            for t in open_list:
                if t.symbol not in current_prices:
                    current_prices[t.symbol] = float(
                        client.ticker_price(symbol=t.symbol)["price"]
                    )
        except Exception:
            pass  # price enrichment is best-effort

        open_enriched = []
        total_unrealised = 0.0
        for t in open_list:
            cp = current_prices.get(t.symbol)
            unreal = None
            if cp and t.entry_price:
                if t.direction == "LONG":
                    unreal = (cp - t.entry_price) * t.quantity
                else:
                    unreal = (t.entry_price - cp) * t.quantity
                total_unrealised += unreal
            open_enriched.append({
                "id":        t.id,
                "symbol":    t.symbol,
                "direction": t.direction,
                "entry":     t.entry_price,
                "quantity":  t.quantity,
                "current":   cp,
                "unrealised_pnl": round(unreal, 4) if unreal is not None else None,
                "entry_time": t.entry_time,
            })

        return {
            "stats":             stats,
            "open_positions":    len(open_list),
            "total_unrealised":  round(total_unrealised, 4),
            "open_trades":       open_enriched,
            "recent_trades": [
                {
                    "symbol":    t.symbol,
                    "direction": t.direction,
                    "entry":     t.entry_price,
                    "exit":      t.exit_price,
                    "pnl":       t.pnl,
                    "pnl_pct":   t.pnl_pct,
                    "reason":    t.close_reason,
                    "time":      t.exit_time,
                } for t in recent
            ],
        }
    except Exception as exc:
        api_log.error(f"Stats failed: {exc}")
        raise HTTPException(500, "Stats unavailable — see server logs")


@app.get("/api/stats/equity_curve")
@limiter.limit(_RATE_READ)
async def equity_curve(request: Request):
    """Return cumulative PnL series for charting."""
    try:
        from trade_tracker import TradeTracker
        tracker = TradeTracker()
        trades  = tracker.get_closed_trades(limit=500)
        trades  = list(reversed(trades))
        cum = 0.0
        points = []
        for t in trades:
            cum += t.pnl or 0.0
            points.append({
                "time":   t.exit_time[:16] if t.exit_time else "",
                "pnl":    round(t.pnl or 0.0, 4),
                "cum":    round(cum, 4),
                "reason": t.close_reason or "",
                "symbol": t.symbol,
            })
        return {"points": points, "total": round(cum, 4)}
    except Exception as exc:
        api_log.error(f"Equity curve failed: {exc}")
        raise HTTPException(500, "Equity curve unavailable — see server logs")


@app.get("/api/risk/status")
@limiter.limit(_RATE_READ)
async def risk_status(request: Request):
    """Return current risk manager state."""
    try:
        from risk_manager import RiskManager
        rm = RiskManager()
        return rm.status()
    except Exception as exc:
        api_log.error(f"Risk status failed: {exc}")
        raise HTTPException(500, "Risk status unavailable — see server logs")


@app.get("/api/logs")
@limiter.limit(_RATE_READ)
async def get_logs(request: Request, limit: int = 100):
    # Why: cap at 500 — returning the full deque via a tight loop would be a
    # trivial DoS by keeping the server busy serialising large payloads.
    limit = max(1, min(limit, 500))
    return {"logs": list(log_buffer)[-limit:]}


# ── News endpoints ────────────────────────────────────────────────────────────

@app.on_event("startup")
async def _startup():
    """Optionally start the news engine on boot (set NEWS_ENGINE=true to enable)."""
    if os.getenv("NEWS_ENGINE", "false").lower() == "true":
        _get_news_engine()
    else:
        api_log.info("NewsEngine disabled — set NEWS_ENGINE=true in .env to enable")
    asyncio.create_task(_daily_summary_loop())


@app.get("/api/news")
@limiter.limit(_RATE_READ)
async def get_news(request: Request, limit: int = 30):
    """Return recent news items with sentiment scores."""
    limit  = _safe_limit(limit, 1, 100)
    engine = _get_news_engine()
    if not engine:
        raise HTTPException(503, "News engine unavailable")
    items = engine.recent_news(limit)
    return {
        "auto_trade": engine._auto_trade,
        "count": len(items),
        "items": [
            {
                "title":     n.title,
                "summary":   n.summary[:200],
                "source":    n.source,
                "url":       n.url,
                "published": n.published,
                "score":     n.score,
                "sentiment": n.sentiment,
                "symbols":   n.symbols,
                "ts":        n.ts,
            }
            for n in reversed(items)
        ],
    }


@app.get("/api/news/signals")
@limiter.limit(_RATE_READ)
async def get_news_signals(request: Request, limit: int = 20):
    """Return recent news-triggered trade signals."""
    limit  = _safe_limit(limit, 1, 50)
    engine = _get_news_engine()
    if not engine:
        raise HTTPException(503, "News engine unavailable")
    sigs = engine.recent_signals(limit)
    return {
        "auto_trade": engine._auto_trade,
        "count": len(sigs),
        "signals": [
            {
                "symbol":    s.symbol,
                "direction": s.direction,
                "score":     s.score,
                "headline":  s.headline,
                "source":    s.source,
                "url":       s.url,
                "ts":        s.ts,
            }
            for s in reversed(sigs)
        ],
    }


@app.post("/api/news/auto_trade")
@limiter.limit(_RATE_TRADE)
async def set_auto_trade(request: Request, enabled: bool):
    """Enable or disable automatic trade execution on news signals."""
    # Why: this directly controls live trade execution — must require auth
    await _require_auth(request)
    engine = _get_news_engine()
    if not engine:
        raise HTTPException(503, "News engine unavailable")
    engine.set_auto_trade(enabled)
    api_log.info(f"News auto-trade toggled: {'ENABLED' if enabled else 'DISABLED'}")
    return {"auto_trade": enabled, "message": f"News auto-trade {'ENABLED' if enabled else 'DISABLED'}"}


# ── Market data endpoints ─────────────────────────────────────────────────────

@app.get("/api/prices")
@limiter.limit(_RATE_READ)
async def get_prices(request: Request, symbols: str = "BTCUSDT,ETHUSDT,SOLUSDT"):
    """Lightweight multi-symbol price fetch (no klines, just ticker)."""
    syms = [_clean_symbol(s.strip()) for s in symbols.split(",") if s.strip()][:10]
    try:
        from binance.um_futures import UMFutures
        client = UMFutures(
            key=os.getenv("BINANCE_API_KEY"), secret=os.getenv("BINANCE_SECRET_KEY"),
            base_url="https://testnet.binancefuture.com" if os.getenv("USE_TESTNET","true").lower()=="true" else "https://fapi.binance.com",
        )
        prices = {}
        for sym in syms:
            try:
                prices[sym] = float(client.ticker_price(symbol=sym)["price"])
            except Exception:
                prices[sym] = None
        return {"prices": prices, "ts": datetime.now().isoformat()}
    except Exception as exc:
        api_log.error(f"Prices failed: {exc}")
        raise HTTPException(500, "Prices unavailable — see server logs")


@app.get("/api/funding")
@limiter.limit(_RATE_READ)
async def get_funding_rates(request: Request,
                             symbols: str = "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT,ADAUSDT,AVAXUSDT,LINKUSDT,DOTUSDT"):
    """Return current funding rates and market bias for a list of symbols."""
    syms = [_clean_symbol(s.strip()) for s in symbols.split(",") if s.strip()][:15]
    try:
        from binance.um_futures import UMFutures
        client = UMFutures(
            key=os.getenv("BINANCE_API_KEY"), secret=os.getenv("BINANCE_SECRET_KEY"),
            base_url="https://testnet.binancefuture.com" if os.getenv("USE_TESTNET","true").lower()=="true" else "https://fapi.binance.com",
        )
        rates = []
        for sym in syms:
            try:
                info = client.mark_price(symbol=sym)
                rate  = float(info.get("lastFundingRate", 0))
                price = float(info.get("markPrice", 0))
                rates.append({
                    "symbol":          sym,
                    "funding_rate":    round(rate, 6),
                    "funding_pct":     round(rate * 100, 4),
                    "mark_price":      round(price, 4),
                    "annualized_pct":  round(rate * 3 * 365 * 100, 2),
                    # positive funding = longs pay shorts = crowded longs = short bias
                    "bias": "SHORT_BIAS" if rate > 0.0005 else ("LONG_BIAS" if rate < -0.0005 else "NEUTRAL"),
                })
            except Exception as e:
                api_log.warning(f"Funding rate error for {sym}: {e}")
        return {"rates": rates, "ts": datetime.now().isoformat()}
    except Exception as exc:
        api_log.error(f"Funding rates failed: {exc}")
        raise HTTPException(500, "Funding rates unavailable — see server logs")


@app.get("/api/signal/scan_multi")
@limiter.limit(_RATE_SIGNAL)
async def scan_multi_signal(request: Request,
                             symbols: str = "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT,ADAUSDT,AVAXUSDT,LINKUSDT,DOTUSDT",
                             primary_tf: str = "5m",
                             confirm_tf: str = "1h"):
    """Run multi-timeframe SignalEngine across multiple symbols, return all results."""
    syms       = [_clean_symbol(s.strip()) for s in symbols.split(",") if s.strip()][:10]
    primary_tf = _safe_interval(primary_tf)
    confirm_tf = _safe_interval(confirm_tf)
    try:
        import pandas as pd
        from binance.um_futures import UMFutures
        from signal_engine import SignalEngine

        client = UMFutures(
            key=os.getenv("BINANCE_API_KEY"), secret=os.getenv("BINANCE_SECRET_KEY"),
            base_url="https://testnet.binancefuture.com" if os.getenv("USE_TESTNET","true").lower()=="true" else "https://fapi.binance.com",
        )

        def fetch_klines(sym, interval, limit=200):
            raw  = client.klines(sym, interval, limit=limit)
            cols = ["OpenTime","Open","High","Low","Close","Volume",
                    "CloseTime","QuoteVol","Trades","TakerBase","TakerQuote","Ignore"]
            df = pd.DataFrame(raw, columns=cols)
            for c in ["Open","High","Low","Close","Volume"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            return df

        def get_funding_rate(sym: str) -> float:
            info = client.mark_price(symbol=sym)
            return float(info.get("lastFundingRate", 0))

        engine  = SignalEngine(fetch_klines, get_funding_rate)
        results = []
        for sym in syms:
            try:
                sig = engine.analyse(sym, primary_tf, confirm_tf)
                if sig:
                    results.append({
                        "symbol":     sig.symbol,
                        "direction":  sig.direction.value,
                        "confidence": sig.confidence,
                        "price":      sig.price,
                        "stop_loss":  sig.stop_loss,
                        "take_profit":sig.take_profit,
                        "atr":        sig.atr,
                        "reasons":    sig.reasons[:3],
                    })
                else:
                    # Still return the symbol so UI shows FLAT
                    try:
                        price = float(client.ticker_price(symbol=sym)["price"])
                    except Exception:
                        price = 0.0
                    results.append({"symbol": sym, "direction": "FLAT", "confidence": 0, "price": price})
            except Exception as e:
                api_log.warning(f"Scan error for {sym}: {e}")
                results.append({"symbol": sym, "direction": "FLAT", "confidence": 0, "error": str(e)[:50]})

        active = [r for r in results if r.get("direction") not in ("FLAT", None)]
        return {
            "scanned":       len(syms),
            "signals_found": len(active),
            "results":       results,
            "primary_tf":    primary_tf,
            "confirm_tf":    confirm_tf,
            "ts":            datetime.now().isoformat(),
        }
    except Exception as exc:
        api_log.error(f"Multi-scan failed: {exc}")
        raise HTTPException(500, "Multi-scan failed — see server logs")


@app.get("/api/journal")
@limiter.limit(_RATE_READ)
async def get_journal(request: Request, limit: int = 100):
    limit = _safe_limit(limit, 1, 500)
    try:
        from intelligence import IntelligenceEngine
        intel = _get_intel()
        return {
            "stats":        intel.get_journal_stats(),
            "rows":         intel.get_journal_rows(limit=limit),
            "kelly_active": intel.kelly_active,
        }
    except Exception as exc:
        api_log.error(f"Journal fetch failed: {exc}")
        raise HTTPException(500, "Journal unavailable — see server logs")


@app.get("/api/soul")
@limiter.limit(_RATE_READ)
async def get_soul(request: Request):
    try:
        return {"text": _get_intel().read_soul()}
    except Exception as exc:
        api_log.error(f"SOUL read failed: {exc}")
        raise HTTPException(500, "SOUL unavailable — see server logs")


@app.post("/api/soul")
@limiter.limit(_RATE_TRADE)
async def update_soul(request: Request, payload: dict):
    await _require_auth(request)
    text = payload.get("text", "")
    if not text.strip():
        raise HTTPException(400, "Empty SOUL text rejected")
    try:
        _get_intel().update_soul(text)
        api_log.info("SOUL.md updated via API")
        return {"ok": True}
    except Exception as exc:
        api_log.error(f"SOUL update failed: {exc}")
        raise HTTPException(500, "SOUL update failed — see server logs")


@app.get("/api/kelly")
@limiter.limit(_RATE_READ)
async def get_kelly(request: Request):
    try:
        intel  = _get_intel()
        stats  = intel.get_journal_stats()
        from risk_manager import RiskManager
        rm_state  = RiskManager()._state
        equity    = float(rm_state.get("peak_equity") or 10000.0)
        peak      = float(rm_state.get("peak_equity") or equity)
        drawdown  = (peak - equity) / peak if peak > 0 else 0.0
        next_size = intel.compute_kelly_size(equity, 80, "TRENDING", drawdown)
        return {
            "kelly_active":   intel.kelly_active,
            "trade_count":    stats["trade_count"],
            "win_rate":       stats["win_rate"],
            "avg_rr":         stats["avg_rr"],
            "next_size_usdt": next_size,
            "equity":         equity,
            "drawdown":       round(drawdown, 4),
        }
    except Exception as exc:
        api_log.error(f"Kelly fetch failed: {exc}")
        raise HTTPException(500, "Kelly unavailable — see server logs")


@app.get("/api/positions/live")
@limiter.limit(_RATE_READ)
async def live_binance_positions(request: Request):
    """Return actual open positions from Binance exchange (not SQLite tracker)."""
    try:
        from binance.um_futures import UMFutures
        client = UMFutures(
            key=os.getenv("BINANCE_API_KEY"), secret=os.getenv("BINANCE_SECRET_KEY"),
            base_url="https://testnet.binancefuture.com" if os.getenv("USE_TESTNET","true").lower()=="true" else "https://fapi.binance.com",
        )
        account = client.account()
        positions = [
            {
                "symbol":         p["symbol"],
                "side":           "LONG" if float(p["positionAmt"]) > 0 else "SHORT",
                "size":           abs(float(p["positionAmt"])),
                "entry_price":    float(p["entryPrice"]),
                "mark_price":     float(p.get("markPrice", p["entryPrice"])),
                "unrealised_pnl": round(float(p["unrealizedProfit"]), 4),
                "leverage":       int(p.get("leverage", 1)),
                "notional":       round(abs(float(p["positionAmt"])) * float(p.get("markPrice", p["entryPrice"])), 2),
            }
            for p in account.get("positions", [])
            if float(p.get("positionAmt", 0)) != 0
        ]
        total_unrealised = sum(pos["unrealised_pnl"] for pos in positions)
        return {
            "positions":      positions,
            "count":          len(positions),
            "total_unrealised": round(total_unrealised, 4),
            "ts":             datetime.now().isoformat(),
        }
    except Exception as exc:
        api_log.error(f"Live positions failed: {exc}")
        raise HTTPException(500, "Live positions unavailable — see server logs")


# ── WebSocket — streams buffered log entries ───────────────────────────────────
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    _active_ws.append(ws)
    api_log.info("WebSocket client connected")

    # Send buffered history
    await ws.send_json({"type": "init", "data": list(log_buffer)[-50:]})

    last_sent = len(log_buffer)
    try:
        while True:
            await asyncio.sleep(1)
            current_len = len(log_buffer)
            if current_len > last_sent:
                new_entries = list(log_buffer)[last_sent:current_len]
                for entry in new_entries:
                    await ws.send_json({"type": "log", "data": entry})
                last_sent = current_len
            else:
                tick = {"type": "ping"}
                try:
                    positions = _get_client().get_position_risk(recvWindow=5000)
                    upnl = sum(
                        float(p.get("unrealizedProfit", 0))
                        for p in positions
                        if float(p.get("positionAmt", 0)) != 0
                    )
                except Exception:
                    upnl = None

                tick["upnl"] = round(upnl, 2) if upnl is not None else None
                await ws.send_json(tick)
    except (WebSocketDisconnect, Exception):
        if ws in _active_ws:
            _active_ws.remove(ws)
        api_log.info("WebSocket client disconnected")


# ── WebSocket /ws/log — structured stream for STREAM tab ─────────────────────
@app.websocket("/ws/log")
async def ws_log_endpoint(ws: WebSocket):
    """Same as /ws but sends structured {type, msg, ts} events for the STREAM tab."""
    await ws.accept()
    _active_ws.append(ws)
    api_log.info("WS/log client connected")

    last_sent = len(log_buffer)
    try:
        while True:
            await asyncio.sleep(1)
            current_len = len(log_buffer)
            if current_len > last_sent:
                new_entries = list(log_buffer)[last_sent:current_len]
                for entry in new_entries:
                    await ws.send_json({
                        "type": entry.get("level", "INFO"),
                        "msg":  entry.get("msg", ""),
                        "ts":   entry.get("ts", ""),
                    })
                last_sent = current_len
            else:
                await ws.send_json({"type": "ping", "msg": "", "ts": ""})
    except (WebSocketDisconnect, Exception):
        if ws in _active_ws:
            _active_ws.remove(ws)
        api_log.info("WS/log client disconnected")


# ── Serve frontend ─────────────────────────────────────────────────────────────
@app.get("/")
async def serve_frontend():
    path = Path(__file__).parent / "frontend" / "index.html"
    if path.exists():
        return FileResponse(str(path))
    return HTMLResponse(
        "<pre style='font-family:monospace;padding:20px'>frontend/index.html not found.\n"
        "Place the HTML file at: frontend/index.html</pre>",
        status_code=404,
    )


if __name__ == "__main__":
    print("  BNCE//TERMINAL API")
    print(f"  http://localhost:8000\n")
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=False, log_level="info")
