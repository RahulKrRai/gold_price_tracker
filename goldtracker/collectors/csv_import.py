"""Import listings from a CSV file.

Useful for manual entries (e.g. a deal you saw in an app) and for the sample data.
Columns: retailer, sku, title, price, brand, url, mrp, coupon_code, coupon_value, in_stock, stock_left
Only retailer, sku, title and price are required.
"""

from __future__ import annotations

import csv
from pathlib import Path

from .base import RawListing


def _num(v: str | None) -> float | None:
    v = (v or "").replace(",", "").replace("₹", "").strip()
    return float(v) if v else None


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
            ))
    return out
