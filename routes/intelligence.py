"""Intelligence routes: journal, SOUL editor, Kelly criterion."""
from fastapi import Depends, HTTPException, Request
from fastapi.routing import APIRouter

from auth import require_auth
from shared import limiter, RATE_READ, RATE_TRADE, api_log, get_intel

router = APIRouter()


@router.get("/api/journal")
@limiter.limit(RATE_READ)
async def get_journal(request: Request, limit: int = 100):
    from shared import safe_limit
    limit = safe_limit(limit, 1, 500)
    try:
        intel = get_intel()
        return {
            "stats":        intel.get_journal_stats(),
            "rows":         intel.get_journal_rows(limit=limit),
            "kelly_active": intel.kelly_active,
        }
    except Exception as exc:
        api_log.error(f"Journal fetch failed: {exc}")
        raise HTTPException(500, "Journal unavailable — see server logs")


@router.get("/api/soul")
@limiter.limit(RATE_READ)
async def get_soul(request: Request):
    try:
        return {"text": get_intel().read_soul()}
    except Exception as exc:
        api_log.error(f"SOUL read failed: {exc}")
        raise HTTPException(500, "SOUL unavailable — see server logs")


@router.post("/api/soul")
@limiter.limit(RATE_TRADE)
async def update_soul(request: Request, payload: dict, _: str = Depends(require_auth)):
    text = payload.get("text", "")
    if not text.strip():
        raise HTTPException(400, "Empty SOUL text rejected")
    try:
        get_intel().update_soul(text)
        api_log.info("SOUL.md updated via API")
        return {"ok": True}
    except Exception as exc:
        api_log.error(f"SOUL update failed: {exc}")
        raise HTTPException(500, "SOUL update failed — see server logs")


@router.get("/api/kelly")
@limiter.limit(RATE_READ)
async def get_kelly(request: Request):
    try:
        intel    = get_intel()
        stats    = intel.get_journal_stats()
        from risk_manager import RiskManager
        rm_state = RiskManager()._state
        equity   = float(rm_state.get("peak_equity") or 10000.0)
        peak     = float(rm_state.get("peak_equity") or equity)
        drawdown = (peak - equity) / peak if peak > 0 else 0.0
        next_size = intel.compute_kelly_size(equity, 80, "TRENDING", drawdown)
        return {
            "kelly_active":   intel.kelly_active,
            "trade_count":    stats["trade_count"],
            "win_rate":       stats["win_rate"],
            "avg_rr":         stats["avg_rr"],
            "next_size_usdt": next_size,
            "equity":         equity,
            "drawdown":       round(drawdown, 4),
        }
    except Exception as exc:
        api_log.error(f"Kelly fetch failed: {exc}")
        raise HTTPException(500, "Kelly unavailable — see server logs")
