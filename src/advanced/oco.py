"""
Simulated OCO for Binance USD-M Futures testnet.

Binance Futures testnet only supports LIMIT and MARKET order types.
STOP, STOP_MARKET, TAKE_PROFIT_MARKET all return -4120 on testnet.

Strategy:
  Leg 1 (TP): LIMIT order at take-profit price   — placed immediately
  Leg 2 (SL): Background thread watches mark price; when stop_price is hit,
               cancels the TP leg and fires a MARKET order as SL.

One leg cancels the other when triggered.
"""
import os
import sys
import logging
import threading
import time
from dotenv import load_dotenv
from binance.um_futures import UMFutures
from binance.error import ClientError

logger = logging.getLogger(__name__)


class BinanceOCOBot:

    def __init__(self, log_path="logs/bot.log"):
        load_dotenv()
        self.api_key = os.getenv("BINANCE_API_KEY")
        self.secret_key = os.getenv("BINANCE_SECRET_KEY")

        if not self.api_key or not self.secret_key:
            logger.critical("API Key or Secret Key not found in .env file.")
            sys.exit(1)

        use_testnet = os.getenv("USE_TESTNET", "true").lower() == "true"
        base_url = "https://testnet.binancefuture.com" if use_testnet else "https://fapi.binance.com"

        try:
            self.client = UMFutures(key=self.api_key, secret=self.secret_key, base_url=base_url)
            self.client.account()
        except Exception as e:
            logger.critical(f"Failed to connect to Binance Futures API: {e}")
            sys.exit(1)

    def place_oco_order(self, symbol, side, quantity, price, stop_price,
                        stop_limit_price=None, dry_run=False):
        symbol = symbol.upper()
        side = side.upper()

        if side not in ("BUY", "SELL"):
            raise ValueError("Side must be BUY or SELL.")
        for name, val in [("quantity", quantity), ("price", price), ("stop_price", stop_price)]:
            if val <= 0:
                raise ValueError(f"{name} must be a positive value.")

        if dry_run:
            logger.info(f"[Dry Run] OCO {side} {symbol} qty={quantity} tp={price} sl={stop_price}")
            return {"dry_run": True, "tp_price": price, "sl_price": stop_price}

        # Leg 1: TP as a LIMIT order (works on testnet)
        try:
            tp = self.client.new_order(
                symbol=symbol,
                side=side,
                type="LIMIT",
                quantity=quantity,
                price=str(price),
                timeInForce="GTC",
            )
        except ClientError as e:
            logger.error(f"OCO TP leg failed: {e}")
            raise

        tp_order_id = tp.get("orderId")
        logger.info(f"OCO TP leg placed — orderId={tp_order_id} price={price}")

        # Leg 2: Background SL monitor — watches price, fires MARKET if stop hit
        t = threading.Thread(
            target=self._monitor_sl,
            args=(symbol, side, quantity, stop_price, tp_order_id),
            daemon=True,
        )
        t.start()
        logger.info(f"OCO SL monitor started — watching for {symbol} to hit {stop_price}")

        return [
            {"leg": "take_profit", "orderId": tp_order_id, "type": "LIMIT", "price": price},
            {"leg": "stop_loss",   "orderId": None,        "type": "MARKET_MONITORED", "stopPrice": stop_price},
        ]

    def _monitor_sl(self, symbol, side, quantity, stop_price, tp_order_id,
                    poll_interval=5, timeout=3600):
        """
        Background thread: polls mark price every poll_interval seconds.
        If price crosses stop_price, cancels TP and fires a MARKET order.
        Exits when TP fills, SL fires, or timeout is reached.
        """
        # For a SELL bracket (closing LONG): SL triggers when price DROPS to stop_price
        # For a BUY  bracket (closing SHORT): SL triggers when price RISES to stop_price
        sell_side = side == "SELL"
        deadline = time.time() + timeout

        logger.info(f"SL monitor running: {symbol} stop={stop_price} direction={'drop' if sell_side else 'rise'}")

        while time.time() < deadline:
            try:
                # Check if TP already filled or cancelled
                tp_status = self.client.query_order(symbol=symbol, orderId=tp_order_id)
                if tp_status.get("status") in ("FILLED", "CANCELED", "EXPIRED", "REJECTED"):
                    logger.info(f"OCO TP order {tp_order_id} is {tp_status['status']} — SL monitor exiting")
                    return

                # Get current mark price
                mark = float(self.client.mark_price(symbol=symbol)["markPrice"])

                sl_hit = (sell_side and mark <= stop_price) or (not sell_side and mark >= stop_price)

                if sl_hit:
                    logger.info(f"OCO SL triggered: mark={mark} crossed stop={stop_price}")
                    # Cancel TP leg
                    try:
                        self.client.cancel_order(symbol=symbol, orderId=tp_order_id)
                        logger.info(f"OCO TP leg {tp_order_id} cancelled")
                    except Exception as ce:
                        logger.warning(f"Could not cancel TP leg {tp_order_id}: {ce}")

                    # Fire MARKET SL order
                    try:
                        sl_result = self.client.new_order(
                            symbol=symbol,
                            side=side,
                            type="MARKET",
                            quantity=quantity,
                        )
                        logger.info(f"OCO SL MARKET fired — orderId={sl_result.get('orderId')}")
                    except Exception as me:
                        logger.error(f"OCO SL MARKET order failed: {me}")
                    return

            except Exception as e:
                logger.error(f"SL monitor error: {e}")

            time.sleep(poll_interval)

        logger.warning(f"OCO SL monitor timed out after {timeout}s — stopping")
