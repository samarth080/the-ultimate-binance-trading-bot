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

class MarketOrderBot:
    
    def __init__(self, config_path: str = None):
        # Try multiple possible environment variable names
        self.api_key = (os.getenv("BINANCE_API_KEY") or 
                       os.getenv("API_KEY") or 
                       os.getenv("BINANCE_FUTURES_API_KEY"))
        
        self.secret_key = (os.getenv("BINANCE_SECRET_KEY") or 
                          os.getenv("SECRET_KEY") or 
                          os.getenv("API_SECRET") or 
                          os.getenv("BINANCE_SECRET") or
                          os.getenv("BINANCE_FUTURES_SECRET_KEY"))
        
        # Debug: Print what we found (partially masked)
        print(f"🔑 API Key found: {'✅' if self.api_key else '❌'}")
        print(f"🔐 Secret Key found: {'✅' if self.secret_key else '❌'}")
        
        if self.api_key:
            print(f"🔑 API Key (first 8 chars): {self.api_key[:8]}...")
        if self.secret_key:
            print(f"🔐 Secret Key (first 8 chars): {self.secret_key[:8]}...")
        
        if not self.api_key or not self.secret_key:
            print("\n❌ API credentials not found!")
            print("📋 Checked these environment variables:")
            print("   - BINANCE_API_KEY")
            print("   - API_KEY") 
            print("   - BINANCE_FUTURES_API_KEY")
            print("   - BINANCE_SECRET_KEY")
            print("   - SECRET_KEY")
            print("   - API_SECRET")
            print("   - BINANCE_SECRET")
            print("   - BINANCE_FUTURES_SECRET_KEY")
            print("\n📝 Please set the correct environment variables in your .env file:")
            print("BINANCE_API_KEY=your_api_key_here")
            print("BINANCE_SECRET_KEY=your_secret_key_here")
            raise ValueError("API credentials not found in environment variables")

        # Determine if we should use testnet
        use_testnet = os.getenv("USE_TESTNET", "true").lower() == "true"
        base_url = "https://testnet.binancefuture.com" if use_testnet else "https://fapi.binance.com"
        
        print(f"🌐 Using {'TESTNET' if use_testnet else 'MAINNET'}: {base_url}")

        try:
            self.client = UMFutures(
                key=self.api_key,
                secret=self.secret_key,
                base_url=base_url
            )
            print("✅ Binance client initialized successfully")
        except Exception as e:
            print(f"❌ Failed to initialize Binance client: {e}")
            raise

        self._setup_logging()
        self._symbol_info_cache = {}
        self.config = self._load_config(config_path) if config_path else None

    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load and validate JSON configuration"""
        try:
            with open(config_path) as f:
                config = json.load(f)
            
            # Basic validation
            if not isinstance(config, dict):
                raise ValueError("Config must be a JSON object")
                
            return config
            
        except FileNotFoundError:
            self.logger.error(f"Config file not found: {config_path}")
            raise
        except json.JSONDecodeError:
            self.logger.error(f"Invalid JSON in config file")
            raise
    
    def _setup_logging(self):
        log_dir = os.path.dirname(os.path.abspath(__file__))
        log_file = os.path.join(log_dir, 'logs', 'bot.log')
        
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
        self.logger.info("MarketOrderBot initialized")

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
                    
                    if step_size > 0:
                        steps = (quantity - min_qty) / step_size
                        if abs(steps - round(steps)) > 1e-6:
                            self.logger.error(f"Quantity {quantity} doesn't match step size {step_size}")
                            return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error validating quantity for {symbol}: {e}")
            return False

    def get_account_balance(self) -> Optional[Dict[str, Any]]:
        try:
            account_info = self.client.account()
            return account_info
        except Exception as e:
            self.logger.error(f"Error getting account balance: {e}")
            return None

    def place_market_order(self, symbol: str, side: str, quantity: float) -> Optional[Dict[str, Any]]:
        symbol = symbol.upper()
        side = side.upper()
        
        self.logger.info(f"Attempting to place MARKET {side} order: {symbol} qty={quantity}")
        
        if side not in ["BUY", "SELL"]:
            self.logger.error(f"Invalid side: {side}. Must be BUY or SELL")
            return None
        
        if not self.validate_symbol(symbol):
            self.logger.error(f"Symbol validation failed for {symbol}")
            return None
        
        if not self.validate_quantity(symbol, quantity):
            self.logger.error(f"Quantity validation failed for {symbol} qty={quantity}")
            return None
        
        account_info = self.get_account_balance()
        if account_info:
            self.logger.info(f"Account balance check completed")
        
        try:
            response = self.client.new_order(
                symbol=symbol,
                side=side,
                type="MARKET",
                quantity=quantity,
                timestamp=int(datetime.now().timestamp() * 1000)
            )
            
            self.logger.info(f"✅ MARKET {side} order placed successfully: {response}")
            
            order_id = response.get('orderId', 'N/A')
            status = response.get('status', 'N/A')
            executed_qty = response.get('executedQty', 'N/A')
            
            self.logger.info(f"Order Details - ID: {order_id}, Status: {status}, Executed: {executed_qty}")
            
            return response
            
        except ClientError as e:
            self.logger.error(f"❌ Client error placing order: {e}")
            return None
        except ServerError as e:
            self.logger.error(f"❌ Server error placing order: {e}")
            return None
        except Exception as e:
            self.logger.error(f"❌ Unexpected error placing order: {e}")
            return None

    def execute_from_config(self) -> bool:
        """Execute orders from config file"""
        if not self.config:
            self.logger.error("No configuration loaded")
            return False

        success = True
        for order in self.config.get('orders', []):
            if order.get('type', '').lower() == 'market':
                try:
                    result = self.place_market_order(
                        order['symbol'],
                        order['side'],
                        order['quantity']
                    )
                    if not result:
                        success = False
                except Exception as e:
                    self.logger.error(f"Failed to execute order: {e}")
                    success = False
        
        return success


def main():
    parser = argparse.ArgumentParser(
        description="Place market orders on Binance Futures",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python market_orders.py BTCUSDT BUY 0.01
  python market_orders.py ETHUSDT SELL 0.1
  python market_orders.py --config strategy.json
        """
    )
    
    # Mutually exclusive group for either single order or config file
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--config', help='Path to JSON config file')
    group.add_argument('symbol', nargs='?', help='Trading symbol (e.g., BTCUSDT)')
    
    parser.add_argument('side', nargs='?', choices=['BUY', 'SELL', 'buy', 'sell'], 
                       help='Order side (BUY or SELL)')
    parser.add_argument('quantity', nargs='?', type=float, help='Order quantity')
    
    parser.add_argument('--dry-run', action='store_true', 
                       help='Validate inputs without placing actual order')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Enable verbose logging')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        bot = MarketOrderBot(args.config if args.config else None)
        
        if args.dry_run:
            print("🔍 DRY RUN MODE - No actual orders will be placed")
            bot.logger.info("Running in DRY RUN mode")
            
            if args.config:
                # Validate all orders in config
                valid = True
                for order in bot.config.get('orders', []):
                    if order.get('type', '').lower() == 'market':
                        if not bot.validate_symbol(order['symbol'].upper()):
                            print(f"❌ Symbol {order['symbol']} is invalid")
                            valid = False
                        if not bot.validate_quantity(order['symbol'].upper(), order['quantity']):
                            print(f"❌ Quantity {order['quantity']} is invalid for {order['symbol']}")
                            valid = False
                print("✅ All validations passed!" if valid else "❌ Validation failed!")
                return 0 if valid else 1
            else:
                # Validate single order
                if bot.validate_symbol(args.symbol.upper()):
                    print(f"✅ Symbol {args.symbol.upper()} is valid")
                else:
                    print(f"❌ Symbol {args.symbol.upper()} is invalid")
                    return 1
                
                if bot.validate_quantity(args.symbol.upper(), args.quantity):
                    print(f"✅ Quantity {args.quantity} is valid")
                else:
                    print(f"❌ Quantity {args.quantity} is invalid")
                    return 1
                
                print("✅ All validations passed!")
                return 0
        
        if args.config:
            # Execute orders from config
            success = bot.execute_from_config()
            return 0 if success else 1
        else:
            # Execute single order
            result = bot.place_market_order(args.symbol, args.side, args.quantity)
            
            if result:
                print(f"✅ Order placed successfully!")
                print(f"Order ID: {result.get('orderId', 'N/A')}")
                print(f"Status: {result.get('status', 'N/A')}")
                print(f"Executed Quantity: {result.get('executedQty', 'N/A')}")
                return 0
            else:
                print("❌ Order placement failed. Check logs for details.")
                return 1
            
    except KeyboardInterrupt:
        print("\n⏸️  Operation cancelled by user")
        return 130
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        logging.error(f"Unexpected error in main: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())