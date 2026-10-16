"""Optional Telegram alert when a deal drops below a set INR per fine gram."""

from __future__ import annotations

import sqlite3

import httpx

from . import db
from .config import Settings
from .ranking import RankedDeal


def format_deal(d: RankedDeal) -> str:
    prem = f"{d.premium_vs_spot:+.1%} vs spot" if d.premium_vs_spot is not None else ""
    return (f"Gold deal: ₹{d.per_fine_g:,.0f}/fine-g {prem}\n"
            f"{d.title}\n{d.weight_g:g} g · {d.purity:g} · {d.retailer}\n"
            f"Pay ₹{d.breakdown['pay_at_checkout']:,.0f} (effective ₹{d.breakdown['effective_price']:,.0f})\n"
            f"{d.url or ''}")


def send_telegram(token: str, chat_id: str, text: str) -> None:
    httpx.post(f"https://api.telegram.org/bot{token}/sendMessage",
               json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
               timeout=15).raise_for_status()


def check_and_alert(conn: sqlite3.Connection, deals: list[RankedDeal], settings: Settings) -> int:
    """Send one message per new deal below the threshold. Returns how many were sent."""
    if not (settings.telegram_token and settings.telegram_chat_id and settings.alert_below):
        return 0
    sent = 0
    for d in deals:
        if d.per_fine_g >= settings.alert_below:
            break  # deals are sorted cheapest first
        key = (d.product_id, round(d.per_fine_g))
        if conn.execute("SELECT 1 FROM alerts_sent WHERE product_id=? AND per_fine_g=?", key).fetchone():
            continue
        send_telegram(settings.telegram_token, settings.telegram_chat_id, format_deal(d))
        conn.execute("INSERT INTO alerts_sent (product_id, per_fine_g, sent_at) VALUES (?, ?, ?)",
                     (*key, db.now_iso()))
        sent += 1
    conn.commit()
    return sent
