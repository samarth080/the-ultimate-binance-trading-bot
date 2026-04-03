import os
import sys
import json
import argparse
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
from pathlib import Path

from binance.um_futures import UMFutures
from binance.error import ClientError, ServerError
from dotenv import load_dotenv, find_dotenv

from binance.um_futures import UMFutures
from binance.error import ClientError, ServerError
from dotenv import load_dotenv

# Multiple attempts to load .env file
def load_environment():
    """Load environment variables with multiple fallback options"""
    env_loaded = False
    
    # Method 1: Try to find .env automatically
    try:
        dotenv_path = find_dotenv()
        if dotenv_path:
            load_dotenv(dotenv_path)
            print(f"✅ Loaded .env from: {dotenv_path}")
            env_loaded = True
        else:
            print("⚠️  No .env file found automatically")
    except Exception as e:
        print(f"⚠️  Error with find_dotenv(): {e}")
    
    # Method 2: Try common locations
    if not env_loaded:
        possible_paths = [
            '.env',
            '../.env',
            '../../.env',
            os.path.join(os.path.dirname(__file__), '.env'),
            os.path.join(os.path.dirname(__file__), '..', '.env'),
            os.path.join(os.path.expanduser('~'), '.env')
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                try:
                    load_dotenv(path)
                    print(f"✅ Loaded .env from: {os.path.abspath(path)}")
                    env_loaded = True
                    break
                except Exception as e:
                    print(f"⚠️  Error loading {path}: {e}")
    
    # Method 3: Check if already loaded from system environment
    if not env_loaded:
        if os.getenv("BINANCE_API_KEY") or os.getenv("BINANCE_SECRET_KEY"):
            print("✅ Using environment variables from system")
            env_loaded = True
    
    if not env_loaded:
        print("❌ Could not load .env file from any location")
        print("📍 Current working directory:", os.getcwd())
        print("📍 Script directory:", os.path.dirname(os.path.abspath(__file__)))
        print("\n🔧 Please ensure your .env file exists in one of these locations:")
        for path in possible_paths:
            print(f"   - {os.path.abspath(path)}")
        
        print("\n📝 Your .env file should contain:")
        print("BINANCE_API_KEY=your_api_key_here")
        print("BINANCE_SECRET_KEY=your_secret_key_here")
        
        return False
    
    return True

# Load environment at module level
if not load_environment():
    print("\n❌ Failed to load environment variables. Exiting...")
    sys.exit(1)


class LimitOrderBot:
    
    def __init__(self):
        self.api_key = os.getenv("BINANCE_API_KEY")
        self.secret_key = os.getenv("BINANCE_SECRET_KEY")
        
        if not self.api_key or not self.secret_key:
            raise ValueError("API credentials not found. Please set BINANCE_API_KEY and BINANCE_SECRET_KEY in .env file")

        self.client = UMFutures(key=self.api_key, secret=self.secret_key)
        self._setup_logging()
        self._symbol_info_cache = {}
    
    def _setup_logging(self):
        log_dir = os.path.dirname(os.path.abspath(__file__))
        log_file = os.path.join(log_dir, '..', 'logs/bot.log')
        
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        
        logging.basicConfig(
            level=logging.INFO,
            format='[%(asctime)s] %(levelname)s [%(name)s]: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler(sys.stdout)
            ]
        )
        
        self.logger = logging.getLogger(__name__)
        self.logger.info("LimitOrderBot initialized")
    
    def validate_symbol(self, symbol: str) -> bool:

        try:
            if symbol in self._symbol_info_cache:
                return self._symbol_info_cache[symbol]['status'] == 'TRADING'
            
            exchange_info = self.client.exchange_info()
            
            for symbol_info in exchange_info['symbols']:
                if symbol_info['symbol'] == symbol:
                    self._symbol_info_cache[symbol] = symbol_info
                    is_trading = symbol_info['status'] == 'TRADING'
                    
                    if not is_trading:
                        self.logger.error(f"Symbol {symbol} is not in TRADING status: {symbol_info['status']}")
                    
                    return is_trading
            
            self.logger.error(f"Symbol {symbol} not found in exchange info")
            return False
            
        except Exception as e:
            self.logger.error(f"Error validating symbol {symbol}: {e}")
            return False
    
    def validate_quantity(self, symbol: str, quantity: float) -> bool:

        try:
            if quantity <= 0:
                self.logger.error(f"Invalid quantity: {quantity}. Must be positive")
                return False
            
            if symbol not in self._symbol_info_cache:
                if not self.validate_symbol(symbol):
                    return False
            
            symbol_info = self._symbol_info_cache[symbol]
            
 
            for filter_info in symbol_info['filters']:
                if filter_info['filterType'] == 'LOT_SIZE':
                    min_qty = float(filter_info['minQty'])
                    max_qty = float(filter_info['maxQty'])
                    step_size = float(filter_info['stepSize'])
                    
                    if quantity < min_qty:
                        self.logger.error(f"Quantity {quantity} below minimum {min_qty}")
                        return False
                    
                    if quantity > max_qty:
                        self.logger.error(f"Quantity {quantity} above maximum {max_qty}")
                        return False
                    
                    # Check step size
                    if step_size > 0:
                        steps = (quantity - min_qty) / step_size
                        if abs(steps - round(steps)) > 1e-6:
                            self.logger.error(f"Quantity {quantity} doesn't match step size {step_size}")
                            return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error validating quantity for {symbol}: {e}")
            return False
    
    def validate_price(self, symbol: str, price: float) -> bool:

        try:
            if price <= 0:
                self.logger.error(f"Invalid price: {price}. Must be positive")
                return False

            if symbol not in self._symbol_info_cache:
                if not self.validate_symbol(symbol):
                    return False
            
            symbol_info = self._symbol_info_cache[symbol]
            
            for filter_info in symbol_info['filters']:
                if filter_info['filterType'] == 'PRICE_FILTER':
                    min_price = float(filter_info['minPrice'])
                    max_price = float(filter_info['maxPrice'])
                    tick_size = float(filter_info['tickSize'])
                    
                    if price < min_price:
                        self.logger.error(f"Price {price} below minimum {min_price}")
                        return False
                    
                    if price > max_price:
                        self.logger.error(f"Price {price} above maximum {max_price}")
                        return False
                    
                    if tick_size > 0:
                        remainder = (price - min_price) % tick_size
                        if remainder != 0:
                            self.logger.error(f"Price {price} doesn't match tick size {tick_size}")
                            return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error validating price for {symbol}: {e}")
            return False
    
    def get_account_balance(self) -> Optional[Dict[str, Any]]:

        try:
            account_info = self.client.account()
            return account_info
        except Exception as e:
            self.logger.error(f"Error getting account balance: {e}")
            return None
    
    def place_limit_order(self, symbol: str, side: str, quantity: float, price: float) -> Optional[Dict[str, Any]]:

        symbol = symbol.upper()
        side = side.upper()
        
        self.logger.info(f"Attempting to place LIMIT {side} order: {symbol} qty={quantity} price={price}")
        

        if side not in ["BUY", "SELL"]:
            self.logger.error(f"Invalid side: {side}. Must be BUY or SELL")
            return None
 
        if not self.validate_symbol(symbol):
            self.logger.error(f"Symbol validation failed for {symbol}")
            return None
        
        if not self.validate_quantity(symbol, quantity):
            self.logger.error(f"Quantity validation failed for {symbol} qty={quantity}")
            return None
        
        if not self.validate_price(symbol, price):
            self.logger.error(f"Price validation failed for {symbol} price={price}")
            return None

        account_info = self.get_account_balance()
        if account_info:
            self.logger.info(f"Account balance check completed")
        
        try:

            response = self.client.new_order(
                symbol=symbol,
                side=side,
                type="LIMIT",
                quantity=quantity,
                price=str(price),
                timeInForce="GTC",
                timestamp=int(datetime.now().timestamp() * 1000)
            )
            
            self.logger.info(f"✅ LIMIT {side} order placed successfully: {response}")
            

            order_id = response.get('orderId', 'N/A')
            status = response.get('status', 'N/A')
            orig_qty = response.get('origQty', 'N/A')
            
            self.logger.info(f"Order Details - ID: {order_id}, Status: {status}, Quantity: {orig_qty}")
            
            return response
            
        except ClientError as e:
            self.logger.error(f"  Client error placing order: {e}")
            return None
        except ServerError as e:
            self.logger.error(f" Server error placing order: {e}")
            return None
        except Exception as e:
            self.logger.error(f" Unexpected error placing order: {e}")
            return None


def main():
    parser = argparse.ArgumentParser(
        description="Place limit orders on Binance Futures",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python limit_orders.py BTCUSDT BUY 0.01 50000
  python limit_orders.py ETHUSDT SELL 0.1 3000
        """
    )
    
    parser.add_argument('symbol', help='Trading symbol (e.g., BTCUSDT)')
    parser.add_argument('side', choices=['BUY', 'SELL', 'buy', 'sell'], 
                       help='Order side (BUY or SELL)')
    parser.add_argument('quantity', type=float, help='Order quantity')
    parser.add_argument('price', type=float, help='Order price')


    parser.add_argument('--dry-run', action='store_true', 
                       help='Validate inputs without placing actual order')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Enable verbose logging')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        bot = LimitOrderBot()
        
        if args.dry_run:
            print(" DRY RUN MODE - No actual orders will be placed")
            bot.logger.info("Running in DRY RUN mode")
            
            if bot.validate_symbol(args.symbol.upper()):
                print(f" Symbol {args.symbol.upper()} is valid")
            else:
                print(f" Symbol {args.symbol.upper()} is invalid")
                return 1
            
            if bot.validate_quantity(args.symbol.upper(), args.quantity):
                print(f" Quantity {args.quantity} is valid")
            else:
                print(f" Quantity {args.quantity} is invalid")
                return 1
            
            if bot.validate_price(args.symbol.upper(), args.price):
                print(f"Price {args.price} is valid")
            else:
                print(f" Price {args.price} is invalid")
                return 1
            
            print(" All validations passed!")
            return 0
        
        result = bot.place_limit_order(args.symbol, args.side, args.quantity, args.price)
        
        if result:
            print(f"Limit order placed successfully!")
            print(f"Order ID: {result.get('orderId', 'N/A')}")
            print(f"Status: {result.get('status', 'N/A')}")
            print(f"Quantity: {result.get('origQty', 'N/A')}")
            print(f"Price: {result.get('price', 'N/A')}")
            return 0
        else:
            print(" Order placement failed. Check logs for details.")
            return 1
            
    except KeyboardInterrupt:
        print("\n  Operation cancelled by user")
        return 130
    except Exception as e:
        print(f" Unexpected error: {e}")
        logging.error(f"Unexpected error in main: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())