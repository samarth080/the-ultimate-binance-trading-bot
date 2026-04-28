import os
from binance.um_futures import UMFutures
from dotenv import load_dotenv

load_dotenv()

def test_api_credentials():
    """Test if API credentials are working"""
    
    api_key = os.getenv("BINANCE_API_KEY")
    secret_key = os.getenv("BINANCE_SECRET_KEY")
    
    print("🔑 Testing API credentials...")
    print(f"API Key: {api_key[:8]}...{api_key[-4:] if api_key else 'None'}")
    print(f"Secret Key: {secret_key[:8]}...{secret_key[-4:] if secret_key else 'None'}")
    
    if not api_key or not secret_key:
        print("❌ API credentials not found in environment variables")
        return False
    
    # Test with testnet
    testnet_client = UMFutures(
        key=api_key,
        secret=secret_key,
        base_url="https://testnet.binancefuture.com"
    )
    
    try:
        print("\n🌐 Testing TESTNET connection...")
        
        # Test 1: Server time (no auth required)
        server_time = testnet_client.time()
        print(f"✅ Server time: {server_time}")
        
        # Test 2: Account info (auth required)
        account_info = testnet_client.account()
        print(f"✅ Account info retrieved successfully")
        print(f"Account type: {account_info.get('accountType', 'N/A')}")
        
        # Test 3: Balance info
        balances = account_info.get('assets', [])
        print(f"✅ Account has {len(balances)} assets")
        
        # Show non-zero balances
        for asset in balances:
            if float(asset.get('walletBalance', 0)) > 0:
                print(f"  {asset['asset']}: {asset['walletBalance']}")
        
        return True
        
    except Exception as e:
        print(f"❌ TESTNET Error: {e}")
        
        # Test with mainnet to see if keys are for wrong network
        print("\n🌐 Testing MAINNET connection...")
        mainnet_client = UMFutures(
            key=api_key,
            secret=secret_key,
            base_url="https://fapi.binance.com"
        )
        
        try:
            account_info = mainnet_client.account()
            print("⚠️  SUCCESS ON MAINNET! Your keys are for MAINNET, not TESTNET!")
            print("💡 Either:")
            print("   1. Get testnet keys from https://testnet.binancefuture.com/")
            print("   2. Or change USE_TESTNET=false in your .env file")
            return False
        except Exception as mainnet_error:
            print(f"❌ MAINNET Error: {mainnet_error}")
            print("\n🔧 Troubleshooting steps:")
            print("1. Check if your API key is correct")
            print("2. Check if your secret key is correct")
            print("3. Verify keys are for the right network (testnet vs mainnet)")
            print("4. Check API permissions (Enable Reading + Enable Futures Trading)")
            print("5. Check IP restrictions")
            return False

if __name__ == "__main__":
    test_api_credentials()