"""Market data routes: status, prices, funding rates, ML analysis, signal scanning."""
import os
from datetime import datetime

from fastapi import Request
from fastapi.routing import APIRouter

from shared import (
    limiter, RATE_READ, RATE_SIGNAL,
    api_log, get_client, get_intel,
    clean_symbol, safe_interval,
)

router = APIRouter()


@router.get("/api/status")
@limiter.limit(RATE_READ)
async def status(request: Request):
    api_key = os.getenv("BINANCE_API_KEY", "")
    secret  = os.getenv("BINANCE_SECRET_KEY", "")
    testnet = os.getenv("USE_TESTNET", "true").lower() == "true"
    mode    = os.getenv("BINANCE_MODE", "live").lower()
    api_log.info(f"Status check — testnet={testnet} mode={mode}")
    return {
        "api_key_set":    bool(api_key),
        "secret_key_set": bool(secret),
        "testnet":        testnet,
        "mode":           mode,
        "timestamp":      datetime.now().isoformat(),
    }


@router.get("/api/prices")
@limiter.limit(RATE_READ)
async def get_prices(request: Request, symbols: str = "BTCUSDT,ETHUSDT,SOLUSDT"):
    syms = [clean_symbol(s.strip()) for s in symbols.split(",") if s.strip()][:10]
    try:
        client = get_client()
        prices = {}
        for sym in syms:
            try: prices[sym] = float(client.ticker_price(symbol=sym)["price"])
            except Exception: prices[sym] = None
        return {"prices": prices, "ts": datetime.now().isoformat()}
    except Exception as exc:
        api_log.error(f"Prices failed: {exc}")
        from fastapi import HTTPException
        raise HTTPException(500, "Prices unavailable — see server logs")


@router.get("/api/funding")
@limiter.limit(RATE_READ)
async def get_funding_rates(
    request: Request,
    symbols: str = "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT,ADAUSDT,AVAXUSDT,LINKUSDT,DOTUSDT",
):
    syms = [clean_symbol(s.strip()) for s in symbols.split(",") if s.strip()][:15]
    try:
        client = get_client()
        rates  = []
        for sym in syms:
            try:
                info  = client.mark_price(symbol=sym)
                rate  = float(info.get("lastFundingRate", 0))
                price = float(info.get("markPrice", 0))
                rates.append({
                    "symbol":         sym,
                    "funding_rate":   round(rate, 6),
                    "funding_pct":    round(rate * 100, 4),
                    "mark_price":     round(price, 4),
                    "annualized_pct": round(rate * 3 * 365 * 100, 2),
                    "bias": "SHORT_BIAS" if rate > 0.0005 else ("LONG_BIAS" if rate < -0.0005 else "NEUTRAL"),
                })
            except Exception as e:
                api_log.warning(f"Funding rate error for {sym}: {e}")
        return {"rates": rates, "ts": datetime.now().isoformat()}
    except Exception as exc:
        api_log.error(f"Funding rates failed: {exc}")
        from fastapi import HTTPException
        raise HTTPException(500, "Funding rates unavailable — see server logs")


@router.get("/api/ml/analyze")
@limiter.limit(RATE_SIGNAL)
async def ml_analyze(request: Request, symbol: str = "BTCUSDT", interval: str = "1m"):
    from fastapi import HTTPException
    symbol   = clean_symbol(symbol)
    interval = safe_interval(interval)
    try:
        import pandas as pd
        from binance.um_futures import UMFutures

        client = UMFutures(
            key=os.getenv("BINANCE_API_KEY"), secret=os.getenv("BINANCE_SECRET_KEY"),
            base_url="https://testnet.binancefuture.com",
        )
        klines = client.klines(symbol, interval, limit=50)
        cols   = ["OpenTime","Open","High","Low","Close","Volume",
                  "CloseTime","QuoteVol","Trades","TakerBase","TakerQuote","Ignore"]
        df     = pd.DataFrame(klines, columns=cols)
        for c in ["Open","High","Low","Close","Volume"]:
            df[c] = pd.to_numeric(df[c])

        close   = df["Close"]
        current = float(close.iloc[-1])
        pct_chg = (current - float(close.iloc[0])) / float(close.iloc[0]) * 100

        sma5  = float(close.rolling(5).mean().iloc[-1])
        sma10 = float(close.rolling(10).mean().iloc[-1])
        sma20 = float(close.rolling(20).mean().iloc[-1])
        ema12 = float(close.ewm(span=12, adjust=False).mean().iloc[-1])
        ema26 = float(close.ewm(span=26, adjust=False).mean().iloc[-1])
        macd  = ema12 - ema26

        delta  = close.diff()
        gain   = delta.where(delta > 0, 0).rolling(14).mean()
        loss   = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi    = float(100 - 100 / (1 + (gain / loss).iloc[-1]))

        std20    = close.rolling(20).std()
        sma20s   = close.rolling(20).mean()
        bb_upper = float((sma20s + std20 * 2).iloc[-1])
        bb_lower = float((sma20s - std20 * 2).iloc[-1])

        avg_vol   = float(df["Volume"].rolling(10).mean().iloc[-1])
        vol_ratio = float(df["Volume"].iloc[-1]) / avg_vol if avg_vol else 1.0

        candles = [
            {"o": float(r.Open), "h": float(r.High),
             "l": float(r.Low),  "c": float(r.Close), "v": float(r.Volume)}
            for _, r in df.tail(30).iterrows()
        ]

        ml_prob, ml_action = 0.5, "NEUTRAL"
        try:
            from ml.predictor import MLPredictor
            predictor = MLPredictor()
            if predictor.enabled:
                ml_prob = predictor.predict_up_probability(df)
                if ml_prob > 0.65:   ml_action = "BULLISH"
                elif ml_prob < 0.35: ml_action = "BEARISH"
        except Exception as e:
            api_log.warning(f"ML Predictor fallback: {e}")

        api_log.info(f"ML {symbol}: ${current:,.2f} RSI={rsi:.1f} PROB={ml_prob*100:.1f}%")
        return {
            "symbol":           symbol,
            "price":            current,
            "price_change_pct": pct_chg,
            "indicators": {
                "sma_5": sma5, "sma_10": sma10, "sma_20": sma20,
                "ema_12": ema12, "ema_26": ema26, "macd": macd,
                "rsi": rsi, "bb_upper": bb_upper, "bb_lower": bb_lower,
                "volume_ratio": vol_ratio,
            },
            "signals": {
                "sma5":   "BULLISH"    if current > sma5   else "BEARISH",
                "sma20":  "BULLISH"    if current > sma20  else "BEARISH",
                "rsi":    "OVERBOUGHT" if rsi > 70  else ("OVERSOLD" if rsi < 30 else "NEUTRAL"),
                "macd":   "BULLISH"    if macd > 0  else "BEARISH",
                "bb":     "OVERBOUGHT" if current > bb_upper else ("OVERSOLD" if current < bb_lower else "NEUTRAL"),
                "volume": "HIGH"       if vol_ratio > 1.5 else ("LOW" if vol_ratio < 0.5 else "NORMAL"),
            },
            "ml_probability": round(ml_prob * 100, 2),
            "ml_action":      ml_action,
            "candles":        candles,
            "ts":             datetime.now().isoformat(),
        }
    except Exception as exc:
        api_log.error(f"ML analysis failed: {exc}")
        raise HTTPException(500, "Analysis failed — see server logs")


def _make_binance_client():
    from binance.um_futures import UMFutures
    use_testnet = os.getenv("USE_TESTNET", "true").lower() == "true"
    return UMFutures(
        key=os.getenv("BINANCE_API_KEY"), secret=os.getenv("BINANCE_SECRET_KEY"),
        base_url="https://testnet.binancefuture.com" if use_testnet else "https://fapi.binance.com",
    )


def _fetch_klines_df(client, sym: str, interval: str, limit: int = 200):
    import pandas as pd
    raw  = client.klines(sym, interval, limit=limit)
    cols = ["OpenTime","Open","High","Low","Close","Volume",
            "CloseTime","QuoteVol","Trades","TakerBase","TakerQuote","Ignore"]
    df   = pd.DataFrame(raw, columns=cols)
    for c in ["Open","High","Low","Close","Volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


@router.get("/api/signal")
@limiter.limit(RATE_SIGNAL)
async def signal_scan(request: Request, symbol: str = "BTCUSDT",
                      primary_tf: str = "5m", confirm_tf: str = "1h"):
    from fastapi import HTTPException
    symbol     = clean_symbol(symbol)
    primary_tf = safe_interval(primary_tf)
    confirm_tf = safe_interval(confirm_tf)
    try:
        from signal_engine import SignalEngine
        client = _make_binance_client()

        def fetch_klines(sym, interval, limit=200):
            return _fetch_klines_df(client, sym, interval, limit)

        def get_funding_rate(sym: str) -> float:
            return float(client.mark_price(symbol=sym).get("lastFundingRate", 0))

        engine = SignalEngine(fetch_klines, get_funding_rate)
        sig    = engine.analyse(symbol.upper(), primary_tf, confirm_tf)

        if sig is None:
            return {"symbol": symbol.upper(), "has_signal": False,
                    "primary_tf": primary_tf, "confirm_tf": confirm_tf,
                    "message": "No high-confidence signal at this time"}

        return {
            "symbol":      sig.symbol, "has_signal":  True,
            "direction":   sig.direction.value, "confidence": sig.confidence,
            "price":       sig.price, "stop_loss":   sig.stop_loss,
            "take_profit": sig.take_profit, "atr":   sig.atr,
            "primary_tf":  sig.timeframe, "confirm_tf": confirm_tf,
            "reasons":     sig.reasons,
            "indicators":  {k: round(v, 6) if isinstance(v, float) else v
                            for k, v in sig.indicators.items()
                            if isinstance(v, (int, float, str, type(None)))},
            "ts": datetime.now().isoformat(),
        }
    except Exception as exc:
        api_log.error(f"Signal scan failed: {exc}")
        raise HTTPException(500, "Signal scan failed — see server logs")


@router.get("/api/signal/scan_multi")
@limiter.limit(RATE_SIGNAL)
async def scan_multi_signal(
    request: Request,
    symbols:    str = "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT,ADAUSDT,AVAXUSDT,LINKUSDT,DOTUSDT",
    primary_tf: str = "5m",
    confirm_tf: str = "1h",
):
    from fastapi import HTTPException
    syms       = [clean_symbol(s.strip()) for s in symbols.split(",") if s.strip()][:10]
    primary_tf = safe_interval(primary_tf)
    confirm_tf = safe_interval(confirm_tf)
    try:
        from signal_engine import SignalEngine
        client = _make_binance_client()

        def fetch_klines(sym, interval, limit=200):
            return _fetch_klines_df(client, sym, interval, limit)

        def get_funding_rate(sym: str) -> float:
            return float(client.mark_price(symbol=sym).get("lastFundingRate", 0))

        engine  = SignalEngine(fetch_klines, get_funding_rate)
        results = []
        for sym in syms:
            try:
                sig = engine.analyse(sym, primary_tf, confirm_tf)
                if sig:
                    results.append({
                        "symbol":      sig.symbol, "direction":   sig.direction.value,
                        "confidence":  sig.confidence, "price":   sig.price,
                        "stop_loss":   sig.stop_loss, "take_profit": sig.take_profit,
                        "atr":         sig.atr, "reasons":         sig.reasons[:3],
                    })
                else:
                    try: price = float(client.ticker_price(symbol=sym)["price"])
                    except Exception: price = 0.0
                    results.append({"symbol": sym, "direction": "FLAT", "confidence": 0, "price": price})
            except Exception as e:
                api_log.warning(f"Scan error for {sym}: {e}")
                results.append({"symbol": sym, "direction": "FLAT", "confidence": 0, "error": str(e)[:50]})

        active = [r for r in results if r.get("direction") not in ("FLAT", None)]
        return {
            "scanned":       len(syms), "signals_found": len(active),
            "results":       results, "primary_tf":    primary_tf,
            "confirm_tf":    confirm_tf, "ts":          datetime.now().isoformat(),
        }
    except Exception as exc:
        api_log.error(f"Multi-scan failed: {exc}")
        raise HTTPException(500, "Multi-scan failed — see server logs")
