"""Import listings from a CSV file.

Useful for manual entries (e.g. a deal you saw in an app) and for the sample data.
Columns: retailer, sku, title, price, brand, url, mrp, coupon_code, coupon_value, in_stock, stock_left, seen_at
Only retailer, sku, title and price are required. seen_at (e.g. 2026-10-01 or 2026-10-01T09:30) backfills
past prices for price history; dates without a time zone are read as India time.
"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))

from .base import RawListing


def _num(v: str | None) -> float | None:
    v = (v or "").replace(",", "").replace("₹", "").strip()
    return float(v) if v else None


def _iso(v: str | None) -> str | None:
    """Accept '2026-10-01' or a full ISO timestamp; store as UTC ISO so it sorts with live rows."""
    v = (v or "").strip()
    if not v:
        return None
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def read_csv(path: Path | str) -> list[RawListing]:
    out: list[RawListing] = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            stock_left = _num(row.get("stock_left"))
            out.append(RawListing(
                retailer=row["retailer"].strip().lower(),
                retailer_sku=row["sku"].strip(),
                title=row["title"].strip(),
                price=float(_num(row["price"])),
                brand=(row.get("brand") or "").strip() or None,
                url=(row.get("url") or "").strip() or None,
                mrp=_num(row.get("mrp")),
                coupon_code=(row.get("coupon_code") or "").strip() or None,
                coupon_value=_num(row.get("coupon_value")),
                in_stock=(row.get("in_stock") or "1").strip().lower() not in {"0", "false", "no"},
                stock_left=int(stock_left) if stock_left is not None else None,
                seen_at=_iso(row.get("seen_at")),
            ))
    return out
