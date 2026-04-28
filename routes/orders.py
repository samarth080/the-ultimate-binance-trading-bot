"""Order routes: market, limit, OCO, stop-limit, TWAP."""
import os
import asyncio
import threading
import time

from fastapi import Depends, Request
from fastapi.routing import APIRouter
from pydantic import BaseModel, field_validator

from auth import require_auth
from shared import (
    limiter, RATE_TRADE, RATE_TWAP,
    api_log, get_client, get_market_bot, get_limit_bot,
    record_fill, clean_symbol, clean_side, safe_qty, positive,
)

router = APIRouter()


# ── Pydantic request models ────────────────────────────────────────────────────

class MarketOrderReq(BaseModel):
    symbol:   str
    side:     str
    quantity: float
    dry_run:  bool = False

    @field_validator("symbol")
    @classmethod
    def val_symbol(cls, v): return clean_symbol(v)
    @field_validator("side")
    @classmethod
    def val_side(cls, v): return clean_side(v)
    @field_validator("quantity")
    @classmethod
    def val_qty(cls, v): return safe_qty(v)


class LimitOrderReq(BaseModel):
    symbol:   str
    side:     str
    quantity: float
    price:    float
    dry_run:  bool = False

    @field_validator("symbol")
    @classmethod
    def val_symbol(cls, v): return clean_symbol(v)
    @field_validator("side")
    @classmethod
    def val_side(cls, v): return clean_side(v)
    @field_validator("quantity")
    @classmethod
    def val_qty(cls, v): return safe_qty(v)
    @field_validator("price")
    @classmethod
    def val_price(cls, v): return positive(v, "price")


class OCOOrderReq(BaseModel):
    symbol:           str
    side:             str
    quantity:         float
    price:            float
    stop_price:       float
    stop_limit_price: float
    dry_run:          bool = False

    @field_validator("symbol")
    @classmethod
    def val_symbol(cls, v): return clean_symbol(v)
    @field_validator("side")
    @classmethod
    def val_side(cls, v): return clean_side(v)
    @field_validator("quantity")
    @classmethod
    def val_qty(cls, v): return safe_qty(v)
    @field_validator("price", "stop_price", "stop_limit_price")
    @classmethod
    def val_prices(cls, v): return positive(v, "price field")


class StopLimitOrderReq(BaseModel):
    symbol:     str
    side:       str
    quantity:   float
    stop_price: float
    price:      float
    dry_run:    bool = False

    @field_validator("symbol")
    @classmethod
    def val_symbol(cls, v): return clean_symbol(v)
    @field_validator("side")
    @classmethod
    def val_side(cls, v): return clean_side(v)
    @field_validator("quantity")
    @classmethod
    def val_qty(cls, v): return safe_qty(v)
    @field_validator("price", "stop_price")
    @classmethod
    def val_prices(cls, v): return positive(v, "price field")


class TWAPOrderReq(BaseModel):
    symbol:           str
    side:             str
    total_quantity:   float
    parts:            int
    interval_seconds: int
    dry_run:          bool = False

    @field_validator("symbol")
    @classmethod
    def val_symbol(cls, v): return clean_symbol(v)
    @field_validator("side")
    @classmethod
    def val_side(cls, v): return clean_side(v)
    @field_validator("total_quantity")
    @classmethod
    def val_qty(cls, v): return safe_qty(v)
    @field_validator("parts")
    @classmethod
    def val_parts(cls, v):
        if not (1 <= v <= 20):
            raise ValueError("parts must be between 1 and 20")
        return v
    @field_validator("interval_seconds")
    @classmethod
    def val_interval(cls, v):
        if not (5 <= v <= 3600):
            raise ValueError("interval_seconds must be between 5 and 3600")
        return v


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/api/order/market")
@limiter.limit(RATE_TRADE)
async def market_order(request: Request, req: MarketOrderReq, _: str = Depends(require_auth)):
    api_log.info(f"MARKET {req.side} {req.quantity} {req.symbol} dry={req.dry_run}")
    bot = get_market_bot()
    if req.dry_run:
        sym = bot.validate_symbol(req.symbol.upper())
        qty = bot.validate_quantity(req.symbol.upper(), req.quantity) if sym else False
        return {"dry_run": True, "symbol_valid": sym, "quantity_valid": qty}
    result = bot.place_market_order(req.symbol, req.side, req.quantity)
    if not result:
        raise Exception(400, "Order failed — see logs")
    avg_price = float(result.get("avgPrice") or result.get("price") or 0)
    record_fill(req.symbol, req.side, req.quantity, avg_price, result.get("orderId", ""))
    return {"success": True, "order": result}


@router.post("/api/order/limit")
@limiter.limit(RATE_TRADE)
async def limit_order(request: Request, req: LimitOrderReq, _: str = Depends(require_auth)):
    api_log.info(f"LIMIT {req.side} {req.quantity} {req.symbol} @ {req.price} dry={req.dry_run}")
    bot = get_limit_bot()
    if req.dry_run:
        sym   = bot.validate_symbol(req.symbol.upper())
        qty   = bot.validate_quantity(req.symbol.upper(), req.quantity) if sym else False
        price = bot.validate_price(req.symbol.upper(), req.price)       if sym else False
        return {"dry_run": True, "symbol_valid": sym, "quantity_valid": qty, "price_valid": price}
    result = bot.place_limit_order(req.symbol, req.side, req.quantity, req.price)
    if not result:
        raise Exception(400, "Order failed — see logs")
    if result.get("status", "") in ("FILLED", "PARTIALLY_FILLED"):
        record_fill(req.symbol, req.side, req.quantity, req.price, result.get("orderId", ""))
    return {"success": True, "order": result}


@router.post("/api/order/oco")
@limiter.limit(RATE_TRADE)
async def oco_order(request: Request, req: OCOOrderReq, _: str = Depends(require_auth)):
    api_log.info(f"OCO {req.side} {req.quantity} {req.symbol} dry={req.dry_run}")
    try:
        from advanced.oco import BinanceOCOBot
        bot    = BinanceOCOBot()
        result = bot.place_oco_order(
            req.symbol, req.side, req.quantity,
            req.price, req.stop_price, req.stop_limit_price,
            dry_run=req.dry_run,
        )
        return {"success": True, "dry_run": req.dry_run, "legs": result}
    except SystemExit:
        raise Exception(503, "OCO bot could not connect — check keys")
    except Exception as exc:
        api_log.error(f"OCO error: {exc}")
        raise Exception(500, "OCO order failed — see server logs")


@router.post("/api/order/stop_limit")
@limiter.limit(RATE_TRADE)
async def stop_limit_order(request: Request, req: StopLimitOrderReq, _: str = Depends(require_auth)):
    from fastapi import HTTPException
    api_log.info(f"STOP-LIMIT {req.side} {req.quantity} {req.symbol} stop={req.stop_price} lim={req.price}")

    notional = req.quantity * req.price
    if notional < 100:
        min_qty = round(100 / req.price * 1.05, 3)
        raise HTTPException(400,
            f"Order notional ${notional:.2f} is below the $100 Binance Futures minimum. "
            f"Increase quantity to at least {min_qty} at this price.")

    try:
        from binance.um_futures import UMFutures
        from advanced.stop_limit_orders import StopLimitOrderHandler

        use_testnet = os.getenv("USE_TESTNET", "true").lower() == "true"
        base_url    = "https://testnet.binancefuture.com" if use_testnet else "https://fapi.binance.com"
        client      = UMFutures(key=os.getenv("BINANCE_API_KEY"), secret=os.getenv("BINANCE_SECRET_KEY"), base_url=base_url)
        handler     = StopLimitOrderHandler(client, api_log)

        if req.dry_run:
            valid = handler.validate_stop_limit_params(
                req.symbol.upper(), req.side.upper(), req.quantity, req.stop_price, req.price)
            return {"dry_run": True, "valid": valid, "notional": round(notional, 2)}

        symbol_u = req.symbol.upper()
        side_u   = req.side.upper()
        stop_px  = req.stop_price
        qty      = req.quantity

        def _monitor_stop():
            sell_side = side_u == "SELL"
            api_log.info(f"STP monitor started: {symbol_u} {side_u} qty={qty} stop={stop_px}")
            deadline = time.time() + 3600
            while time.time() < deadline:
                try:
                    mark      = float(client.mark_price(symbol=symbol_u)["markPrice"])
                    triggered = (sell_side and mark <= stop_px) or (not sell_side and mark >= stop_px)
                    if triggered:
                        api_log.info(f"STP triggered: mark={mark} crossed stop={stop_px} — firing MARKET")
                        client.new_order(symbol=symbol_u, side=side_u, type="MARKET", quantity=qty)
                        return
                except Exception as e:
                    api_log.error(f"STP monitor error: {e}")
                time.sleep(5)
            api_log.warning(f"STP monitor timed out for {symbol_u}")

        threading.Thread(target=_monitor_stop, daemon=True).start()
        return {
            "success": True, "type": "STOP_MONITORED", "symbol": symbol_u,
            "side": side_u, "quantity": qty, "stop_price": stop_px, "limit_price": req.price,
            "note": "Testnet: server monitors mark price and fires MARKET when stop is hit",
        }
    except HTTPException:
        raise
    except Exception as exc:
        msg = str(exc)
        if "-4164" in msg or "notional" in msg.lower():
            min_qty = round(100 / req.price * 1.05, 3)
            raise HTTPException(400,
                f"Notional too small (${notional:.2f} < $100 minimum). Use quantity ≥ {min_qty}.")
        api_log.error(f"Stop-limit error: {exc}")
        raise HTTPException(500, "Stop-limit order failed — see server logs")


@router.post("/api/order/twap")
@limiter.limit(RATE_TWAP)
async def twap_order(request: Request, req: TWAPOrderReq, _: str = Depends(require_auth)):
    part_qty = req.total_quantity / req.parts
    api_log.info(f"TWAP {req.parts}× {part_qty:.6f} {req.symbol} every {req.interval_seconds}s dry={req.dry_run}")

    if req.dry_run:
        return {"dry_run": True,
                "plan": f"{req.parts} orders × {part_qty:.6f} {req.symbol} every {req.interval_seconds}s"}

    bot       = get_market_bot()
    executed, errors = 0, []
    total_value = 0.0
    for i in range(req.parts):
        api_log.info(f"TWAP [{i+1}/{req.parts}] {req.side} {part_qty} {req.symbol}")
        result = bot.place_market_order(req.symbol, req.side, part_qty)
        if result:
            executed    += 1
            fill_price   = float(result.get("avgPrice") or result.get("price") or 0)
            total_value += fill_price * part_qty
        else:
            errors.append(f"part {i+1} failed")
        if i < req.parts - 1:
            await asyncio.sleep(req.interval_seconds)

    if executed > 0:
        avg_fill = total_value / (part_qty * executed)
        record_fill(req.symbol, req.side, part_qty * executed, avg_fill)

    return {"success": executed == req.parts, "parts_executed": executed, "errors": errors}
