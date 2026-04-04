import argparse
import subprocess
import logging
import sys
import os
from typing import Dict, List, Optional
from pathlib import Path
from dotenv import load_dotenv
import time
from datetime import datetime

# ── new engine imports (graceful fallback if pandas not installed) ────────────
try:
    from signal_engine import SignalEngine, analyse_timeframe
    SIGNAL_ENGINE_AVAILABLE = True
except ImportError:
    SIGNAL_ENGINE_AVAILABLE = False

# Load environment variables early
load_dotenv()

"""
Enhanced Binance CLI Bot
- Supports market, limit, oco, stop-limit, twap orders
- Tracks crypto with multiple ML indicators (SMA, EMA, RSI, MACD, BB)
- Includes config validation and structured logging
"""

# Import required libraries with fallbacks
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    print("Warning: pandas not installed. ML tracking will be limited.")

try:
    from binance.um_futures import UMFutures
    BINANCE_AVAILABLE = True
except ImportError:
    BINANCE_AVAILABLE = False
    print("Warning: python-binance not installed. ML tracking will not work.")

# Setup enhanced logging configuration
def setup_logging():
    """Setup comprehensive logging with rotation and better formatting."""
    log_format = '[%(asctime)s] %(name)s - %(levelname)s: %(message)s'
    
    # Create logs directory if it doesn't exist
    log_dir = Path('logs')
    log_dir.mkdir(exist_ok=True)
    
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.FileHandler(log_dir / 'bot.log'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()


# Enhanced order scripts mapping with validation
ORDER_SCRIPTS = {
    'market':     'market_orders.py',
    'limit':      'limit_orders.py',
    'oco':        Path('Advanced') / 'oco.py',
    'stop_limit': Path('Advanced') / 'stop_limit_orders.py',
    'twap':       Path('advanced')  / 'twap.py',
}

class BinanceBotError(Exception):
    """Custom exception for bot-related errors."""
    pass

class ConfigValidator:
    """Validates bot configuration and environment."""
    
    @staticmethod
    def validate_environment() -> bool:
        """Validate required environment variables."""
        required_vars = ['BINANCE_API_KEY', 'BINANCE_SECRET_KEY']
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        
        if missing_vars:
            logger.error(f"Missing environment variables: {', '.join(missing_vars)}")
            return False
        return True
    
    @staticmethod
    def validate_scripts() -> Dict[str, bool]:
        """Validate that all order scripts exist."""
        script_status = {}
        for order_type, script_path in ORDER_SCRIPTS.items():
            script_exists = Path(script_path).exists()
            script_status[order_type] = script_exists
            if not script_exists:
                logger.warning(f"Script not found: {script_path}")
        return script_status

class MLTracker:
    """Enhanced ML-based crypto tracking with multiple indicators."""
    
    def __init__(self):
        if not BINANCE_AVAILABLE:
            raise BinanceBotError("python-binance library not available")
        if not PANDAS_AVAILABLE:
            raise BinanceBotError("pandas library not available")
            
        self.api_key = os.getenv("BINANCE_API_KEY")
        self.secret_key = os.getenv("BINANCE_SECRET_KEY")
        
        if not self.api_key or not self.secret_key:
            raise BinanceBotError("API keys not found in environment variables")
        
        # Use testnet for safety
        try:
            self.client = UMFutures(
                key=self.api_key, 
                secret=self.secret_key, 
                base_url="https://testnet.binancefuture.com/en/futures/BTCUSDT"
            )
        except Exception as e:
            raise BinanceBotError(f"Failed to initialize Binance client: {e}")
    
    def fetch_klines(self, symbol: str, interval: str = "1m", limit: int = 50) -> Optional[pd.DataFrame]:
        """Fetch and process klines data with error handling."""
        try:
            klines = self.client.klines(symbol, interval, limit=limit)
            
            columns = [
                'OpenTime', 'Open', 'High', 'Low', 'Close', 'Volume',
                'CloseTime', 'QuoteAssetVolume', 'NumberOfTrades',
                'TakerBuyBase', 'TakerBuyQuote', 'Ignore'
            ]
            
            df = pd.DataFrame(klines, columns=columns)
            
            # Convert numeric columns
            numeric_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
            for col in numeric_cols:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # Convert timestamps
            df['OpenTime'] = pd.to_datetime(df['OpenTime'], unit='ms')
            df['CloseTime'] = pd.to_datetime(df['CloseTime'], unit='ms')
            
            return df
            
        except Exception as e:
            logger.error(f"Binance API error: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching klines: {e}")
            return None
    
    def calculate_indicators(self, df: pd.DataFrame) -> Dict[str, float]:
        """Calculate multiple technical indicators."""
        indicators = {}
        
        try:
            # Simple Moving Averages
            indicators['sma_5'] = df['Close'].rolling(window=5).mean().iloc[-1]
            indicators['sma_10'] = df['Close'].rolling(window=10).mean().iloc[-1]
            indicators['sma_20'] = df['Close'].rolling(window=20).mean().iloc[-1]
            
            # Exponential Moving Average
            indicators['ema_12'] = df['Close'].ewm(span=12).mean().iloc[-1]
            indicators['ema_26'] = df['Close'].ewm(span=26).mean().iloc[-1]
            
            # RSI (Relative Strength Index)
            delta = df['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            indicators['rsi'] = 100 - (100 / (1 + rs.iloc[-1]))
            
            # MACD
            indicators['macd'] = indicators['ema_12'] - indicators['ema_26']
            
            # Bollinger Bands
            sma_20 = df['Close'].rolling(window=20).mean()
            std_20 = df['Close'].rolling(window=20).std()
            indicators['bb_upper'] = (sma_20 + (std_20 * 2)).iloc[-1]
            indicators['bb_lower'] = (sma_20 - (std_20 * 2)).iloc[-1]
            
            # Volume indicators
            indicators['avg_volume'] = df['Volume'].rolling(window=10).mean().iloc[-1]
            indicators['volume_ratio'] = df['Volume'].iloc[-1] / indicators['avg_volume']
            
        except Exception as e:
            logger.error(f"Error calculating indicators: {e}")
            
        return indicators
    
    def generate_signals(self, current_price: float, indicators: Dict[str, float]) -> Dict[str, str]:
        """Generate trading signals based on indicators."""
        signals = {}
        
        try:
            # Trend signals
            if current_price > indicators.get('sma_5', 0):
                signals['sma_5_trend'] = 'BULLISH'
            else:
                signals['sma_5_trend'] = 'BEARISH'
            
            if current_price > indicators.get('sma_20', 0):
                signals['sma_20_trend'] = 'BULLISH'
            else:
                signals['sma_20_trend'] = 'BEARISH'
            
            # RSI signals
            rsi = indicators.get('rsi', 50)
            if rsi > 70:
                signals['rsi_signal'] = 'OVERBOUGHT'
            elif rsi < 30:
                signals['rsi_signal'] = 'OVERSOLD'
            else:
                signals['rsi_signal'] = 'NEUTRAL'
            
            # MACD signal
            macd = indicators.get('macd', 0)
            if macd > 0:
                signals['macd_signal'] = 'BULLISH'
            else:
                signals['macd_signal'] = 'BEARISH'
            
            # Bollinger Bands
            bb_upper = indicators.get('bb_upper', float('inf'))
            bb_lower = indicators.get('bb_lower', 0)
            
            if current_price > bb_upper:
                signals['bb_signal'] = 'OVERBOUGHT'
            elif current_price < bb_lower:
                signals['bb_signal'] = 'OVERSOLD'
            else:
                signals['bb_signal'] = 'NEUTRAL'
            
            # Volume signal
            volume_ratio = indicators.get('volume_ratio', 1)
            if volume_ratio > 1.5:
                signals['volume_signal'] = 'HIGH_VOLUME'
            elif volume_ratio < 0.5:
                signals['volume_signal'] = 'LOW_VOLUME'
            else:
                signals['volume_signal'] = 'NORMAL_VOLUME'
                
        except Exception as e:
            logger.error(f"Error generating signals: {e}")
            
        return signals
    
    def track_crypto(self, symbol: str = "BTCUSDT", interval: str = "1m"):
        """Enhanced crypto tracking with multiple indicators."""
        logger.info(f"Starting enhanced ML tracking for {symbol}...")
        
        df = self.fetch_klines(symbol, interval)
        if df is None or df.empty:
            logger.error("Failed to fetch price data")
            return
        
        current_price = df['Close'].iloc[-1]
        indicators = self.calculate_indicators(df)
        signals = self.generate_signals(current_price, indicators)
        
        # Display results
        print(f"\n{'='*60}")
        print(f"📊 {symbol} Analysis - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}")
        print(f"💰 Current Price: ${current_price:,.2f}")
        print(f"📈 24h Change: {((current_price - df['Close'].iloc[0]) / df['Close'].iloc[0] * 100):+.2f}%")
        
        print(f"\n📋 Technical Indicators:")
        for indicator, value in indicators.items():
            if 'sma' in indicator or 'ema' in indicator or 'bb' in indicator:
                print(f"  {indicator.upper()}: ${value:,.2f}")
            elif 'rsi' in indicator:
                print(f"  {indicator.upper()}: {value:.2f}")
            elif 'volume' in indicator:
                if 'ratio' in indicator:
                    print(f"  {indicator.upper()}: {value:.2f}x")
                else:
                    print(f"  {indicator.upper()}: {value:,.0f}")
            else:
                print(f"  {indicator.upper()}: {value:.2f}")
        
        print(f"\n🎯 Trading Signals:")
        for signal_type, signal in signals.items():
            emoji = self._get_signal_emoji(signal)
            print(f"  {emoji} {signal_type.replace('_', ' ').title()}: {signal}")
        
        # Overall recommendation
        bullish_signals = sum(1 for s in signals.values() if 'BULLISH' in s or 'OVERSOLD' in s)
        bearish_signals = sum(1 for s in signals.values() if 'BEARISH' in s or 'OVERBOUGHT' in s)
        
        print(f"\n🔍 Overall Assessment:")
        if bullish_signals > bearish_signals:
            print("  📈 BULLISH BIAS - Consider long positions")
        elif bearish_signals > bullish_signals:
            print("  📉 BEARISH BIAS - Consider short positions")
        else:
            print("  ⚖️ NEUTRAL - Wait for clearer signals")
        
        print(f"{'='*60}\n")
    
    def _get_signal_emoji(self, signal: str) -> str:
        """Get appropriate emoji for signal."""
        emoji_map = {
            'BULLISH': '🟢',
            'BEARISH': '🔴',
            'OVERBOUGHT': '🔴',
            'OVERSOLD': '🟢',
            'NEUTRAL': '🟡',
            'HIGH_VOLUME': '🔊',
            'LOW_VOLUME': '🔉',
            'NORMAL_VOLUME': '🔈'
        }
        return emoji_map.get(signal, '⚪')

def validate_order_args(order_type: str, args: List[str]) -> bool:
    """Validate arguments for different order types."""
    min_args = {
        'market': 3,    # symbol, side, quantity
        'limit': 4,     # symbol, side, quantity, price
        'oco': 6,       # symbol, side, quantity, price, stopPrice, stopLimitPrice
        'stop_limit': 5, # symbol, side, quantity, stopPrice, price
        'twap': 5       # symbol, side, quantity, parts, interval
    }
    
    required = min_args.get(order_type, 0)
    if len(args) < required:
        logger.error(f"Order type '{order_type}' requires at least {required} arguments, got {len(args)}")
        return False
    
    return True

def run_order_script(order_type: str, args: List[str]) -> bool:
    """Execute order script with enhanced error handling."""
    if not validate_order_args(order_type, args):
        return False
    
    script_path = ORDER_SCRIPTS[order_type]
    
    if not Path(script_path).exists():
        logger.error(f"Script not found: {script_path}")
        return False
    
    command = ['python', str(script_path)] + args
    logger.info(f"Running: {' '.join(command)}")
    
    try:
        result = subprocess.run(
            command, 
            check=True, 
            capture_output=True, 
            text=True,
            timeout=30  # 30 second timeout
        )
        
        if result.stdout:
            logger.info(f"Script output: {result.stdout}")
        
        return True
        
    except subprocess.TimeoutExpired:
        logger.error("Script execution timed out")
        return False
    except subprocess.CalledProcessError as e:
        logger.error(f"Script failed with exit code {e.returncode}")
        if e.stderr:
            logger.error(f"Error output: {e.stderr}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error running script: {e}")
        return False

def _run_signal_scan(symbol: str, primary_tf: str, confirm_tf: str):
    """Run the advanced multi-TF signal scan and pretty-print the result."""
    import pandas as pd
    from binance.um_futures import UMFutures

    api_key    = os.getenv("BINANCE_API_KEY", "")
    secret_key = os.getenv("BINANCE_SECRET_KEY", "")
    use_testnet = os.getenv("USE_TESTNET", "true").lower() == "true"
    base_url = "https://testnet.binancefuture.com" if use_testnet else "https://fapi.binance.com"
    client = UMFutures(key=api_key, secret=secret_key, base_url=base_url)

    def fetch_klines(sym, interval, limit=200):
        raw = client.klines(sym, interval, limit=limit)
        cols = ["OpenTime","Open","High","Low","Close","Volume",
                "CloseTime","QuoteVol","Trades","TakerBase","TakerQuote","Ignore"]
        df = pd.DataFrame(raw, columns=cols)
        for c in ["Open","High","Low","Close","Volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df

    engine = SignalEngine(fetch_klines)
    sig = engine.analyse(symbol, primary_tf, confirm_tf)

    print(f"\n{'='*60}")
    print(f"  Advanced Signal Scan: {symbol}  ({primary_tf} / {confirm_tf})")
    print(f"{'='*60}")
    if sig is None:
        print("  No high-confidence signal at this time.")
    else:
        arrow = "LONG  (BUY)" if sig.direction.value == "LONG" else "SHORT (SELL)"
        print(f"  Direction  : {arrow}")
        print(f"  Confidence : {sig.confidence}%")
        print(f"  Entry      : {sig.price}")
        print(f"  Stop Loss  : {sig.stop_loss}  (ATR-based)")
        print(f"  Take Profit: {sig.take_profit}  (R:R ≈ 1.75)")
        print(f"\n  Reasons:")
        for r in sig.reasons:
            print(f"    • {r}")
    print(f"{'='*60}\n")


def _print_stats():
    """Display trade statistics from the SQLite tracker."""
    try:
        from trade_tracker import TradeTracker
        tracker = TradeTracker()
        stats   = tracker.get_stats()
        open_t  = tracker.get_open_trades()
        print(f"\n{'='*50}")
        print("PERFORMANCE STATS (All Time)")
        print(f"{'='*50}")
        print(f"  Total trades   : {stats['total_trades']}")
        print(f"  Win rate       : {stats['win_rate']}%")
        print(f"  Total PnL      : {stats['total_pnl']:.4f} USDT")
        print(f"  Avg PnL/trade  : {stats['avg_pnl']:.4f} USDT")
        print(f"  Avg R:R        : {stats['avg_rr']:.2f}")
        print(f"  Max Drawdown   : {stats['max_drawdown_pct']:.2f}%")
        print(f"  Profit Factor  : {stats['profit_factor']:.2f}")
        print(f"\n  Open positions : {len(open_t)}")
        print(f"{'='*50}\n")
    except Exception as e:
        logger.error(f"Stats error: {e}")


def main():
    """Enhanced main function with comprehensive error handling."""
    parser = argparse.ArgumentParser(
        description="Enhanced Binance Master CLI Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python bot.py market BTCUSDT BUY 0.001
  python bot.py limit BTCUSDT BUY 0.001 25000
  python bot.py oco BTCUSDT SELL 0.001 26000 24000 23500
  python bot.py stop_limit BTCUSDT BUY 0.001 24500 25000
  python bot.py twap BTCUSDT BUY 0.01 --parts 5 --interval 60
  python bot.py ml_track [SYMBOL] [INTERVAL]
  python bot.py signal [SYMBOL] [PRIMARY_TF] [CONFIRM_TF]   # advanced MTF signal
  python bot.py strategy --symbols BTCUSDT ETHUSDT          # autonomous trading
  python bot.py stats                                        # P&L stats
  python bot.py validate
        """
    )
    
    parser.add_argument(
        'order_type',
        choices=list(ORDER_SCRIPTS.keys()) + ['ml_track', 'signal', 'strategy', 'stats', 'validate'],
        help='Order type, signal scan, autonomous strategy, stats, or validation'
    )
    parser.add_argument('args', nargs=argparse.REMAINDER, help='Order arguments')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose logging')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Validate environment
    if not ConfigValidator.validate_environment():
        logger.error("Environment validation failed")
        sys.exit(1)
    
    try:
        if args.order_type == 'validate':
            logger.info("Running configuration validation...")
            script_status = ConfigValidator.validate_scripts()
            
            print(f"\n{'='*40}")
            print("📋 Configuration Status")
            print(f"{'='*40}")
            print("✅ Environment variables: OK")
            
            print("\n📁 Script Status:")
            for order_type, exists in script_status.items():
                status = "✅ OK" if exists else "❌ MISSING"
                print(f"  {order_type}: {status}")
            
            missing_scripts = [k for k, v in script_status.items() if not v]
            if missing_scripts:
                print(f"\n⚠️  Missing scripts: {', '.join(missing_scripts)}")
                sys.exit(1)
            else:
                print("\n✅ All systems ready!")
        
        elif args.order_type in ORDER_SCRIPTS:
            success = run_order_script(args.order_type, args.args)
            if not success:
                sys.exit(1)

        elif args.order_type == 'signal':
            # Advanced multi-timeframe signal scan
            if not SIGNAL_ENGINE_AVAILABLE or not BINANCE_AVAILABLE or not PANDAS_AVAILABLE:
                logger.error("signal requires pandas and python-binance")
                sys.exit(1)
            symbol     = args.args[0] if args.args           else "BTCUSDT"
            primary_tf = args.args[1] if len(args.args) > 1  else "5m"
            confirm_tf = args.args[2] if len(args.args) > 2  else "1h"
            _run_signal_scan(symbol, primary_tf, confirm_tf)

        elif args.order_type == 'strategy':
            # Launch the autonomous strategy engine as a subprocess
            strategy_script = Path(__file__).parent / 'strategy_engine.py'
            extra = list(args.args)
            cmd = ['python', str(strategy_script)] + extra
            logger.info(f"Launching strategy engine: {' '.join(cmd)}")
            os.execv(sys.executable, [sys.executable] + cmd[1:] if cmd[0] == 'python' else cmd)

        elif args.order_type == 'stats':
            # Show trade stats from the tracker
            _print_stats()

        elif args.order_type == 'ml_track':
            if not BINANCE_AVAILABLE or not PANDAS_AVAILABLE:
                logger.error("ML tracking requires python-binance and pandas libraries")
                print("\nTo install required libraries:")
                print("pip install python-binance pandas")
                sys.exit(1)
                
            try:
                tracker = MLTracker()
                
                # Parse optional arguments
                symbol = args.args[0] if args.args else "BTCUSDT"
                interval = args.args[1] if len(args.args) > 1 else "1m"
                
                tracker.track_crypto(symbol, interval)
            except BinanceBotError as e:
                logger.error(f"ML tracking failed: {e}")
                sys.exit(1)
        
        else:
            logger.error(f"Unknown order type: {args.order_type}")
            sys.exit(1)
    
    except KeyboardInterrupt:
        logger.info("Operation cancelled by user")
        sys.exit(0)
    except BinanceBotError as e:
        logger.error(f"Bot error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()