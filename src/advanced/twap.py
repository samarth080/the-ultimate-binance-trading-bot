"""
TWAP (Time-Weighted Average Price) Order Executor.

Splits a large order into equal child orders and spaces them out over a
defined time window to minimise market impact — exactly as production
bots like Hummingbot and institutional desks do.

Usage:
  python src/advanced/twap.py BTCUSDT BUY 0.1 --parts 5 --interval 60
"""

import os
import sys
import time
import logging
import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from dotenv import load_dotenv

# ── env / path setup ─────────────────────────────────────────────────────────
load_dotenv()
sys.path.insert(0, str(Path(__file__).parent.parent))

from binance.um_futures import UMFutures
from binance.error import ClientError, ServerError

# ── logging ──────────────────────────────────────────────────────────────────
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s [%(name)s]: %(message)s",
    handlers=[
        logging.FileHandler(log_dir / "twap.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("twap")


# ── helpers ──────────────────────────────────────────────────────────────────

def _align_qty(qty: float, step_size: float, min_qty: float) -> float:
    """Round qty down to the nearest valid step size."""
    if step_size <= 0:
        return qty
    aligned = round(int(qty / step_size) * step_size, 10)
    return max(aligned, min_qty)


def _get_lot_filters(client: UMFutures, symbol: str) -> Dict[str, float]:
    info = client.exchange_info()
    for s in info["symbols"]:
        if s["symbol"] == symbol:
            for f in s["filters"]:
                if f["filterType"] == "LOT_SIZE":
                    return {
                        "min_qty":   float(f["minQty"]),
                        "max_qty":   float(f["maxQty"]),
                        "step_size": float(f["stepSize"]),
                    }
    return {"min_qty": 0.0, "max_qty": 1e9, "step_size": 0.0}


# ── TWAP executor ─────────────────────────────────────────────────────────────

class TWAPExecutor:
    """
    Executes a TWAP strategy:
      1. Divides total_quantity into `parts` equal child slices.
      2. Places each slice as a MARKET order.
      3. Waits `interval_seconds` between slices.
      4. Handles step-size alignment and reports avg fill price.
    """

    def __init__(self, symbol: str, side: str, total_quantity: float,
                 parts: int, interval_seconds: int,
                 dry_run: bool = False):
        self.symbol           = symbol.upper()
        self.side             = side.upper()
        self.total_quantity   = total_quantity
        self.parts            = parts
        self.interval         = interval_seconds
        self.dry_run          = dry_run

        if self.side not in ("BUY", "SELL"):
            raise ValueError(f"Invalid side: {side}")
        if parts < 1:
            raise ValueError("parts must be ≥ 1")
        if total_quantity <= 0:
            raise ValueError("total_quantity must be > 0")

        api_key    = os.getenv("BINANCE_API_KEY")
        secret_key = os.getenv("BINANCE_SECRET_KEY")
        use_testnet = os.getenv("USE_TESTNET", "true").lower() == "true"
        base_url = ("https://testnet.binancefuture.com"
                    if use_testnet else "https://fapi.binance.com")

        if not api_key or not secret_key:
            raise EnvironmentError("BINANCE_API_KEY / BINANCE_SECRET_KEY not set")

        self.client = UMFutures(key=api_key, secret=secret_key, base_url=base_url)
        logger.info(f"TWAP executor init — {'TESTNET' if use_testnet else 'MAINNET'}")

        filters = _get_lot_filters(self.client, self.symbol)
        self.min_qty   = filters["min_qty"]
        self.max_qty   = filters["max_qty"]
        self.step_size = filters["step_size"]

    def _place_child(self, qty: float, child_num: int) -> Optional[Dict[str, Any]]:
        if self.dry_run:
            logger.info(f"[DRY-RUN] Child {child_num}: {self.side} {qty} {self.symbol}")
            return {"status": "DRY_RUN", "executedQty": str(qty), "avgPrice": "0"}

        try:
            resp = self.client.new_order(
                symbol    = self.symbol,
                side      = self.side,
                type      = "MARKET",
                quantity  = qty,
                timestamp = int(datetime.now().timestamp() * 1000),
            )
            logger.info(
                f"Child {child_num}: status={resp.get('status')} "
                f"execQty={resp.get('executedQty')} avgPrice={resp.get('avgPrice')}"
            )
            return resp
        except ClientError as e:
            logger.error(f"Child {child_num} ClientError: {e}")
        except ServerError as e:
            logger.error(f"Child {child_num} ServerError: {e}")
        except Exception as e:
            logger.error(f"Child {child_num} unexpected error: {e}")
        return None

    def execute(self) -> Dict[str, Any]:
        """
        Run the full TWAP execution.
        Returns a summary dict with fills, avg price, and completion rate.
        """
        base_qty  = _align_qty(self.total_quantity / self.parts,
                                self.step_size, self.min_qty)

        # Distribute rounding remainder across first child
        first_qty = _align_qty(
            self.total_quantity - base_qty * (self.parts - 1),
            self.step_size, self.min_qty
        )

        qtys = [first_qty] + [base_qty] * (self.parts - 1)
        qtys = [q for q in qtys if q >= self.min_qty]

        logger.info(
            f"TWAP START: {self.symbol} {self.side} total={self.total_quantity} "
            f"parts={len(qtys)} interval={self.interval}s"
        )

        fills: list     = []
        total_executed  = 0.0
        total_value     = 0.0
        failed_children = 0

        for i, qty in enumerate(qtys, start=1):
            resp = self._place_child(qty, i)

            if resp:
                exec_qty  = float(resp.get("executedQty", qty))
                avg_price = float(resp.get("avgPrice", 0) or 0)
                fills.append({"child": i, "qty": exec_qty, "avg_price": avg_price})
                total_executed += exec_qty
                total_value    += exec_qty * avg_price
            else:
                failed_children += 1

            if i < len(qtys):
                logger.info(f"Waiting {self.interval}s before child {i+1}...")
                time.sleep(self.interval)

        avg_fill_price = total_value / total_executed if total_executed > 0 else 0.0
        completion_pct = total_executed / self.total_quantity * 100

        summary = {
            "symbol":           self.symbol,
            "side":             self.side,
            "total_requested":  self.total_quantity,
            "total_executed":   round(total_executed, 8),
            "avg_fill_price":   round(avg_fill_price, 4),
            "completion_pct":   round(completion_pct, 2),
            "failed_children":  failed_children,
            "fills":            fills,
            "timestamp":        datetime.now().isoformat(),
        }

        logger.info(
            f"TWAP DONE: executed={total_executed}/{self.total_quantity} "
            f"avg_price={avg_fill_price:.4f} completion={completion_pct:.1f}%"
        )
        return summary


# ── CLI entry point ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="TWAP order executor for Binance Futures",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python twap.py BTCUSDT BUY 0.1 --parts 5 --interval 60
  python twap.py ETHUSDT SELL 1.0 --parts 10 --interval 30 --dry-run
        """,
    )
    parser.add_argument("symbol",   help="Trading pair, e.g. BTCUSDT")
    parser.add_argument("side",     choices=["BUY", "SELL", "buy", "sell"])
    parser.add_argument("quantity", type=float, help="Total quantity to execute")
    parser.add_argument("--parts",    type=int, default=5,  help="Number of child orders (default 5)")
    parser.add_argument("--interval", type=int, default=60, help="Seconds between orders (default 60)")
    parser.add_argument("--dry-run",  action="store_true",  help="Simulate without placing orders")

    args = parser.parse_args()

    try:
        executor = TWAPExecutor(
            symbol           = args.symbol,
            side             = args.side,
            total_quantity   = args.quantity,
            parts            = args.parts,
            interval_seconds = args.interval,
            dry_run          = args.dry_run,
        )
        summary = executor.execute()

        print("\n" + "="*55)
        print("TWAP EXECUTION SUMMARY")
        print("="*55)
        print(f"  Symbol      : {summary['symbol']}")
        print(f"  Side        : {summary['side']}")
        print(f"  Requested   : {summary['total_requested']}")
        print(f"  Executed    : {summary['total_executed']}")
        print(f"  Avg Price   : {summary['avg_fill_price']}")
        print(f"  Completion  : {summary['completion_pct']}%")
        print(f"  Failed slices: {summary['failed_children']}")
        print("="*55)

        sys.exit(0 if summary["failed_children"] == 0 else 1)

    except Exception as e:
        logger.error(f"TWAP execution failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
