from datetime import datetime, timezone

import pytest

from backtesting.portfolio import PortfolioBook
from backtesting.types import Fill, Position, Bar


def test_portfolio_initial_state():
    book = PortfolioBook(initial_capital=10_000.0)
    assert book.cash == 10_000.0
    assert book.get_equity() == 10_000.0
    assert len(book.get_open_positions()) == 0


def test_process_fill_entry_long_deducts_cash():
    book = PortfolioBook(10_000.0)
    pos = Position("BTCUSDT", "LONG", 1.0, 50000.0, 49000.0, 52000.0,
                   datetime.now(timezone.utc), 10.0, 500.0, 1)
    fill = Fill("BTCUSDT", "BUY", 1.0, 50000.0, 10.0, datetime.now(timezone.utc), "ENTRY")
    
    book.add_position(pos)
    book.process_fill(fill)
    
    # 50,000 cost + 10 fee
    assert book.cash == pytest.approx(10_000.0 - 50_010.0)
    # Equity unchanged at moment of fill (value of asset = 50,000, cash = -40,010 => eq = 9,990, minus fees)
    assert book.get_open_positions()[0].symbol == "BTCUSDT"


def test_process_fill_entry_short_adds_cash():
    book = PortfolioBook(10_000.0)
    pos = Position("BTCUSDT", "SHORT", 1.0, 50000.0, 51000.0, 48000.0,
                   datetime.now(timezone.utc), 10.0, 500.0, 1)
    fill = Fill("BTCUSDT", "SELL", 1.0, 50000.0, 10.0, datetime.now(timezone.utc), "ENTRY")
    
    book.add_position(pos)
    book.process_fill(fill)
    
    # Received 50,000, paid 10
    assert book.cash == pytest.approx(10_000.0 + 49_990.0)


def test_update_equity_long_position():
    book = PortfolioBook(10_000.0)
    pos = Position("BTCUSDT", "LONG", 1.0, 50000.0, 49000.0, 52000.0,
                   datetime.now(timezone.utc), 10.0, 500.0, 1)
    book.add_position(pos)
    # Give it fake cash for simplicity
    book.cash = 0.0 
    
    # Current MTM at 51,000
    bar = Bar("BTCUSDT", "5m", datetime.now(timezone.utc), 51000, 51000, 51000, 51000, 1.0)
    book.update_mtm({"BTCUSDT": bar})
    
    # Equity = Cash(0) + Long Value(51,000)
    assert book.get_equity() == 51000.0


def test_update_equity_short_position():
    book = PortfolioBook(10_000.0)
    pos = Position("BTCUSDT", "SHORT", 1.0, 50000.0, 51000.0, 48000.0,
                   datetime.now(timezone.utc), 10.0, 500.0, 1)
    book.add_position(pos)
    # Provide the margin cash the short sale would have generated
    book.cash = 60000.0 
    
    # Current MTM at 48,000
    bar = Bar("BTCUSDT", "5m", datetime.now(timezone.utc), 48000, 48000, 48000, 48000, 1.0)
    book.update_mtm({"BTCUSDT": bar})
    
    # Equity = Cash(60,000) - Short Liability(48,000)
    assert book.get_equity() == 12000.0


def test_process_fill_exit_removes_position():
    book = PortfolioBook(10_000.0)
    pos = Position("BTCUSDT", "LONG", 1.0, 50000.0, 49000.0, 52000.0,
                   datetime.now(timezone.utc), 10.0, 500.0, 1)
    book.add_position(pos)
    
    # Exit Long (SELL)
    fill = Fill("BTCUSDT", "SELL", 1.0, 52000.0, 15.0, datetime.now(timezone.utc), "TP")
    book.process_fill(fill)
    
    assert len(book.get_open_positions()) == 0
    # Cash += 52000 - 15 = 51985
    assert book.cash == 10_000.0 + 51985.0
