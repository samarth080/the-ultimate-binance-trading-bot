import logging
import time
from typing import Dict, Any, Optional
from binance.client import Client
from binance.exceptions import BinanceAPIException
import json
from datetime import datetime

class StopLimitOrderHandler:
    def __init__(self, client: Client, logger: logging.Logger):
        self.client = client
        self.logger = logger
        
    def validate_stop_limit_params(self, symbol: str, side: str, quantity: float, stop_price: float, limit_price: float) -> bool:
        try:
            symbol_info = self.client.futures_exchange_info()
            symbol_data = None
            
            for s in symbol_info['symbols']:
                if s['symbol'] == symbol:
                    symbol_data = s
                    break
            
            if not symbol_data:
                self.logger.error(f"Invalid symbol: {symbol}")
                return False
            
            if side not in ['BUY', 'SELL']:
                self.logger.error(f"Invalid side: {side}. Must be BUY or SELL")
                return False
            
            lot_size_filter = next((f for f in symbol_data['filters'] if f['filterType'] == 'LOT_SIZE'), None)
            if lot_size_filter:
                min_qty = float(lot_size_filter['minQty'])
                max_qty = float(lot_size_filter['maxQty'])
                step_size = float(lot_size_filter['stepSize'])
                
                if quantity < min_qty or quantity > max_qty:
                    self.logger.error(f"Quantity {quantity} outside allowed range [{min_qty}, {max_qty}]")
                    return False
            
            price_filter = next((f for f in symbol_data['filters'] if f['filterType'] == 'PRICE_FILTER'), None)
            if price_filter:
                min_price = float(price_filter['minPrice'])
                max_price = float(price_filter['maxPrice'])
                tick_size = float(price_filter['tickSize'])
                
                if stop_price < min_price or stop_price > max_price:
                    self.logger.error(f"Stop price {stop_price} outside allowed range [{min_price}, {max_price}]")
                    return False
                
                if limit_price < min_price or limit_price > max_price:
                    self.logger.error(f"Limit price {limit_price} outside allowed range [{min_price}, {max_price}]")
                    return False
            
            if side == 'BUY':
                current_price = float(self.client.futures_symbol_ticker(symbol=symbol)['price'])
                if stop_price <= current_price:
                    self.logger.error(f"For BUY orders, stop price {stop_price} should be above current price {current_price}")
                    return False
                if limit_price <= stop_price:
                    self.logger.error(f"For BUY orders, limit price {limit_price} should be above stop price {stop_price}")
                    return False
            else:
                current_price = float(self.client.futures_symbol_ticker(symbol=symbol)['price'])
                if stop_price >= current_price:
                    self.logger.error(f"For SELL orders, stop price {stop_price} should be below current price {current_price}")
                    return False
                if limit_price >= stop_price:
                    self.logger.error(f"For SELL orders, limit price {limit_price} should be below stop price {stop_price}")
                    return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"Validation error: {str(e)}")
            return False
    
    def place_stop_limit_order(self, symbol: str, side: str, quantity: float, stop_price: float, limit_price: float, time_in_force: str = 'GTC') -> Optional[Dict[str, Any]]:
        order_data = {
            'symbol': symbol,
            'side': side,
            'quantity': quantity,
            'stop_price': stop_price,
            'limit_price': limit_price,
            'time_in_force': time_in_force,
            'timestamp': datetime.now().isoformat()
        }
        
        self.logger.info(f"Attempting to place stop-limit order: {json.dumps(order_data, indent=2)}")
        
        if not self.validate_stop_limit_params(symbol, side, quantity, stop_price, limit_price):
            return None
        
        try:
            order_response = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type='STOP',
                quantity=quantity,
                stopPrice=stop_price,
                price=limit_price,
                timeInForce=time_in_force
            )
            
            self.logger.info(f"Stop-limit order placed successfully: {json.dumps(order_response, indent=2)}")
            
            order_log = {
                'action': 'STOP_LIMIT_ORDER_PLACED',
                'order_id': order_response['orderId'],
                'symbol': symbol,
                'side': side,
                'quantity': quantity,
                'stop_price': stop_price,
                'limit_price': limit_price,
                'status': order_response['status'],
                'timestamp': datetime.now().isoformat()
            }
            
            self.logger.info(f"Order logged: {json.dumps(order_log, indent=2)}")
            
            return order_response
            
        except BinanceAPIException as e:
            error_msg = f"Binance API Error placing stop-limit order: {e.message} (Code: {e.code})"
            self.logger.error(error_msg)
            return None
            
        except Exception as e:
            error_msg = f"Unexpected error placing stop-limit order: {str(e)}"
            self.logger.error(error_msg)
            return None
    
    def monitor_stop_limit_order(self, symbol: str, order_id: int, check_interval: int = 5) -> Dict[str, Any]:
        self.logger.info(f"Starting to monitor stop-limit order {order_id} for {symbol}")
        
        while True:
            try:
                order_status = self.client.futures_get_order(symbol=symbol, orderId=order_id)
                
                status = order_status['status']
                self.logger.info(f"Order {order_id} status: {status}")
                
                if status in ['FILLED', 'CANCELED', 'REJECTED', 'EXPIRED']:
                    self.logger.info(f"Stop-limit order {order_id} final status: {status}")
                    
                    final_log = {
                        'action': 'STOP_LIMIT_ORDER_FINAL_STATUS',
                        'order_id': order_id,
                        'symbol': symbol,
                        'status': status,
                        'executed_qty': order_status.get('executedQty', 0),
                        'avg_price': order_status.get('avgPrice', 0),
                        'timestamp': datetime.now().isoformat()
                    }
                    
                    self.logger.info(f"Final order status logged: {json.dumps(final_log, indent=2)}")
                    return order_status
                
                time.sleep(check_interval)
                
            except BinanceAPIException as e:
                error_msg = f"Error monitoring order {order_id}: {e.message}"
                self.logger.error(error_msg)
                break
                
            except Exception as e:
                error_msg = f"Unexpected error monitoring order {order_id}: {str(e)}"
                self.logger.error(error_msg)
                break
        
        return {}
    
    def cancel_stop_limit_order(self, symbol: str, order_id: int) -> bool:
        try:
            cancel_response = self.client.futures_cancel_order(
                symbol=symbol,
                orderId=order_id
            )
            
            self.logger.info(f"Stop-limit order {order_id} cancelled successfully")
            
            cancel_log = {
                'action': 'STOP_LIMIT_ORDER_CANCELLED',
                'order_id': order_id,
                'symbol': symbol,
                'timestamp': datetime.now().isoformat()
            }
            
            self.logger.info(f"Cancellation logged: {json.dumps(cancel_log, indent=2)}")
            
            return True
            
        except BinanceAPIException as e:
            error_msg = f"Error cancelling order {order_id}: {e.message}"
            self.logger.error(error_msg)
            return False
            
        except Exception as e:
            error_msg = f"Unexpected error cancelling order {order_id}: {str(e)}"
            self.logger.error(error_msg)
            return False


def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('bot.log'),
            logging.StreamHandler()
        ]
    )
    
    logger = logging.getLogger(__name__)
    
    client = Client(
        api_key='your_api_key',
        api_secret='your_api_secret',
        testnet=True
    )
    
    stop_limit_handler = StopLimitOrderHandler(client, logger)
    
    order_response = stop_limit_handler.place_stop_limit_order(
        symbol='BTCUSDT',
        side='SELL',
        quantity=0.01,
        stop_price=65000.0,
        limit_price=64500.0
    )
    
    if order_response:
        order_id = order_response['orderId']
        
        final_status = stop_limit_handler.monitor_stop_limit_order(
            symbol='BTCUSDT',
            order_id=order_id
        )
        
        print(f"Order final status: {final_status.get('status', 'Unknown')}")


if __name__ == "__main__":
    main()
