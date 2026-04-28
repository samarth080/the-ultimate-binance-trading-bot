"""
Shared state, utilities, and singleton getters used across all route modules.
Nothing in this file imports from routes/ or auth.py — no circular deps.
"""
import asyncio
import logging
import os
import re as _re
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List

from fastapi import HTTPException, WebSocket
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

sys.path.insert(0, str(Path(__file__).parent / "src"))

# ── Rate limits ────────────────────────────────────────────────────────────────
RATE_TRADE  = os.getenv("RATE_TRADE",  "120/minute")
RATE_SIGNAL = os.getenv("RATE_SIGNAL", "60/minute")
RATE_TWAP   = os.getenv("RATE_TWAP",   "20/minute")
RATE_READ   = os.getenv("RATE_READ",   "120/minute")

limiter = Limiter(key_func=get_remote_address)

# ── In-memory log buffer ───────────────────────────────────────────────────────
log_buffer: deque = deque(maxlen=500)
active_ws: List[WebSocket] = []


class _WSLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        log_buffer.append({
            "ts":    datetime.now().strftime("%H:%M:%S"),
            "level": record.levelname,
            "msg":   self.format(record),
        })


_ws_handler = _WSLogHandler()
_ws_handler.setFormatter(logging.Formatter("%(name)s › %(message)s"))
_ws_handler.setLevel(logging.INFO)
logging.getLogger().addHandler(_ws_handler)
logging.getLogger().setLevel(logging.INFO)

api_log = logging.getLogger("bnce-api")

# ── Input validation ───────────────────────────────────────────────────────────
_SYMBOL_RE    = _re.compile(r'^[A-Z0-9]{3,20}$')
_VALID_SIDES  = {"BUY", "SELL"}
_MAX_QUANTITY = 1_000.0
_MAX_PRICE    = 10_000_000.0
_VALID_INTERVALS = {
    "1m","3m","5m","15m","30m","1h","2h","4h","6h","8h","12h","1d","3d","1w","1M"
}


def clean_symbol(v: str) -> str:
    v = v.upper().strip()
    if not _SYMBOL_RE.match(v):
        raise HTTPException(400, "Invalid symbol — must be 3-20 uppercase alphanumeric characters")
    return v


def clean_side(v: str) -> str:
    v = v.upper().strip()
    if v not in _VALID_SIDES:
        raise ValueError(f"Side must be BUY or SELL, got '{v}'")
    return v


def positive(v: float, name: str = "value") -> float:
    if v <= 0:
        raise ValueError(f"{name} must be positive, got {v}")
    if v > _MAX_PRICE:
        raise ValueError(f"{name} {v} exceeds maximum allowed {_MAX_PRICE}")
    return v


def safe_qty(v: float) -> float:
    if v <= 0:
        raise ValueError(f"quantity must be positive, got {v}")
    if v > _MAX_QUANTITY:
        raise ValueError(f"quantity {v} exceeds safety cap of {_MAX_QUANTITY}")
    return v


def safe_interval(v: str) -> str:
    if v not in _VALID_INTERVALS:
        raise HTTPException(400, f"Invalid interval '{v}'. Must be one of: {', '.join(sorted(_VALID_INTERVALS))}")
    return v


def safe_limit(v: int, lo: int = 1, hi: int = 200) -> int:
    if not (lo <= v <= hi):
        raise HTTPException(400, f"limit must be {lo}–{hi}")
    return v


# ── Binance client factory ────────────────────────────────────────────────────
def get_client():
    from binance.um_futures import UMFutures
    use_testnet = os.getenv("USE_TESTNET", "true").lower() == "true"
    base_url = "https://testnet.binancefuture.com" if use_testnet else "https://fapi.binance.com"
    return UMFutures(
        key=os.getenv("BINANCE_API_KEY"),
        secret=os.getenv("BINANCE_SECRET_KEY"),
        base_url=base_url,
    )


# ── Singletons ────────────────────────────────────────────────────────────────
_market_bot    = None
_limit_bot     = None
_tracker       = None
_intel_engine  = None
_news_engine   = None
_notifier_inst = None


def get_market_bot():
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


def get_limit_bot():
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


def get_tracker():
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


def get_notifier():
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


def get_intel():
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


def news_auto_execute(sig):
    """Callback fired by NewsEngine when a high-confidence news signal arrives."""
    notifier = get_notifier()
    try:
        from risk_manager import RiskManager
        rm = RiskManager()
        if not rm.is_trading_allowed():
            api_log.warning(f"NEWS AUTO-TRADE blocked by RiskManager: {sig.direction} {sig.symbol}")
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

        result = client.new_order(symbol=sig.symbol, side=sig.direction, type="MARKET", quantity=qty)
        avg = float(result.get("avgPrice") or 0) or mark_px
        record_fill(sig.symbol, sig.direction, qty, avg, str(result.get("orderId", "")))
        rm.record_trade_open()
        api_log.info(
            f"NEWS AUTO-TRADE ENTRY: {sig.direction} {qty} {sig.symbol} @ {avg:.2f} "
            f"| score={sig.score:+.0f} | '{sig.headline[:50]}'"
        )

        abs_score = abs(sig.score)
        if abs_score >= 75:
            tp_pct, sl_pct = 0.020, 0.010
        elif abs_score >= 50:
            tp_pct, sl_pct = 0.015, 0.008
        else:
            tp_pct, sl_pct = 0.010, 0.006

        is_long   = sig.direction == "BUY"
        exit_side = "SELL" if is_long else "BUY"
        tp_price  = round(avg * (1 + tp_pct if is_long else 1 - tp_pct), 2)
        sl_price  = round(avg * (1 - sl_pct if is_long else 1 + sl_pct), 2)

        tp_order_id = None
        try:
            tp_result   = client.new_order(
                symbol=sig.symbol, side=exit_side, type="LIMIT",
                quantity=qty, price=str(tp_price), timeInForce="GTC", reduceOnly="true",
            )
            tp_order_id = tp_result.get("orderId")
            api_log.info(f"NEWS AUTO-TRADE TP SET: {exit_side} {qty} {sig.symbol} @ {tp_price:.2f}")
        except Exception as e:
            api_log.error(f"NEWS AUTO-TRADE: TP order failed: {e}")

        notifier.order_filled(sig.symbol, sig.direction, qty, avg, str(result.get("orderId", "")))
        notifier.signal_alert(sig.symbol, sig.direction, avg, sl_price, tp_price,
                              abs(sig.score), [sig.headline[:80]])

        def _sl_monitor():
            def _exit(reason: str, exit_price: float):
                if tp_order_id:
                    try: client.cancel_order(symbol=sig.symbol, orderId=tp_order_id)
                    except Exception: pass
                try:
                    client.new_order(symbol=sig.symbol, side=exit_side,
                                     type="MARKET", quantity=qty, reduceOnly="true")
                except Exception as e:
                    api_log.error(f"NEWS exit order failed ({reason}): {e}")
                rm.record_trade_close(pnl=0.0, equity=exit_price * qty)
                pnl_v = ((exit_price - avg) if is_long else (avg - exit_price)) * qty
                pnl_p = pnl_v / (avg * qty) * 100 if avg * qty > 0 else 0.0
                notifier.trade_closed(sig.symbol, sig.direction, pnl_v, pnl_p)
                api_log.info(f"NEWS AUTO-TRADE CLOSED ({reason}): {sig.symbol}")

            deadline = time.time() + 3600
            while time.time() < deadline:
                try:
                    mark    = float(client.mark_price(symbol=sig.symbol)["markPrice"])
                    sl_hit  = (is_long and mark <= sl_price) or (not is_long and mark >= sl_price)
                    tp_hit  = (is_long and mark >= tp_price) or (not is_long and mark <= tp_price)
                    if sl_hit:
                        api_log.info(f"NEWS AUTO-TRADE SL HIT: mark={mark:.2f} sl={sl_price:.2f}")
                        _exit("SL", mark); return
                    if tp_hit:
                        api_log.info(f"NEWS AUTO-TRADE TP HIT: mark={mark:.2f} tp={tp_price:.2f}")
                        pnl_v = ((mark - avg) if is_long else (avg - mark)) * qty
                        pnl_p = pnl_v / (avg * qty) * 100 if avg * qty > 0 else 0.0
                        rm.record_trade_close(pnl=0.0, equity=mark * qty)
                        notifier.trade_closed(sig.symbol, sig.direction, pnl_v, pnl_p)
                        return
                except Exception as e:
                    api_log.error(f"NEWS SL monitor error: {e}")
                time.sleep(5)

            api_log.warning(f"NEWS AUTO-TRADE TIMEOUT: closing {sig.symbol} at market")
            try: mark = float(client.mark_price(symbol=sig.symbol)["markPrice"])
            except Exception: mark = avg
            _exit("TIMEOUT", mark)

        threading.Thread(target=_sl_monitor, daemon=True, name=f"news-sl-{sig.symbol}").start()

    except Exception as e:
        api_log.error(f"News auto-execute failed: {e}")
        notifier.error_alert(f"News auto-trade error: {str(e)[:100]}")


def get_news_engine():
    global _news_engine
    if _news_engine is None:
        try:
            from news_engine import NewsEngine
            _news_engine = NewsEngine(
                on_signal=news_auto_execute,
                default_symbol="BTCUSDT",
                auto_trade=False,
            )
            _news_engine.start()
            api_log.info("NewsEngine started")
        except Exception as e:
            api_log.warning(f"NewsEngine unavailable: {e}")
    return _news_engine


# ── Trade recording ────────────────────────────────────────────────────────────
def record_fill(symbol: str, side: str, quantity: float,
                avg_price: float, order_id: str = ""):
    tracker = get_tracker()
    if tracker is None:
        return
    try:
        symbol = symbol.upper()
        side   = side.upper()

        if avg_price == 0:
            try:
                client    = get_client()
                avg_price = float(client.ticker_price(symbol=symbol)["price"])
            except Exception:
                pass

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

        direction = "LONG" if side == "BUY" else "SHORT"
        tid = tracker.open_trade(
            symbol=symbol, direction=direction, entry_price=avg_price,
            stop_loss=0.0, take_profit=0.0, quantity=quantity, order_id=str(order_id),
        )
        api_log.info(f"TradeTracker: opened {direction} #{tid} {symbol} @ {avg_price}")

    except Exception as exc:
        api_log.warning(f"TradeTracker record_fill error: {exc}")


# ── Daily summary loop ────────────────────────────────────────────────────────
async def daily_summary_loop():
    sent_date = ""
    while True:
        await asyncio.sleep(60)
        now   = datetime.now(timezone.utc)
        today = str(now.date())
        if now.hour == 23 and now.minute >= 55 and sent_date != today:
            try:
                from trade_tracker import TradeTracker
                from risk_manager import RiskManager
                tracker = TradeTracker()
                rm      = RiskManager()
                state   = rm.status()
                stats   = tracker.get_stats(since=today)
                get_notifier().daily_summary(
                    pnl=state.get("daily_pnl", 0),
                    trades=stats.get("total_trades", 0),
                    win_rate=stats.get("win_rate", 0),
                    equity=state.get("peak_equity", 0),
                )
                sent_date = today
                api_log.info("Daily Telegram summary sent")
            except Exception as e:
                api_log.error(f"Daily summary failed: {e}")
