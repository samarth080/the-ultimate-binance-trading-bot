import logging
import time
import json
from datetime import datetime
from typing import Dict, Any, Optional

from binance.um_futures import UMFutures
from binance.error import ClientError


class StopLimitOrderHandler:
    """Stop-Limit order handler for Binance USD-M Futures (UMFutures client)."""

    def __init__(self, client: UMFutures, logger: logging.Logger):
        self.client = client
        self.logger = logger

    def validate_stop_limit_params(self, symbol: str, side: str, quantity: float,
                                   stop_price: float, limit_price: float) -> bool:
        try:
            exchange_info = self.client.exchange_info()
            symbol_data = next(
                (s for s in exchange_info["symbols"] if s["symbol"] == symbol), None
            )
            if not symbol_data:
                self.logger.error(f"Invalid symbol: {symbol}")
                return False

            if side not in ("BUY", "SELL"):
                self.logger.error(f"Invalid side: {side}")
                return False

            lot = next((f for f in symbol_data["filters"] if f["filterType"] == "LOT_SIZE"), None)
            if lot:
                min_qty = float(lot["minQty"])
                max_qty = float(lot["maxQty"])
                if not (min_qty <= quantity <= max_qty):
                    self.logger.error(f"Quantity {quantity} outside [{min_qty}, {max_qty}]")
                    return False

            pf = next((f for f in symbol_data["filters"] if f["filterType"] == "PRICE_FILTER"), None)
            if pf:
                min_p = float(pf["minPrice"])
                max_p = float(pf["maxPrice"])
                if not (min_p <= stop_price <= max_p):
                    self.logger.error(f"Stop price {stop_price} outside [{min_p}, {max_p}]")
                    return False
                if not (min_p <= limit_price <= max_p):
                    self.logger.error(f"Limit price {limit_price} outside [{min_p}, {max_p}]")
                    return False

            current_price = float(self.client.ticker_price(symbol=symbol)["price"])
            if side == "BUY":
                if stop_price <= current_price:
                    self.logger.error(
                        f"BUY stop {stop_price} must be above current {current_price}"
                    )
                    return False
                if limit_price <= stop_price:
                    self.logger.error(
                        f"BUY limit {limit_price} must be above stop {stop_price}"
                    )
                    return False
            else:  # SELL
                if stop_price >= current_price:
                    self.logger.error(
                        f"SELL stop {stop_price} must be below current {current_price}"
                    )
                    return False
                if limit_price >= stop_price:
                    self.logger.error(
                        f"SELL limit {limit_price} must be below stop {stop_price}"
                    )
                    return False

            return True

        except Exception as e:
            self.logger.error(f"Validation error: {e}")
            return False

    def place_stop_limit_order(self, symbol: str, side: str, quantity: float,
                               stop_price: float, limit_price: float,
                               time_in_force: str = "GTC") -> Optional[Dict[str, Any]]:
        self.logger.info(
            f"Placing STOP order: {symbol} {side} qty={quantity} "
            f"stop={stop_price} limit={limit_price}"
        )

        if not self.validate_stop_limit_params(symbol, side, quantity, stop_price, limit_price):
            return None

        try:
            order = self.client.new_order(
                symbol=symbol,
                side=side,
                type="STOP",
                quantity=quantity,
                stopPrice=str(stop_price),
                price=str(limit_price),
                timeInForce=time_in_force,
            )
            self.logger.info(f"Stop-limit order placed: orderId={order['orderId']} status={order['status']}")
            return order

        except ClientError as e:
            self.logger.error(f"Binance error placing stop-limit: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error placing stop-limit: {e}")
            return None

    def monitor_stop_limit_order(self, symbol: str, order_id: int,
                                 check_interval: int = 5) -> Dict[str, Any]:
        self.logger.info(f"Monitoring stop-limit order {order_id} for {symbol}")
        while True:
            try:
                status_resp = self.client.query_order(symbol=symbol, orderId=order_id)
                status = status_resp["status"]
                self.logger.info(f"Order {order_id} status: {status}")
                if status in ("FILLED", "CANCELED", "REJECTED", "EXPIRED"):
                    return status_resp
                time.sleep(check_interval)
            except ClientError as e:
                self.logger.error(f"Error monitoring order {order_id}: {e}")
                break
            except Exception as e:
                self.logger.error(f"Unexpected error monitoring order {order_id}: {e}")
                break
        return {}

    def cancel_stop_limit_order(self, symbol: str, order_id: int) -> bool:
        try:
            self.client.cancel_order(symbol=symbol, orderId=order_id)
            self.logger.info(f"Stop-limit order {order_id} cancelled")
            return True
        except ClientError as e:
            self.logger.error(f"Error cancelling order {order_id}: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error cancelling order {order_id}: {e}")
            return False
