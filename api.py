"""
Binance Bot API Server
FastAPI wrapper around the existing bot modules.

Requirements:
  pip install fastapi uvicorn[standard]

Usage (from project root):
  python api.py
  Then open http://localhost:8000
"""
import asyncio
import logging
import os
import sys
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Load .env BEFORE importing bot modules (they call sys.exit if keys missing) ──
from dotenv import find_dotenv, load_dotenv

_dotenv = find_dotenv(usecwd=True)
load_dotenv(_dotenv or (Path(__file__).parent / ".env"))

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
import uvicorn

# Add src/ to path so bot modules are importable
sys.path.insert(0, str(Path(__file__).parent / "src"))

# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(title="Binance Bot API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory log buffer ───────────────────────────────────────────────────────
log_buffer: deque = deque(maxlen=500)
_active_ws: List[WebSocket] = []


class _WSLogHandler(logging.Handler):
    """Appends records to the in-memory buffer for WebSocket delivery."""

    def emit(self, record: logging.LogRecord) -> None:
        entry = {
            "ts": datetime.now().strftime("%H:%M:%S"),
            "level": record.levelname,
            "msg": self.format(record),
        }
        log_buffer.append(entry)


_ws_handler = _WSLogHandler()
_ws_handler.setFormatter(logging.Formatter("%(name)s › %(message)s"))
_ws_handler.setLevel(logging.INFO)
logging.getLogger().addHandler(_ws_handler)
logging.getLogger().setLevel(logging.INFO)

api_log = logging.getLogger("bnce-api")

# ── Pydantic request models ────────────────────────────────────────────────────

class MarketOrderReq(BaseModel):
    symbol: str
    side: str
    quantity: float
    dry_run: bool = False


class LimitOrderReq(BaseModel):
    symbol: str
    side: str
    quantity: float
    price: float
    dry_run: bool = False


class OCOOrderReq(BaseModel):
    symbol: str
    side: str
    quantity: float
    price: float
    stop_price: float
    stop_limit_price: float
    dry_run: bool = False


class StopLimitOrderReq(BaseModel):
    symbol: str
    side: str
    quantity: float
    stop_price: float
    price: float
    dry_run: bool = False


class TWAPOrderReq(BaseModel):
    symbol: str
    side: str
    total_quantity: float
    parts: int
    interval_seconds: int
    dry_run: bool = False


# ── Lazy bot singletons ────────────────────────────────────────────────────────
_market_bot = None
_limit_bot = None


def _market() :
    global _market_bot
    if _market_bot is None:
        try:
            from market_orders import MarketOrderBot
            _market_bot = MarketOrderBot()
            api_log.info("MarketOrderBot ready")
        except SystemExit:
            raise HTTPException(503, "Bot exited during init — check API keys / .env")
        except Exception as exc:
            api_log.error(f"MarketOrderBot init failed: {exc}")
            raise HTTPException(503, str(exc))
    return _market_bot


def _limit():
    global _limit_bot
    if _limit_bot is None:
        try:
            from limit_orders import LimitOrderBot
            _limit_bot = LimitOrderBot()
            api_log.info("LimitOrderBot ready")
        except SystemExit:
            raise HTTPException(503, "Bot exited during init — check API keys / .env")
        except Exception as exc:
            api_log.error(f"LimitOrderBot init failed: {exc}")
            raise HTTPException(503, str(exc))
    return _limit_bot


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/api/status")
async def status():
    api_key = os.getenv("BINANCE_API_KEY", "")
    secret  = os.getenv("BINANCE_SECRET_KEY", "")
    testnet = os.getenv("USE_TESTNET", "true").lower() == "true"
    api_log.info(f"Status check — testnet={testnet} key_set={bool(api_key)}")
    return {
        "api_key_set":     bool(api_key),
        "secret_key_set":  bool(secret),
        "testnet":         testnet,
        "api_key_preview": (api_key[:8] + "…") if api_key else None,
        "timestamp":       datetime.now().isoformat(),
    }


@app.post("/api/order/market")
async def market_order(req: MarketOrderReq):
    api_log.info(f"MARKET {req.side} {req.quantity} {req.symbol} dry={req.dry_run}")
    bot = _market()
    if req.dry_run:
        sym = bot.validate_symbol(req.symbol.upper())
        qty = bot.validate_quantity(req.symbol.upper(), req.quantity) if sym else False
        return {"dry_run": True, "symbol_valid": sym, "quantity_valid": qty}
    result = bot.place_market_order(req.symbol, req.side, req.quantity)
    if not result:
        raise HTTPException(400, "Order failed — see logs")
    return {"success": True, "order": result}


@app.post("/api/order/limit")
async def limit_order(req: LimitOrderReq):
    api_log.info(f"LIMIT {req.side} {req.quantity} {req.symbol} @ {req.price} dry={req.dry_run}")
    bot = _limit()
    if req.dry_run:
        sym   = bot.validate_symbol(req.symbol.upper())
        qty   = bot.validate_quantity(req.symbol.upper(), req.quantity) if sym else False
        price = bot.validate_price(req.symbol.upper(), req.price)       if sym else False
        return {"dry_run": True, "symbol_valid": sym, "quantity_valid": qty, "price_valid": price}
    result = bot.place_limit_order(req.symbol, req.side, req.quantity, req.price)
    if not result:
        raise HTTPException(400, "Order failed — see logs")
    return {"success": True, "order": result}


@app.post("/api/order/oco")
async def oco_order(req: OCOOrderReq):
    api_log.info(f"OCO {req.side} {req.quantity} {req.symbol} dry={req.dry_run}")
    try:
        from advanced.oco import BinanceOCOBot
        bot = BinanceOCOBot()
        bot.place_oco_order(
            req.symbol, req.side, req.quantity,
            req.price, req.stop_price, req.stop_limit_price,
            dry_run=req.dry_run,
        )
        return {"success": True, "dry_run": req.dry_run}
    except SystemExit:
        raise HTTPException(503, "OCO bot could not connect — check keys")
    except Exception as exc:
        api_log.error(f"OCO error: {exc}")
        raise HTTPException(500, str(exc))


@app.post("/api/order/stop_limit")
async def stop_limit_order(req: StopLimitOrderReq):
    api_log.info(f"STOP-LIMIT {req.side} {req.quantity} {req.symbol} stop={req.stop_price} lim={req.price}")
    try:
        from binance.client import Client
        from advanced.stop_limit_orders import StopLimitOrderHandler

        client = Client(
            api_key=os.getenv("BINANCE_API_KEY"),
            api_secret=os.getenv("BINANCE_SECRET_KEY"),
            testnet=True,
        )
        handler = StopLimitOrderHandler(client, api_log)

        if req.dry_run:
            valid = handler.validate_stop_limit_params(
                req.symbol.upper(), req.side.upper(),
                req.quantity, req.stop_price, req.price,
            )
            return {"dry_run": True, "valid": valid}

        result = handler.place_stop_limit_order(
            req.symbol.upper(), req.side.upper(),
            req.quantity, req.stop_price, req.price,
        )
        if not result:
            raise HTTPException(400, "Stop-limit order failed — see logs")
        return {"success": True, "order": result}
    except HTTPException:
        raise
    except Exception as exc:
        api_log.error(f"Stop-limit error: {exc}")
        raise HTTPException(500, str(exc))


@app.post("/api/order/twap")
async def twap_order(req: TWAPOrderReq):
    """Splits total_quantity into `parts` market orders spaced `interval_seconds` apart."""
    part_qty = req.total_quantity / req.parts
    api_log.info(f"TWAP {req.parts}× {part_qty:.6f} {req.symbol} every {req.interval_seconds}s dry={req.dry_run}")

    if req.dry_run:
        return {
            "dry_run": True,
            "plan": f"{req.parts} orders × {part_qty:.6f} {req.symbol} every {req.interval_seconds}s",
        }

    bot = _market()
    executed, errors = 0, []
    for i in range(req.parts):
        api_log.info(f"TWAP [{i+1}/{req.parts}] {req.side} {part_qty} {req.symbol}")
        result = bot.place_market_order(req.symbol, req.side, part_qty)
        if result:
            executed += 1
        else:
            errors.append(f"part {i+1} failed")
        if i < req.parts - 1:
            await asyncio.sleep(req.interval_seconds)

    return {"success": executed == req.parts, "parts_executed": executed, "errors": errors}


@app.get("/api/ml/analyze")
async def ml_analyze(symbol: str = "BTCUSDT", interval: str = "1m"):
    try:
        import pandas as pd
        from binance.um_futures import UMFutures

        client = UMFutures(
            key=os.getenv("BINANCE_API_KEY"),
            secret=os.getenv("BINANCE_SECRET_KEY"),
            base_url="https://testnet.binancefuture.com",
        )

        klines = client.klines(symbol, interval, limit=50)
        cols = ["OpenTime","Open","High","Low","Close","Volume",
                "CloseTime","QuoteVol","Trades","TakerBase","TakerQuote","Ignore"]
        df = pd.DataFrame(klines, columns=cols)
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

        delta = close.diff()
        gain  = delta.where(delta > 0, 0).rolling(14).mean()
        loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi   = float(100 - 100 / (1 + (gain / loss).iloc[-1]))

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

        api_log.info(f"ML {symbol}: ${current:,.2f} RSI={rsi:.1f} MACD={macd:+.2f}")

        return {
            "symbol":          symbol,
            "price":           current,
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
            "candles": candles,
            "ts": datetime.now().isoformat(),
        }
    except Exception as exc:
        api_log.error(f"ML analysis failed: {exc}")
        raise HTTPException(500, str(exc))


@app.get("/api/logs")
async def get_logs(limit: int = 100):
    return {"logs": list(log_buffer)[-limit:]}


# ── WebSocket — streams buffered log entries ───────────────────────────────────
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    _active_ws.append(ws)
    api_log.info("WebSocket client connected")

    # Send buffered history
    await ws.send_json({"type": "init", "data": list(log_buffer)[-50:]})

    last_sent = len(log_buffer)
    try:
        while True:
            await asyncio.sleep(1)
            current_len = len(log_buffer)
            if current_len > last_sent:
                new_entries = list(log_buffer)[last_sent:current_len]
                for entry in new_entries:
                    await ws.send_json({"type": "log", "data": entry})
                last_sent = current_len
            else:
                await ws.send_json({"type": "ping"})
    except (WebSocketDisconnect, Exception):
        if ws in _active_ws:
            _active_ws.remove(ws)
        api_log.info("WebSocket client disconnected")


# ── Serve frontend ─────────────────────────────────────────────────────────────
@app.get("/")
async def serve_frontend():
    path = Path(__file__).parent / "frontend" / "index.html"
    if path.exists():
        return FileResponse(str(path))
    return HTMLResponse(
        "<pre style='font-family:monospace;padding:20px'>frontend/index.html not found.\n"
        "Place the HTML file at: frontend/index.html</pre>",
        status_code=404,
    )


if __name__ == "__main__":
    print("  BNCE//TERMINAL API")
    print(f"  http://localhost:8000\n")
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=False, log_level="info")
