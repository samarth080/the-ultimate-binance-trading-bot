"""Stats routes: trade stats, equity curve, risk status, logs, live positions."""
import os
from datetime import datetime

from fastapi import HTTPException, Request
from fastapi.routing import APIRouter

from shared import limiter, RATE_READ, api_log, get_client, log_buffer

router = APIRouter()


@router.get("/api/stats")
@limiter.limit(RATE_READ)
async def trade_stats(request: Request):
    try:
        from trade_tracker import TradeTracker
        from binance.um_futures import UMFutures

        tracker   = TradeTracker()
        stats     = tracker.get_stats()
        open_list = tracker.get_open_trades()
        recent    = tracker.get_closed_trades(limit=10)

        current_prices: dict = {}
        try:
            client = get_client()
            for t in open_list:
                if t.symbol not in current_prices:
                    current_prices[t.symbol] = float(client.ticker_price(symbol=t.symbol)["price"])
        except Exception:
            pass

        open_enriched    = []
        total_unrealised = 0.0
        for t in open_list:
            cp    = current_prices.get(t.symbol)
            unreal = None
            if cp and t.entry_price:
                unreal = (cp - t.entry_price if t.direction == "LONG" else t.entry_price - cp) * t.quantity
                total_unrealised += unreal
            open_enriched.append({
                "id": t.id, "symbol": t.symbol, "direction": t.direction,
                "entry": t.entry_price, "quantity": t.quantity, "current": cp,
                "unrealised_pnl": round(unreal, 4) if unreal is not None else None,
                "entry_time": t.entry_time,
            })

        return {
            "stats":            stats,
            "open_positions":   len(open_list),
            "total_unrealised": round(total_unrealised, 4),
            "open_trades":      open_enriched,
            "recent_trades": [{
                "symbol": t.symbol, "direction": t.direction,
                "entry":  t.entry_price, "exit": t.exit_price,
                "pnl":    t.pnl, "pnl_pct": t.pnl_pct,
                "reason": t.close_reason, "time": t.exit_time,
            } for t in recent],
        }
    except Exception as exc:
        api_log.error(f"Stats failed: {exc}")
        raise HTTPException(500, "Stats unavailable — see server logs")


@router.get("/api/stats/equity_curve")
@limiter.limit(RATE_READ)
async def equity_curve(request: Request):
    try:
        from trade_tracker import TradeTracker
        tracker = TradeTracker()
        trades  = list(reversed(tracker.get_closed_trades(limit=500)))
        cum     = 0.0
        points  = []
        for t in trades:
            cum += t.pnl or 0.0
            points.append({
                "time":   t.exit_time[:16] if t.exit_time else "",
                "pnl":    round(t.pnl or 0.0, 4),
                "cum":    round(cum, 4),
                "reason": t.close_reason or "",
                "symbol": t.symbol,
            })
        return {"points": points, "total": round(cum, 4)}
    except Exception as exc:
        api_log.error(f"Equity curve failed: {exc}")
        raise HTTPException(500, "Equity curve unavailable — see server logs")


@router.get("/api/risk/status")
@limiter.limit(RATE_READ)
async def risk_status(request: Request):
    try:
        from risk_manager import RiskManager
        return RiskManager().status()
    except Exception as exc:
        api_log.error(f"Risk status failed: {exc}")
        raise HTTPException(500, "Risk status unavailable — see server logs")


@router.get("/api/logs")
@limiter.limit(RATE_READ)
async def get_logs(request: Request, limit: int = 100):
    limit = max(1, min(limit, 500))
    return {"logs": list(log_buffer)[-limit:]}


@router.get("/api/positions/live")
@limiter.limit(RATE_READ)
async def live_binance_positions(request: Request):
    try:
        client   = get_client()
        account  = client.account()
        positions = [
            {
                "symbol":         p["symbol"],
                "side":           "LONG" if float(p["positionAmt"]) > 0 else "SHORT",
                "size":           abs(float(p["positionAmt"])),
                "entry_price":    float(p["entryPrice"]),
                "mark_price":     float(p.get("markPrice", p["entryPrice"])),
                "unrealised_pnl": round(float(p["unrealizedProfit"]), 4),
                "leverage":       int(p.get("leverage", 1)),
                "notional":       round(abs(float(p["positionAmt"])) * float(p.get("markPrice", p["entryPrice"])), 2),
            }
            for p in account.get("positions", [])
            if float(p.get("positionAmt", 0)) != 0
        ]
        total_unrealised = sum(pos["unrealised_pnl"] for pos in positions)
        return {
            "positions":        positions,
            "count":            len(positions),
            "total_unrealised": round(total_unrealised, 4),
            "ts":               datetime.now().isoformat(),
        }
    except Exception as exc:
        api_log.error(f"Live positions failed: {exc}")
        raise HTTPException(500, "Live positions unavailable — see server logs")
