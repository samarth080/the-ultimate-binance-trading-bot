"""News routes: news feed, signals, auto-trade toggle."""
from fastapi import Depends, HTTPException, Request
from fastapi.routing import APIRouter

from auth import require_auth
from shared import limiter, RATE_READ, RATE_TRADE, api_log, get_news_engine, safe_limit

router = APIRouter()


@router.get("/api/news")
@limiter.limit(RATE_READ)
async def get_news(request: Request, limit: int = 30):
    limit  = safe_limit(limit, 1, 100)
    engine = get_news_engine()
    if not engine:
        raise HTTPException(503, "News engine unavailable")
    items = engine.recent_news(limit)
    return {
        "auto_trade": engine._auto_trade,
        "count":      len(items),
        "items": [{
            "title":     n.title,
            "summary":   n.summary[:200],
            "source":    n.source,
            "url":       n.url,
            "published": n.published,
            "score":     n.score,
            "sentiment": n.sentiment,
            "symbols":   n.symbols,
            "ts":        n.ts,
        } for n in reversed(items)],
    }


@router.get("/api/news/signals")
@limiter.limit(RATE_READ)
async def get_news_signals(request: Request, limit: int = 20):
    limit  = safe_limit(limit, 1, 50)
    engine = get_news_engine()
    if not engine:
        raise HTTPException(503, "News engine unavailable")
    sigs = engine.recent_signals(limit)
    return {
        "auto_trade": engine._auto_trade,
        "count":      len(sigs),
        "signals": [{
            "symbol":    s.symbol,
            "direction": s.direction,
            "score":     s.score,
            "headline":  s.headline,
            "source":    s.source,
            "url":       s.url,
            "ts":        s.ts,
        } for s in reversed(sigs)],
    }


@router.post("/api/news/auto_trade")
@limiter.limit(RATE_TRADE)
async def set_auto_trade(request: Request, enabled: bool, _: str = Depends(require_auth)):
    engine = get_news_engine()
    if not engine:
        raise HTTPException(503, "News engine unavailable")
    engine.set_auto_trade(enabled)
    api_log.info(f"News auto-trade toggled: {'ENABLED' if enabled else 'DISABLED'}")
    return {"auto_trade": enabled, "message": f"News auto-trade {'ENABLED' if enabled else 'DISABLED'}"}
