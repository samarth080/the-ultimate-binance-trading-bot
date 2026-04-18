# tests/test_intelligence.py
import pytest, sqlite3, os, tempfile
from pathlib import Path
from src.intelligence import IntelligenceEngine, TradeRecord, NearMissRecord

@pytest.fixture
def engine(tmp_path):
    soul = tmp_path / "SOUL.md"
    db   = tmp_path / "intel.db"
    return IntelligenceEngine(soul_path=soul, db_path=db)

def test_soul_created_with_defaults(engine, tmp_path):
    soul = tmp_path / "SOUL.md"
    assert soul.exists()
    assert "Risk Rules" in soul.read_text()

def test_kelly_inactive_below_20_trades(engine):
    assert engine.kelly_active is False
    result = engine.compute_kelly_size(equity=10000, confidence=80, regime="TRENDING", current_drawdown=0.0)
    assert result is None

def test_kelly_activates_after_20_trades(engine):
    for i in range(20):
        engine.record_close(TradeRecord(
            symbol="BTCUSDT", direction="LONG", regime="TRENDING", tier="TIER_1",
            confidence=75.0, indicators_fired="ST,MACD,RSI",
            entry_price=50000.0, exit_reason="TP", pnl=100.0, rr_actual=2.0,
            session_date="2026-01-01"
        ))
    assert engine.kelly_active is True

def test_kelly_formula_happy_path(engine):
    # Seed 20 trades: 10 wins (+2R), 10 losses (-1R)
    for i in range(10):
        engine.record_close(TradeRecord("BTC","LONG","TRENDING","TIER_1",75,"ST",50000,"TP",200,2.0,"2026-01-01"))
    for i in range(10):
        engine.record_close(TradeRecord("BTC","LONG","TRENDING","TIER_1",75,"ST",50000,"SL",-100,1.0,"2026-01-01"))
    size = engine.compute_kelly_size(10000, 80, "TRENDING", 0.0)
    assert size is not None
    assert 0 < size <= 500  # hard cap 5% = $500

def test_kelly_drawdown_multiplier(engine):
    for i in range(10):
        engine.record_close(TradeRecord("BTC","LONG","TRENDING","TIER_1",75,"ST",50000,"TP",200,2.0,"2026-01-01"))
    for i in range(10):
        engine.record_close(TradeRecord("BTC","LONG","TRENDING","TIER_1",75,"ST",50000,"SL",-100,1.0,"2026-01-01"))
    size_healthy = engine.compute_kelly_size(10000, 80, "TRENDING", 0.0)
    size_drawdown = engine.compute_kelly_size(10000, 80, "TRENDING", 0.09)
    assert size_drawdown < size_healthy * 0.3  # 0.25x multiplier at >=8% drawdown

def test_near_miss_recorded(engine):
    engine.record_near_miss(NearMissRecord(
        symbol="ETHUSDT", regime="VOLATILE", confidence=55.0,
        indicators="ST,RSI", entry_price_at_skip=3000.0, session_date="2026-01-01"
    ))
    rows = engine._db_fetchall("SELECT * FROM near_misses")
    assert len(rows) == 1

def test_lesson_extracted_volatile_win_rate(engine):
    # 3 wins 17 losses in VOLATILE = 15% win rate < 35%
    for i in range(3):
        engine.record_close(TradeRecord("BTC","LONG","VOLATILE","TIER_2",65,"ST",50000,"TP",100,2.0,"2026-01-01"))
    for i in range(17):
        engine.record_close(TradeRecord("BTC","LONG","VOLATILE","TIER_2",65,"ST",50000,"SL",-100,1.0,"2026-01-01"))
    lessons = engine.get_recent_lessons(10)
    texts = [l["rule_text"] for l in lessons]
    assert any("TIER_1 only in VOLATILE" in t for t in texts)

def test_get_active_soul_returns_dict(engine):
    soul = engine.get_active_soul()
    assert isinstance(soul, dict)
    assert "skip_volatile_tier2" in soul

def test_journal_rows_and_stats(engine):
    engine.record_close(TradeRecord("BTC","LONG","TRENDING","TIER_1",80,"ST,MACD",50000,"TP",150,2.5,"2026-01-01"))
    rows = engine.get_journal_rows(limit=10)
    assert len(rows) == 1
    stats = engine.get_journal_stats()
    assert stats["trade_count"] == 1
