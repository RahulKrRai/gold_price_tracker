"""Today's gold rate.

The project hasn't picked a rate source yet (IBJA, MCX or a paid API - see the tracker's open
questions), so this module supports two things:
  * a manual rate (GOLD_RATE_24K in .env, or `python -m goldtracker rate --set 14787`)
  * any JSON endpoint you configure (GOLD_RATE_URL + GOLD_RATE_JSON_KEY)
"""

from __future__ import annotations

import sqlite3

import httpx

from . import db
from .config import Settings


def _dig(data, dotted: str):
    for part in dotted.split("."):
        data = data[int(part)] if isinstance(data, list) else data[part]
    return data


def fetch_from_url(url: str, json_key: str, timeout: float = 15.0) -> float:
    resp = httpx.get(url, timeout=timeout, headers={"User-Agent": "gold-deal-tracker/0.1"})
    resp.raise_for_status()
    value = float(_dig(resp.json(), json_key))
    if not 1000 < value < 100000:
        raise ValueError(f"24K rate {value} looks wrong (expected INR per gram)")
    return value


def refresh_rate(conn: sqlite3.Connection, settings: Settings) -> float | None:
    """Fetch and store today's rate. Returns the 24K rate saved, or None if no source is configured."""
    if settings.rate_url and settings.rate_json_key:
        rate = fetch_from_url(settings.rate_url, settings.rate_json_key)
        db.save_rate(conn, rate, source=settings.rate_url)
        return rate
    if settings.manual_rate_24k:
        if db.latest_rate(conn) is None:
            db.save_rate(conn, settings.manual_rate_24k, source="manual (.env)")
        return settings.manual_rate_24k
    return None
