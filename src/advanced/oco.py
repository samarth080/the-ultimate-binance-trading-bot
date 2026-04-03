from binance.client import Client
from dotenv import load_dotenv
import os
import logging
import sys

class BinanceOCOBot:
    def __init__(self, log_path='logs/bot.log'):
        # Load environment variables first
        load_dotenv()
        self.api_key = os.getenv("BINANCE_API_KEY")
        self.secret_key = os.getenv("BINANCE_SECRET_KEY")

        # Setup logging and assign logger
        self._setup_logging(log_path)
        self.logger = logging.getLogger(__name__)

        # Validate keys
        if not self.api_key or not self.secret_key:
            self.logger.critical("❌ API Key or Secret Key not found in .env file.")
            sys.exit(1)

        # Create Binance client
        self.client = self._create_client()

    def _setup_logging(self, log_path):
        logging.basicConfig(
            level=logging.INFO,
            format='[%(asctime)s] %(levelname)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            handlers=[
                logging.FileHandler(log_path),
                logging.StreamHandler()
            ]
        )

    def _create_client(self):
        try:
            client = Client(self.api_key, self.secret_key)
            client.get_account()  # Test credentials
            return client
        except Exception as e:
            self.logger.critical("❌ Failed to connect to Binance API.", exc_info=True)
            sys.exit(1)

    def place_oco_order(self, symbol, side, quantity, price, stop_price, stop_limit_price, dry_run=False):
        symbol = symbol.upper()
        side = side.upper()

        # Input validation
        if side not in ["BUY", "SELL"]:
            self.logger.error(f"Invalid side: {side}")
            raise ValueError("Side must be BUY or SELL.")

        for name, val in zip(['quantity', 'price', 'stop_price', 'stop_limit_price'],
                             [quantity, price, stop_price, stop_limit_price]):
            if val <= 0:
                self.logger.error(f"{name} must be a positive value, got {val}")
                raise ValueError(f"{name} must be a positive value.")

        if dry_run:
            self.logger.info(f"[Dry Run] Would place OCO {side} order for {symbol}, Qty: {quantity}")
            print(f"[Dry Run] ✅ Simulated order for {symbol}, {side}, Qty: {quantity}")
            return

        try:
            order_func = self.client.order_oco_sell if side == "SELL" else self.client.order_oco_buy
            order = order_func(
                symbol=symbol,
                quantity=quantity,
                price=str(price),
                stopPrice=str(stop_price),
                stopLimitPrice=str(stop_limit_price),
                stopLimitTimeInForce='GTC'
            )
            self.logger.info(f"OCO {side} order placed successfully: {order}")
            print(f"✅ OCO {side} order placed successfully.")
            print(f"Order details:\n{order}")
        except Exception as e:
            self.logger.error(f"OCO order placement failed: {e}", exc_info=True)
            print(f"❌ Failed to place OCO order: {e}")