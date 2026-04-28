"""
Binance Bot API Server — entry point.
Loads .env, wires up all routers, and serves the frontend.

Usage:
  uvicorn api:app --reload
  python api.py
"""
import asyncio
import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

_dotenv = find_dotenv(usecwd=True)
load_dotenv(_dotenv or (Path(__file__).parent / ".env"))

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from shared import limiter, daily_summary_loop, api_log, get_news_engine
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

import auth
import routes.orders       as orders
import routes.market_data  as market_data
import routes.stats        as stats
import routes.intelligence as intelligence
import routes.news         as news
import routes.backtest     as backtest

# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(title="Binance Bot API", version="1.0.0", docs_url=None, redoc_url=None)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS — restrict to localhost only ─────────────────────────────────────────
_ALLOWED_ORIGINS = [o.strip() for o in
    os.getenv("ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ── Routers ────────────────────────────────────────────────────────────────────
for mod in [auth, orders, market_data, stats, intelligence, news, backtest]:
    app.include_router(mod.router)

# ── Static files (CSS, JS) ────────────────────────────────────────────────────
_frontend_dir = Path(__file__).parent / "frontend"
app.mount("/static", StaticFiles(directory=str(_frontend_dir)), name="static")

# ── WebSocket endpoints ────────────────────────────────────────────────────────
from fastapi import WebSocket, WebSocketDisconnect
from shared import log_buffer, active_ws, get_client


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    active_ws.append(ws)
    api_log.info("WebSocket client connected")
    await ws.send_json({"type": "init", "data": list(log_buffer)[-50:]})
    last_sent = len(log_buffer)
    try:
        while True:
            await asyncio.sleep(1)
            current_len = len(log_buffer)
            if current_len > last_sent:
                for entry in list(log_buffer)[last_sent:current_len]:
                    await ws.send_json({"type": "log", "data": entry})
                last_sent = current_len
            else:
                tick = {"type": "ping"}
                try:
                    positions = get_client().get_position_risk(recvWindow=5000)
                    upnl = sum(
                        float(p.get("unrealizedProfit", 0))
                        for p in positions if float(p.get("positionAmt", 0)) != 0
                    )
                    tick["upnl"] = round(upnl, 2)
                except Exception:
                    tick["upnl"] = None
                await ws.send_json(tick)
    except (WebSocketDisconnect, Exception):
        if ws in active_ws:
            active_ws.remove(ws)
        api_log.info("WebSocket client disconnected")


@app.websocket("/ws/log")
async def ws_log_endpoint(ws: WebSocket):
    await ws.accept()
    active_ws.append(ws)
    api_log.info("WS/log client connected")
    last_sent = len(log_buffer)
    try:
        while True:
            await asyncio.sleep(1)
            current_len = len(log_buffer)
            if current_len > last_sent:
                for entry in list(log_buffer)[last_sent:current_len]:
                    await ws.send_json({
                        "type": entry.get("level", "INFO"),
                        "msg":  entry.get("msg", ""),
                        "ts":   entry.get("ts", ""),
                    })
                last_sent = current_len
            else:
                await ws.send_json({"type": "ping", "msg": "", "ts": ""})
    except (WebSocketDisconnect, Exception):
        if ws in active_ws:
            active_ws.remove(ws)
        api_log.info("WS/log client disconnected")


# ── Startup ────────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def _startup():
    if os.getenv("NEWS_ENGINE", "false").lower() == "true":
        get_news_engine()
    else:
        api_log.info("NewsEngine disabled — set NEWS_ENGINE=true in .env to enable")
    asyncio.create_task(daily_summary_loop())


# ── Serve frontend ─────────────────────────────────────────────────────────────
@app.get("/")
async def serve_frontend():
    path = _frontend_dir / "index.html"
    if path.exists():
        return FileResponse(str(path))
    return HTMLResponse(
        "<pre style='font-family:monospace;padding:20px'>frontend/index.html not found.</pre>",
        status_code=404,
    )


if __name__ == "__main__":
    print("  BNCE//TERMINAL API")
    print("  http://localhost:8000\n")
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=False, log_level="info")
