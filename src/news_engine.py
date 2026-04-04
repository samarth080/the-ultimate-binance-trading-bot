"""
News Engine — RSS-based crypto news fetcher with keyword sentiment analysis.

Architecture:
  1. Polls multiple RSS feeds every POLL_INTERVAL seconds
  2. Scores each headline with weighted keyword matching (-100 to +100)
  3. Maps article symbols (Bitcoin → BTCUSDT, etc.)
  4. Emits a NewsSignal when |score| >= SIGNAL_THRESHOLD
  5. Deduplicates articles by URL hash so each headline fires once

No external API key required — uses free RSS feeds.
"""

import calendar
import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Callable, Dict, List, Optional
from collections import deque

import feedparser
import requests as _requests

_HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CryptoNewsBot/1.0)"}
_HTTP_TIMEOUT = 10

logger = logging.getLogger(__name__)

# ── RSS feeds ────────────────────────────────────────────────────────────────
RSS_FEEDS = [
    ("CoinDesk",       "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("CoinTelegraph",  "https://cointelegraph.com/rss"),
    ("Decrypt",        "https://decrypt.co/feed"),
    ("Bitcoin Mag",    "https://bitcoinmagazine.com/feed"),
    ("The Block",      "https://www.theblock.co/rss.xml"),
]

POLL_INTERVAL        = 30    # seconds between feed polls (was 120 — faster = fresher news)
MAX_ARTICLE_AGE_MIN  = 10   # ignore articles older than this many minutes
SYMBOL_COOLDOWN_SEC  = 120  # don't fire two signals on the same symbol within this window

# ── Keyword sentiment weights ─────────────────────────────────────────────────
BULLISH_KEYWORDS: Dict[str, int] = {
    "rally":           15,
    "surge":           15,
    "bullish":         20,
    "breakout":        18,
    "all-time high":   25,
    " ath":            20,
    "buy":              8,
    "adoption":        12,
    "partnership":     10,
    "upgrade":         10,
    "institutional":   15,
    "etf approved":    30,
    " etf":            15,
    "launch":           8,
    "listing":         10,
    "recovery":        10,
    "bounce":          12,
    "accumulate":      12,
    "support held":    10,
    "buy signal":      20,
    "positive":         8,
    "inflows":         12,
    "record high":     22,
    "spot etf":        25,
    "approved":        12,
    "outperform":      12,
    "milestone":        8,
    "new high":        18,
    "moon":             8,
    "soar":            15,
    "skyrocket":       18,
}

BEARISH_KEYWORDS: Dict[str, int] = {
    "crash":          -20,
    "hack":           -25,
    " ban":           -20,
    "banned":         -20,
    "bearish":        -20,
    "dump":           -18,
    "lawsuit":        -15,
    " sec ":          -12,
    "fraud":          -25,
    "sell-off":       -18,
    "plunge":         -20,
    "collapse":       -25,
    "exploit":        -25,
    "vulnerability":  -15,
    "delisted":       -20,
    "outflows":       -12,
    "regulatory":     -10,
    "investigation":  -15,
    "scam":           -22,
    "rug pull":       -25,
    "liquidat":       -15,
    "warning":        -12,
    "concern":         -8,
    "fear":           -10,
    "risk":            -8,
    "bearish":        -20,
    "short":           -8,
    "resistance":      -8,
    "rejected":       -15,
    "down":            -8,
    "loss":           -10,
    "drop":           -12,
    "fell":           -10,
    "slump":          -12,
    "sink":           -12,
}

# ── Symbol extraction ─────────────────────────────────────────────────────────
# Maps keywords found in headlines → Binance futures symbol
COIN_MAP: Dict[str, str] = {
    "bitcoin":   "BTCUSDT",
    " btc":      "BTCUSDT",
    "ethereum":  "ETHUSDT",
    " eth":      "ETHUSDT",
    "solana":    "SOLUSDT",
    " sol ":     "SOLUSDT",
    "bnb":       "BNBUSDT",
    "ripple":    "XRPUSDT",
    " xrp":      "XRPUSDT",
    "cardano":   "ADAUSDT",
    " ada":      "ADAUSDT",
    "dogecoin":  "DOGEUSDT",
    "doge":      "DOGEUSDT",
    "avalanche": "AVAXUSDT",
    " avax":     "AVAXUSDT",
    "chainlink": "LINKUSDT",
    " link":     "LINKUSDT",
}

SIGNAL_THRESHOLD  = 30    # |score| must exceed this to emit a trade signal
MAX_RECENT_NEWS   = 100   # news items to keep in memory


@dataclass
class NewsItem:
    title:      str
    summary:    str
    source:     str
    url:        str
    published:  str
    score:      float           # -100 to +100
    sentiment:  str             # BULLISH / BEARISH / NEUTRAL
    symbols:    List[str]       # e.g. ["BTCUSDT"]
    uid:        str             # hash of URL for dedup
    ts:         str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class NewsSignal:
    """Actionable signal emitted when a news item exceeds SIGNAL_THRESHOLD."""
    symbol:    str
    direction: str       # BUY or SELL
    score:     float
    headline:  str
    source:    str
    url:       str
    ts:        str = field(default_factory=lambda: datetime.utcnow().isoformat())


class NewsEngine:
    """
    Polls RSS feeds, scores sentiment, emits NewsSignals.

    Usage:
        engine = NewsEngine(on_signal=my_callback)
        engine.start()          # starts background thread
        engine.recent_news()    # returns List[NewsItem]
        engine.stop()
    """

    def __init__(self,
                 on_signal: Optional[Callable[[NewsSignal], None]] = None,
                 default_symbol: str = "BTCUSDT",
                 auto_trade: bool = False):
        self._on_signal        = on_signal
        self._default_sym      = default_symbol
        self._auto_trade       = auto_trade
        self._seen_uids        = set()
        self._news_buf         = deque(maxlen=MAX_RECENT_NEWS)
        self._signals_buf      = deque(maxlen=50)
        self._running          = False
        self._thread           = None
        # Per-symbol cooldown: symbol → epoch seconds of last signal emitted
        self._last_signal_ts: Dict[str, float] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self):
        import threading
        self._running = True
        self._thread  = threading.Thread(target=self._loop, daemon=True, name="news-engine")
        self._thread.start()
        logger.info("NewsEngine started — polling %d feeds every %ds", len(RSS_FEEDS), POLL_INTERVAL)

    def stop(self):
        self._running = False
        logger.info("NewsEngine stopped")

    def recent_news(self, limit: int = 30) -> List[NewsItem]:
        return list(self._news_buf)[-limit:]

    def recent_signals(self, limit: int = 20) -> List[NewsSignal]:
        return list(self._signals_buf)[-limit:]

    def set_auto_trade(self, enabled: bool):
        self._auto_trade = enabled
        logger.info("NewsEngine auto-trade: %s", "ON" if enabled else "OFF")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _loop(self):
        while self._running:
            try:
                self._poll_all_feeds()
            except Exception as e:
                logger.error("NewsEngine poll error: %s", e)
            for _ in range(POLL_INTERVAL):
                if not self._running:
                    break
                time.sleep(1)

    @staticmethod
    def _parse_pub_dt(entry) -> Optional[datetime]:
        """Return UTC-aware datetime from feedparser entry, or None if unparseable."""
        # feedparser gives published_parsed as a time.struct_time in UTC
        pt = entry.get("published_parsed") or entry.get("updated_parsed")
        if pt:
            try:
                return datetime.fromtimestamp(calendar.timegm(pt), tz=timezone.utc)
            except Exception:
                pass
        # fallback: try parsing the raw string
        raw = entry.get("published", "")
        for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z",
                    "%Y-%m-%dT%H:%M:%SZ"):
            try:
                return datetime.strptime(raw, fmt).astimezone(timezone.utc)
            except Exception:
                pass
        return None

    def _poll_all_feeds(self):
        now_utc   = datetime.now(tz=timezone.utc)
        max_age   = timedelta(minutes=MAX_ARTICLE_AGE_MIN)
        new_count = 0
        stale_skipped = 0

        for source_name, url in RSS_FEEDS:
            try:
                try:
                    resp = _requests.get(url, headers=_HTTP_HEADERS, timeout=_HTTP_TIMEOUT, verify=False)
                    feed = feedparser.parse(resp.text)
                except Exception:
                    feed = feedparser.parse(url)

                for entry in feed.entries[:10]:
                    uid = hashlib.md5((entry.get("link", entry.get("title", "")) or "").encode()).hexdigest()
                    if uid in self._seen_uids:
                        continue
                    self._seen_uids.add(uid)

                    # ── Staleness check ──────────────────────────────────────
                    pub_dt = self._parse_pub_dt(entry)
                    if pub_dt:
                        age = now_utc - pub_dt
                        if age > max_age:
                            stale_skipped += 1
                            continue   # article too old — skip entirely, no signal
                    # If pub_dt is unparseable we allow it through (can't determine age)

                    title   = entry.get("title",   "")
                    summary = entry.get("summary", "") or entry.get("description", "")
                    link    = entry.get("link",    "")
                    pub_str = entry.get("published", now_utc.isoformat())

                    score, sentiment = self._score(title + " " + summary)
                    symbols = self._extract_symbols(title + " " + summary)

                    item = NewsItem(
                        title     = title,
                        summary   = summary[:300],
                        source    = source_name,
                        url       = link,
                        published = pub_str,
                        score     = score,
                        sentiment = sentiment,
                        symbols   = symbols or [self._default_sym],
                        uid       = uid,
                    )
                    self._news_buf.append(item)
                    new_count += 1

                    if abs(score) >= SIGNAL_THRESHOLD:
                        self._emit_signal(item)

            except Exception as e:
                logger.warning("Feed error [%s]: %s", source_name, e)

        if new_count or stale_skipped:
            logger.info("NewsEngine: %d new articles, %d stale skipped", new_count, stale_skipped)

    def _score(self, text: str) -> tuple:
        """Score sentiment of text. Returns (score, label)."""
        text_lower = " " + text.lower() + " "
        score = 0.0

        for kw, weight in BULLISH_KEYWORDS.items():
            if kw in text_lower:
                score += weight

        for kw, weight in BEARISH_KEYWORDS.items():
            if kw in text_lower:
                score += weight   # weight is already negative

        # Clamp to [-100, 100]
        score = max(-100.0, min(100.0, score))

        if score >= SIGNAL_THRESHOLD:
            sentiment = "BULLISH"
        elif score <= -SIGNAL_THRESHOLD:
            sentiment = "BEARISH"
        else:
            sentiment = "NEUTRAL"

        return round(score, 1), sentiment

    def _extract_symbols(self, text: str) -> List[str]:
        """Find which crypto symbols are mentioned in the text."""
        text_lower = " " + text.lower() + " "
        found = []
        for keyword, symbol in COIN_MAP.items():
            if keyword in text_lower and symbol not in found:
                found.append(symbol)
        return found

    def _emit_signal(self, item: NewsItem):
        direction = "BUY" if item.score > 0 else "SELL"
        now = time.time()
        for symbol in item.symbols:
            # ── Per-symbol cooldown ──────────────────────────────────────────
            # Prevents firing duplicate trades when several articles about the
            # same coin hit within the same poll window (e.g. 3 BTC articles
            # in the same batch would otherwise open 3 positions).
            last = self._last_signal_ts.get(symbol, 0)
            if now - last < SYMBOL_COOLDOWN_SEC:
                remaining = int(SYMBOL_COOLDOWN_SEC - (now - last))
                logger.info(
                    "NEWS SIGNAL COOLDOWN: %s %s — %ds remaining",
                    symbol, direction, remaining
                )
                continue
            self._last_signal_ts[symbol] = now

            sig = NewsSignal(
                symbol    = symbol,
                direction = direction,
                score     = item.score,
                headline  = item.title,
                source    = item.source,
                url       = item.url,
            )
            self._signals_buf.append(sig)
            logger.info(
                "NEWS SIGNAL: %s %s | score=%.1f | %s [%s]",
                direction, symbol, item.score, item.title[:60], item.source
            )
            if self._auto_trade and self._on_signal:
                try:
                    self._on_signal(sig)
                except Exception as e:
                    logger.error("NewsEngine on_signal callback error: %s", e)
