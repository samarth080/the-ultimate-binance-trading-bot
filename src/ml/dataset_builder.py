import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)

def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Calculates TA features without lookahead bias."""
    df = df.copy()
    
    # Capitalize if they arrive lower test from testnet vs binance um_futures
    if 'close' in df.columns and 'Close' not in df.columns:
        df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'}, inplace=True)
    
    # Price derivations
    df['returns_1'] = df['Close'].pct_change(1)
    df['returns_3'] = df['Close'].pct_change(3)
    df['returns_5'] = df['Close'].pct_change(5)
    
    # Volatility
    df['volatility_10'] = df['returns_1'].rolling(10).std()
    df['volatility_20'] = df['returns_1'].rolling(20).std()
    
    # RSI
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi_14'] = 100 - (100 / (1 + rs))
    
    # Moving Averages distance
    sma_20 = df['Close'].rolling(20).mean()
    df['dist_sma_20'] = (df['Close'] - sma_20) / sma_20
    
    sma_50 = df['Close'].rolling(50).mean()
    df['dist_sma_50'] = (df['Close'] - sma_50) / sma_50
    
    # MACD
    ema_12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema_26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['macd'] = ema_12 - ema_26
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['macd_hist'] = df['macd'] - df['macd_signal']
    
    df.replace([np.inf, -np.inf], np.nan, inplace=True)
    df.dropna(inplace=True)
    return df

def build_dataset(df: pd.DataFrame, forward_bars: int = 5, min_profit_pct: float = 0.002) -> pd.DataFrame:
    """Builds the final dataset with targets."""
    df = build_features(df)
    
    # Binary classification target: Did it go up significantly?
    future_price = df['Close'].shift(-forward_bars)
    future_returns = (future_price - df['Close']) / df['Close']
    df['target'] = (future_returns >= min_profit_pct).astype(int)
    
    # Drop the trailing NaNs mapped from shift negative
    df.dropna(inplace=True)
    return df
