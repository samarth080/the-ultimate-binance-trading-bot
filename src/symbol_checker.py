import os
from binance.um_futures import UMFutures
from dotenv import load_dotenv

load_dotenv()

# Initialize client
client = UMFutures(
    key=os.getenv("BINANCE_API_KEY"),
    secret=os.getenv("BINANCE_SECRET_KEY"),
    base_url="https://testnet.binancefuture.com"
)

def check_symbol_requirements(symbol):
    """Check trading requirements for a symbol"""
    try:
        exchange_info = client.exchange_info()
        
        for symbol_info in exchange_info['symbols']:
            if symbol_info['symbol'] == symbol:
                print(f"\n📊 Trading requirements for {symbol}:")
                print(f"Status: {symbol_info['status']}")
                
                for filter_info in symbol_info['filters']:
                    if filter_info['filterType'] == 'LOT_SIZE':
                        print(f"\n🔢 Quantity Rules:")
                        print(f"  Min Quantity: {filter_info['minQty']}")
                        print(f"  Max Quantity: {filter_info['maxQty']}")
                        print(f"  Step Size: {filter_info['stepSize']}")
                        
                        # Calculate some valid quantities
                        min_qty = float(filter_info['minQty'])
                        step_size = float(filter_info['stepSize'])
                        
                        print(f"\n✅ Valid quantities (examples):")
                        for i in range(1, 6):
                            valid_qty = min_qty + (step_size * i)
                            print(f"  {valid_qty}")
                        
                        return
                
                print(f"❌ No LOT_SIZE filter found for {symbol}")
                return
        
        print(f"❌ Symbol {symbol} not found")
        
    except Exception as e:
        print(f"❌ Error checking {symbol}: {e}")

if __name__ == "__main__":
    check_symbol_requirements("ETHUSDT")
    check_symbol_requirements("BTCUSDT")