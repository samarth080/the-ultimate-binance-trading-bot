# 🚀 Binance Enhanced Trading Bot

<div align="center">

![Python](https://img.shields.io/badge/python-v3.8+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Binance](https://img.shields.io/badge/exchange-Binance%20Futures-yellow.svg)
![Status](https://img.shields.io/badge/status-active-success.svg)

*A comprehensive, feature-rich trading bot for Binance Futures with advanced order types, ML-powered analytics, and robust error handling.*

</div>

## 📋 Table of Contents

- [✨ Features](#-features)
- [🏗️ Project Structure](#️-project-structure)
- [🔧 Installation](#-installation)
- [⚙️ Configuration](#️-configuration)
- [🎯 Usage](#-usage)
- [📊 ML Analytics](#-ml-analytics)
- [📈 Order Types](#-order-types)
- [🔒 Security](#-security)
- [📝 Logging](#-logging)
- [🤝 Contributing](#-contributing)
- [📄 License](#-license)

## ✨ Features

### 🎯 **Advanced Order Management**
- **Market Orders** - Instant execution at current market prices
- **Limit Orders** - Precise entry/exit at specific price levels
- **OCO Orders** - One-Cancels-Other for risk management
- **Stop-Limit Orders** - Advanced stop-loss with price protection
- **TWAP Orders** - Time-Weighted Average Price execution

### 🧠 **ML-Powered Analytics**
- **Technical Indicators**: SMA, EMA, RSI, MACD, Bollinger Bands
- **Volume Analysis**: Volume ratios and trend detection
- **Signal Generation**: Automated buy/sell signal recommendations
- **Real-time Monitoring**: Live price tracking with comprehensive analysis

### 🛡️ **Enterprise-Grade Features**
- **Comprehensive Validation**: Symbol, quantity, and price validation
- **Error Handling**: Robust exception handling with detailed logging
- **Dry Run Mode**: Test strategies without risking capital
- **Configuration Validation**: Environment and script validation
- **Structured Logging**: Detailed logs with rotation support

## 🏗️ Project Structure

```
binance-trading-bot/
├── 📁 src/
│   ├── 🐍 bot.py                    # Main bot orchestrator
│   ├── 🐍 market_orders.py          # Market order execution
│   ├── 🐍 limit_orders.py           # Limit order management
│   └── 📁 advanced/
│       ├── 🐍 oco.py                # OCO order implementation
│       ├── 🐍 stop_limit_orders.py  # Stop-limit functionality
│       └── 🐍 twap.py               # TWAP execution engine
├── 📁 logs/                         # Application logs
│   └── 📄 bot.log                   # Main log file
├── 📁 docs/                         # Documentation
│   └── 📄 Binance Futures Order Bot.docx
├── 📁 venv/                         # Virtual environment
├── 📄 .env                          # Environment variables
├── 📄 requirements.txt              # Python dependencies
└── 📄 README.md                     # This file
```

## 🔧 Installation

### Prerequisites

- **Python 3.8+** - [Download Python](https://python.org/downloads/)
- **Binance Account** - [Create Account](https://binance.com/)
- **API Keys** - [Generate API Keys](https://www.binance.com/en/my/settings/api-management)

### Step 1: Clone Repository

```bash
git clone https://github.com/kr4ter/binance-trading-bot.git
cd binance-trading-bot
```

### Step 2: Create Virtual Environment

```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate
```

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Required Dependencies

```bash
# Core dependencies
pip install python-binance pandas python-dotenv

# Optional for enhanced features
pip install numpy matplotlib seaborn
```

## ⚙️ Configuration

### 1. Environment Setup

Create a `.env` file in the root directory:

```env
# Binance API Configuration
BINANCE_API_KEY=your_api_key_here
BINANCE_SECRET_KEY=your_secret_key_here

# Optional: Testnet Configuration (recommended for testing)
BINANCE_TESTNET=true
```

### 2. API Key Permissions

Ensure your API keys have the following permissions:
- ✅ **Futures Trading** - Required for order execution
- ✅ **Read Info** - Required for account and market data
- ❌ **Withdraw** - Not required (keep disabled for security)

### 3. IP Restrictions

For enhanced security, restrict API access to your IP address in Binance settings.

## 🎯 Usage

### Basic Commands

```bash
# Validate configuration
python bot.py validate

# Place market order
python market_order.py BTCUSDT BUY 0.01

# Place limit order
python bot.py limit BTCUSDT BUY 0.01 50000
# Advanced OCO order
python bot.py oco BTCUSDT SELL 0.01 52000 48000 47500

# Stop-limit order
python bot.py stop_limit BTCUSDT SELL 0.01 49000 48500

# TWAP order (divide into 10 parts, 60s intervals)
python bot.py twap BTCUSDT BUY 0.1 10 60
```

### ML Analytics

```bash
# Track BTC with default settings
python bot.py ml_track

# Track specific symbol with custom interval
python bot.py ml_track ETHUSDT 5m

# Continuous monitoring
python bot.py ml_track BTCUSDT 1m --continuous
```

### Dry Run Mode

Test your strategies without risking capital:

```bash
python market_orders.py BTCUSDT BUY 0.01 --dry-run
python limit_orders.py BTCUSDT BUY 0.01 50000 --dry-run
```

## 📊 ML Analytics

### Available Indicators

| Indicator | Description | Signal Generation |
|-----------|-------------|-------------------|
| **SMA** | Simple Moving Average (5, 10, 20) | Trend identification |
| **EMA** | Exponential Moving Average (12, 26) | Responsive trend analysis |
| **RSI** | Relative Strength Index | Overbought/oversold detection |
| **MACD** | Moving Average Convergence Divergence | Momentum analysis |
| **Bollinger Bands** | Price volatility bands | Support/resistance levels |
| **Volume Analysis** | Volume ratio and trends | Market strength confirmation |

### Sample ML Output

```
📊 BTCUSDT Analysis - 2024-01-15 14:30:25
============================================================
💰 Current Price: $51,234.56
📈 24h Change: +2.45%

📋 Technical Indicators:
  SMA_5: $51,100.23
  SMA_20: $50,800.45
  RSI: 68.45
  MACD: 45.67
  BB_UPPER: $52,000.00
  BB_LOWER: $49,500.00

🎯 Trading Signals:
  🟢 SMA 5 Trend: BULLISH
  🟢 SMA 20 Trend: BULLISH
  🔴 RSI Signal: OVERBOUGHT
  🟢 MACD Signal: BULLISH
  🟡 BB Signal: NEUTRAL

🔍 Overall Assessment:
  📈 BULLISH BIAS - Consider long positions
============================================================
```

## 📈 Order Types

### Market Orders
- **Instant execution** at current market price
- **Best for**: Quick entries/exits
- **Risk**: Price slippage in volatile markets

### Limit Orders
- **Precise price control** with guaranteed execution price
- **Best for**: Planned entries at specific levels
- **Risk**: May not execute if price doesn't reach limit

### OCO Orders (One-Cancels-Other)
- **Dual order system** with profit target and stop loss
- **Best for**: Risk management with automatic execution
- **Risk**: Requires careful price level selection

### Stop-Limit Orders
- **Conditional execution** with price protection
- **Best for**: Advanced risk management
- **Risk**: Gap risk in volatile markets

### TWAP Orders (Time-Weighted Average Price)
- **Gradual execution** to minimize market impact
- **Best for**: Large positions without moving the market
- **Risk**: Extended execution time

## 🔒 Security

### Best Practices

1. **API Key Security**
   - Never commit API keys to version control
   - Use environment variables for sensitive data
   - Enable IP restrictions on Binance

2. **Testnet First**
   - Always test strategies on Binance Testnet
   - Validate all parameters before live trading
   - Use dry-run mode for initial testing

3. **Risk Management**
   - Start with small position sizes
   - Set appropriate stop-losses
   - Monitor positions regularly

## 📝 Logging

### Log Levels

- **INFO**: General operation information
- **WARNING**: Important notices that don't stop execution
- **ERROR**: Errors that prevent specific operations
- **CRITICAL**: System-level failures

### Log Files

```
logs/
├── bot.log          # Main application logs
└── orders.log       # Order execution logs (if enabled)
```

### Sample Log Entry

```
[2024-01-15 14:30:25] INFO [MarketOrderBot]: ✅ MARKET BUY order placed successfully
[2024-01-15 14:30:25] INFO [MarketOrderBot]: Order Details - ID: 123456789, Status: FILLED, Executed: 0.01
```

## 🤝 Contributing

We welcome contributions! Please follow these guidelines:

1. **Fork the repository**
2. **Create a feature branch**: `git checkout -b feature/amazing-feature`
3. **Commit changes**: `git commit -m 'Add amazing feature'`
4. **Push to branch**: `git push origin feature/amazing-feature`
5. **Open a Pull Request**

### Development Setup

```bash
# Install development dependencies
pip install -r requirements-dev.txt

# Run tests
python -m pytest tests/

# Code formatting
black src/
flake8 src/
```

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## ⚠️ Disclaimer

**This bot is for educational purposes only. Trading cryptocurrency involves substantial risk of loss. Always:**

- Start with small amounts
- Use testnet for initial testing
- Understand the risks involved
- Never invest more than you can afford to lose
- The developers are not responsible for any financial losses

---

<div align="center">

**Made with ❤️ by UDAI BATTA**

</div>