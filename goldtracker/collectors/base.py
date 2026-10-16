"""What every collector returns, and how listings are stored."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .. import db
from ..parser import parse_title


@dataclass
class RawListing:
    retailer: str
    retailer_sku: str
    title: str
    price: float
    brand: str | None = None
    url: str | None = None
    mrp: float | None = None
    coupon_code: str | None = None
    coupon_value: float | None = None
    in_stock: bool = True
    stock_left: int | None = None
    # Collectors may override the parser when the retailer gives structured values
    weight_g: float | None = None
    purity: float | None = None


def save_listings(conn: sqlite3.Connection, listings: list[RawListing]) -> dict:
    """Parse titles, upsert products and append a price row each. Returns counts."""
    saved = skipped = unparsed = 0
    for item in listings:
        parsed = parse_title(item.title)
        if parsed.excluded:
            skipped += 1
            continue
        weight = item.weight_g if item.weight_g is not None else parsed.weight_g
        purity = item.purity if item.purity is not None else parsed.purity
        if weight is None or purity is None:
            unparsed += 1
        pid = db.upsert_product(
            conn, retailer=item.retailer, retailer_sku=item.retailer_sku, title=item.title,
            brand=item.brand, url=item.url, weight_g=weight, purity=purity, form=parsed.form,
        )
        db.add_price(conn, pid, list_price=item.price, mrp=item.mrp, coupon_code=item.coupon_code,
                     coupon_value=item.coupon_value, in_stock=item.in_stock, stock_left=item.stock_left)
        saved += 1
    conn.commit()
    return {"saved": saved, "skipped_non_bullion": skipped, "unparsed": unparsed}
