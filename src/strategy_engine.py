"""
Strategy Engine — autonomous trading loop.

Integrates:
  • SignalEngine     (multi-TF confluence signals)
  • RiskManager      (position sizing, daily loss limits, drawdown guard)
  • TradeTracker     (SQLite P&L history)
  • TelegramNotifier (alerts)
  • Binance UMFutures client (order placement + position monitoring)

Usage:
  python src/strategy_engine.py --symbols BTCUSDT ETHUSDT --primary 5m --confirm 1h

The loop runs indefinitely (Ctrl-C to stop). It:
  1. Scans configured symbols every `scan_interval` seconds.
  2. Generates signals via SignalEngine.
  3. Rejects trades failing risk/RR checks.
  4. Places a market entry + stop-market + take-profit-limit bracket.
  5. Monitors open positions for SL/TP hits and trailing stop updates.
  6. Logs every outcome to TradeTracker.
  7. Sends Telegram alerts for signals, fills, and closes.
"""

import os
import sys
import time
import logging
import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent))

from binance.um_futures import UMFutures
from binance.error import ClientError

from signal_engine  import SignalEngine, Signal, SignalDirection
from risk_manager   import RiskManager
from trade_tracker  import TradeTracker
from notifications  import TelegramNotifier

# ── logging ──────────────────────────────────────────────────────────────────
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s [%(name)s]: %(message)s",
    handlers=[
        logging.FileHandler(log_dir / "strategy.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("strategy")


# ── Binance client factory ────────────────────────────────────────────────────

def _make_client() -> UMFutures:
    api_key    = os.getenv("BINANCE_API_KEY",    "")
    secret_key = os.getenv("BINANCE_SECRET_KEY", "")
    use_testnet = os.getenv("USE_TESTNET", "true").lower() == "true"
    base_url = "https://testnet.binancefuture.com" if use_testnet else "https://fapi.binance.com"
    if not api_key or not secret_key:
        raise EnvironmentError("BINANCE_API_KEY / BINANCE_SECRET_KEY not set")
    return UMFutures(key=api_key, secret=secret_key, base_url=base_url)


# ── klines fetcher for SignalEngine ──────────────────────────────────────────

def _make_klines_fn(client: UMFutures):
    def fetch_klines(symbol: str, interval: str, limit: int = 200) -> pd.DataFrame:
        raw = client.klines(symbol, interval, limit=limit)
        cols = ["OpenTime","Open","High","Low","Close","Volume",
                "CloseTime","QuoteVol","Trades","TakerBase","TakerQuote","Ignore"]
        df = pd.DataFrame(raw, columns=cols)
        for c in ["Open","High","Low","Close","Volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df["OpenTime"] = pd.to_datetime(df["OpenTime"], unit="ms")
        return df
    return fetch_klines


# ── order helpers ─────────────────────────────────────────────────────────────

def _get_equity(client: UMFutures) -> float:
    try:
        info = client.account()
        for asset in info.get("assets", []):
            if asset.get("asset") == "USDT":
                return float(asset.get("walletBalance", 0))
        return float(info.get("totalWalletBalance", 0))
    except Exception as e:
        logger.error(f"Could not fetch equity: {e}")
        return 0.0


def _get_step_size(client: UMFutures, symbol: str) -> float:
    try:
        info = client.exchange_info()
        for s in info["symbols"]:
            if s["symbol"] == symbol:
                for f in s["filters"]:
                    if f["filterType"] == "LOT_SIZE":
                        return float(f["stepSize"])
    except Exception:
        pass
    return 0.001


def _place_market(client: UMFutures, symbol: str, side: str,
                  qty: float) -> Optional[Dict]:
    try:
        resp = client.new_order(
            symbol    = symbol,
            side      = side,
            type      = "MARKET",
            quantity  = qty,
            timestamp = int(datetime.now().timestamp() * 1000),
        )
        return resp
    except ClientError as e:
        logger.error(f"Market order error: {e}")
        return None


def _place_stop_market(client: UMFutures, symbol: str, side: str,
                       qty: float, stop_price: float) -> Optional[Dict]:
    """Place a STOP_MARKET order as the protective stop loss."""
    try:
        resp = client.new_order(
            symbol       = symbol,
            side         = side,
            type         = "STOP_MARKET",
            quantity     = qty,
            stopPrice    = round(stop_price, 2),
            closePosition= "false",
            timestamp    = int(datetime.now().timestamp() * 1000),
        )
        return resp
    except ClientError as e:
        logger.error(f"Stop-market order error: {e}")
        return None


def _cancel_order(client: UMFutures, symbol: str, order_id: int):
    try:
        client.cancel_order(symbol=symbol, orderId=order_id,
                            timestamp=int(datetime.now().timestamp() * 1000))
    except Exception as e:
        logger.warning(f"Could not cancel order {order_id}: {e}")


def _get_order_status(client: UMFutures, symbol: str, order_id: int) -> Optional[str]:
    try:
        resp = client.query_order(
            symbol    = symbol,
            orderId   = order_id,
            timestamp = int(datetime.now().timestamp() * 1000),
        )
        return resp.get("status")
    except Exception:
        return None


def _get_current_price(client: UMFutures, symbol: str) -> float:
    try:
        return float(client.ticker_price(symbol=symbol)["price"])
    except Exception:
        return 0.0


def _make_funding_fn(client: UMFutures):
    def get_funding_rate(symbol: str) -> float:
        info = client.mark_price(symbol=symbol)
        return float(info.get("lastFundingRate", 0))
    return get_funding_rate


# ── Position monitor ──────────────────────────────────────────────────────────

class OpenPosition:
    """Tracks one live position."""
    def __init__(self, trade_id: int, signal: Signal, qty: float,
                 entry_fill: float, sl_order_id: int):
        self.trade_id     = trade_id
        self.signal       = signal
        self.qty          = qty
        self.entry_fill   = entry_fill
        self.sl_order_id  = sl_order_id
        self.current_stop = signal.stop_loss
        self.opened_at    = datetime.utcnow()


# ── Strategy engine ───────────────────────────────────────────────────────────

class StrategyEngine:

    def __init__(self, symbols: List[str],
                 primary_tf: str = "5m",
                 confirm_tf: str = "1h",
                 scan_interval: int = 60):
        self.symbols       = [s.upper() for s in symbols]
        self.primary_tf    = primary_tf
        self.confirm_tf    = confirm_tf
        self.scan_interval = scan_interval

        self.client    = _make_client()
        self.tracker   = TradeTracker()
        self.risk      = RiskManager()
        self.notifier  = TelegramNotifier()
        self.signals   = SignalEngine(_make_klines_fn(self.client), _make_funding_fn(self.client))
        self.positions: Dict[str, OpenPosition] = {}   # symbol → position

    # ── main loop ────────────────────────────────────────────────────────────

    def run(self):
        logger.info(
            f"Strategy engine starting | symbols={self.symbols} "
            f"primary={self.primary_tf} confirm={self.confirm_tf} "
            f"scan_interval={self.scan_interval}s"
        )
        self.notifier.send_async(
            f"*Bot Started*\nSymbols: `{', '.join(self.symbols)}`\n"
            f"TF: `{self.primary_tf}` / `{self.confirm_tf}`"
        )

        try:
            while True:
                self._cycle()
                time.sleep(self.scan_interval)
        except KeyboardInterrupt:
            logger.info("Strategy engine stopped by user")
            self.notifier.send_async("*Bot Stopped* (KeyboardInterrupt)")

    def _cycle(self):
        equity = _get_equity(self.client)
        self.risk.update_equity(equity)

        # 1. Monitor existing positions
        for sym in list(self.positions.keys()):
            self._monitor_position(sym, equity)

        # 2. Scan for new signals
        if not self.risk.is_trading_allowed():
            return

        sigs = self.signals.scan_symbols(
            self.symbols, self.primary_tf, self.confirm_tf)

        for sig in sigs:
            if sig.symbol not in self.positions:
                self._enter_trade(sig, equity)

    # ── Entry logic ──────────────────────────────────────────────────────────

    def _enter_trade(self, sig: Signal, equity: float):
        if not self.risk.is_trading_allowed():
            return

        step_size = _get_step_size(self.client, sig.symbol)
        size = self.risk.compute_position_size(
            equity       = equity,
            entry_price  = sig.price,
            stop_price   = sig.stop_loss,
            take_profit  = sig.take_profit,
            step_size    = step_size,
        )
        if size is None:
            return
        size.symbol = sig.symbol

        entry_side = "BUY"  if sig.direction == SignalDirection.LONG  else "SELL"
        stop_side  = "SELL" if sig.direction == SignalDirection.LONG  else "BUY"

        # Place entry
        fill = _place_market(self.client, sig.symbol, entry_side, size.quantity)
        if not fill:
            logger.error(f"Entry order failed for {sig.symbol}")
            return

        # Testnet returns avgPrice="0" — fall back to live ticker price
        _avg = float(fill.get("avgPrice") or 0)
        if _avg == 0:
            try:
                _avg = float(self.client.ticker_price(symbol=sig.symbol)["price"])
            except Exception:
                _avg = sig.price
        avg_fill = _avg
        order_id = str(fill.get("orderId", ""))

        # Recalculate stops from actual fill
        if sig.direction == SignalDirection.LONG:
            actual_sl = avg_fill - sig.atr * 1.6
            actual_tp = avg_fill + sig.atr * 2.8
        else:
            actual_sl = avg_fill + sig.atr * 1.6
            actual_tp = avg_fill - sig.atr * 2.8

        # Place protective stop
        sl_resp = _place_stop_market(
            self.client, sig.symbol, stop_side, size.quantity, actual_sl)
        sl_order_id = int(sl_resp["orderId"]) if sl_resp else -1

        # Record in trade tracker
        trade_id = self.tracker.open_trade(
            symbol      = sig.symbol,
            direction   = sig.direction.value,
            entry_price = avg_fill,
            stop_loss   = actual_sl,
            take_profit = actual_tp,
            quantity    = size.quantity,
            order_id    = order_id,
        )

        self.risk.record_trade_open()

        pos = OpenPosition(
            trade_id    = trade_id,
            signal      = sig,
            qty         = size.quantity,
            entry_fill  = avg_fill,
            sl_order_id = sl_order_id,
        )
        pos.current_stop = actual_sl
        self.positions[sig.symbol] = pos

        self.notifier.signal_alert(
            sig.symbol, sig.direction.value,
            avg_fill, actual_sl, actual_tp,
            sig.confidence, sig.reasons,
        )
        self.notifier.order_filled(
            sig.symbol, entry_side, size.quantity, avg_fill, order_id)

        logger.info(
            f"ENTERED {sig.direction.value} {sig.symbol} @ {avg_fill} "
            f"SL={actual_sl:.4f} TP={actual_tp:.4f} qty={size.quantity}"
        )

    # ── Position monitoring ───────────────────────────────────────────────────

    def _monitor_position(self, symbol: str, equity: float):
        pos    = self.positions[symbol]
        price  = _get_current_price(self.client, symbol)
        if price == 0:
            return

        direction = pos.signal.direction
        sig       = pos.signal

        # Recalc trailing stop
        new_stop = self.risk.trailing_stop(
            entry_price   = pos.entry_fill,
            current_price = price,
            current_stop  = pos.current_stop,
            atr           = sig.atr,
            direction     = direction.value,
        )
        if new_stop != pos.current_stop:
            # Update the SL order if it improved
            if pos.sl_order_id > 0:
                _cancel_order(self.client, symbol, pos.sl_order_id)
            exit_side  = "SELL" if direction == SignalDirection.LONG else "BUY"
            sl_resp    = _place_stop_market(
                self.client, symbol, exit_side, pos.qty, new_stop)
            if sl_resp:
                pos.sl_order_id = int(sl_resp["orderId"])
                pos.current_stop = new_stop
                logger.info(f"[{symbol}] Trailing stop updated → {new_stop:.4f}")

        # Check if TP reached
        tp_hit = (
            (direction == SignalDirection.LONG  and price >= sig.take_profit) or
            (direction == SignalDirection.SHORT and price <= sig.take_profit)
        )
        sl_hit = (
            (direction == SignalDirection.LONG  and price <= pos.current_stop) or
            (direction == SignalDirection.SHORT and price >= pos.current_stop)
        )

        if tp_hit or sl_hit:
            reason = "TP" if tp_hit else "SL"
            self._close_position(symbol, price, reason, equity)

        # Also check if SL order was filled externally
        elif pos.sl_order_id > 0:
            status = _get_order_status(self.client, symbol, pos.sl_order_id)
            if status == "FILLED":
                self._close_position(symbol, pos.current_stop, "SL", equity)

    def _close_position(self, symbol: str, exit_price: float,
                        reason: str, equity: float):
        pos = self.positions.pop(symbol, None)
        if not pos:
            return

        direction  = pos.signal.direction
        exit_side  = "SELL" if direction == SignalDirection.LONG else "BUY"

        # Cancel any open SL order
        if pos.sl_order_id > 0:
            _cancel_order(self.client, symbol, pos.sl_order_id)

        # Place closing market order
        _place_market(self.client, symbol, exit_side, pos.qty)

        # Record close
        record = self.tracker.close_trade(pos.trade_id, exit_price, reason)
        pnl     = record.pnl     if record else 0.0
        pnl_pct = record.pnl_pct if record else 0.0

        self.risk.record_trade_close(pnl, equity)

        self.notifier.trade_closed(symbol, direction.value, pnl, pnl_pct)

        logger.info(
            f"CLOSED {direction.value} {symbol} @ {exit_price} "
            f"reason={reason} PnL={pnl:+.4f} ({pnl_pct:+.2f}%)"
        )

    # ── Status / reporting ────────────────────────────────────────────────────

    def print_stats(self):
        stats = self.tracker.get_stats()
        print("\n" + "="*50)
        print("PERFORMANCE STATS (All Time)")
        print("="*50)
        print(f"  Total trades   : {stats['total_trades']}")
        print(f"  Win rate       : {stats['win_rate']}%")
        print(f"  Total PnL      : {stats['total_pnl']:.4f} USDT")
        print(f"  Avg PnL/trade  : {stats['avg_pnl']:.4f} USDT")
        print(f"  Avg R:R        : {stats['avg_rr']:.2f}")
        print(f"  Max Drawdown   : {stats['max_drawdown_pct']:.2f}%")
        print(f"  Profit Factor  : {stats['profit_factor']:.2f}")
        print("="*50 + "\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Autonomous strategy engine for Binance Futures",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python strategy_engine.py --symbols BTCUSDT ETHUSDT
  python strategy_engine.py --symbols BTCUSDT --primary 15m --confirm 4h --scan 120
  python strategy_engine.py --stats      # show stats and exit
        """,
    )
    parser.add_argument("--symbols",  nargs="+", default=["BTCUSDT"],
                        help="Symbols to trade (default: BTCUSDT)")
    parser.add_argument("--primary",  default="5m",
                        help="Primary (entry) timeframe (default: 5m)")
    parser.add_argument("--confirm",  default="1h",
                        help="Confirmation (trend) timeframe (default: 1h)")
    parser.add_argument("--scan",     type=int, default=60,
                        help="Scan interval in seconds (default: 60)")
    parser.add_argument("--stats",    action="store_true",
                        help="Print stats and exit without trading")

    args = parser.parse_args()

    engine = StrategyEngine(
        symbols       = args.symbols,
        primary_tf    = args.primary,
        confirm_tf    = args.confirm,
        scan_interval = args.scan,
    )

    if args.stats:
        engine.print_stats()
        return

    engine.run()


if __name__ == "__main__":
    main()
