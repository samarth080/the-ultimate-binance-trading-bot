"""
Telegram Notification Module.

Implements the notification system configured in config.json but never wired up.
Provides sync and fire-and-forget async sending so it doesn't block order execution.
"""

import logging
import os
import threading
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)

try:
    import requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False
    logger.warning("requests not installed — Telegram notifications disabled")


class TelegramNotifier:
    """
    Thin wrapper around the Telegram Bot API.

    Configuration (from environment or explicit args):
      TELEGRAM_BOT_TOKEN  — bot token from @BotFather
      TELEGRAM_CHAT_ID    — chat / channel ID to send messages to
    """

    BASE_URL = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None):
        self.token   = token   or os.getenv("TELEGRAM_BOT_TOKEN",  "")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID",    "")
        self.enabled = bool(self.token and self.chat_id and _REQUESTS_OK)

        if not self.enabled:
            logger.info("Telegram notifier disabled (no token/chat_id or missing requests)")

    # ── core send ──────────────────────────────────────────────────────────

    def send(self, text: str, parse_mode: str = "Markdown") -> bool:
        """Synchronous send. Returns True on success."""
        if not self.enabled:
            return False
        try:
            url  = self.BASE_URL.format(token=self.token)
            resp = requests.post(
                url,
                json={"chat_id": self.chat_id, "text": text,
                      "parse_mode": parse_mode},
                timeout=5,
            )
            if not resp.ok:
                logger.warning(f"Telegram send failed {resp.status_code}: {resp.text[:200]}")
            return resp.ok
        except Exception as e:
            logger.error(f"Telegram send error: {e}")
            return False

    def send_async(self, text: str):
        """Fire-and-forget — does NOT block the calling thread."""
        t = threading.Thread(target=self.send, args=(text,), daemon=True)
        t.start()

    # ── formatted helpers ──────────────────────────────────────────────────

    def signal_alert(self, symbol: str, direction: str, price: float,
                     stop: float, tp: float, confidence: float,
                     reasons: list) -> None:
        emoji = "📈" if direction == "LONG" else "📉"
        msg = (
            f"{emoji} *SIGNAL: {direction} {symbol}*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Entry  : `{price}`\n"
            f"🛑 Stop   : `{stop}`\n"
            f"🎯 Target : `{tp}`\n"
            f"📊 Confidence: `{confidence}%`\n"
            f"\n*Reasons:*\n" + "\n".join(f"  • {r}" for r in reasons) +
            f"\n\n🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
        self.send_async(msg)

    def order_filled(self, symbol: str, side: str, qty: float,
                     avg_price: float, order_id) -> None:
        emoji = "✅"
        msg = (
            f"{emoji} *ORDER FILLED*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 {symbol} {side}\n"
            f"📦 Qty      : `{qty}`\n"
            f"💲 Avg Price: `{avg_price}`\n"
            f"🆔 Order ID : `{order_id}`\n"
            f"🕐 {datetime.now().strftime('%H:%M:%S')}"
        )
        self.send_async(msg)

    def trade_closed(self, symbol: str, direction: str, pnl: float,
                     pnl_pct: float) -> None:
        emoji = "🟢" if pnl >= 0 else "🔴"
        msg = (
            f"{emoji} *TRADE CLOSED — {symbol}*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Direction : {direction}\n"
            f"PnL       : `{pnl:+.4f} USDT` ({pnl_pct:+.2f}%)\n"
            f"🕐 {datetime.now().strftime('%H:%M:%S')}"
        )
        self.send_async(msg)

    def error_alert(self, message: str) -> None:
        msg = (
            f"⚠️ *BOT ERROR*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"`{message}`\n"
            f"🕐 {datetime.now().strftime('%H:%M:%S')}"
        )
        self.send_async(msg)

    def daily_summary(self, pnl: float, trades: int, win_rate: float,
                      equity: float) -> None:
        emoji = "📊"
        msg = (
            f"{emoji} *DAILY SUMMARY*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Equity    : `{equity:.2f} USDT`\n"
            f"📈 Daily PnL : `{pnl:+.4f} USDT`\n"
            f"🔢 Trades    : `{trades}`\n"
            f"🎯 Win rate  : `{win_rate:.1f}%`\n"
            f"📅 {datetime.now().strftime('%Y-%m-%d')}"
        )
        self.send_async(msg)
