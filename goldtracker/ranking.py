"""Rank listings by effective INR per fine gram and premium over spot."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from . import db
from .offers import Offer, apply_offers

GST = 0.03  # GST on gold in India


@dataclass
class RankedDeal:
    product_id: int
    retailer: str
    title: str
    brand: str | None
    url: str | None
    form: str | None
    weight_g: float
    purity: float
    fine_g: float
    in_stock: bool
    stock_left: int | None
    seen_at: str
    breakdown: dict
    per_fine_g: float
    per_g_actual: float
    premium_vs_spot: float | None          # vs 24K rate excl. GST
    premium_vs_spot_gst: float | None      # vs 24K rate + 3% GST (the price you can't avoid)

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def per_fine_gram(effective_price: float, weight_g: float, purity: float) -> float:
    return effective_price / (weight_g * purity)


def spot_per_fine_gram(rate_24k: float) -> float:
    """The quoted 24K rate is for 999 gold; scale it to pure (fine) gold."""
    return rate_24k / 0.999


def rank(conn: sqlite3.Connection, offers: list[Offer], *, held: set[str] | None = None,
         include_first_order: bool = False, retailer: str | None = None, weight_g: float | None = None,
         purity: float | None = None, form: str | None = None, in_stock_only: bool = True) -> list[RankedDeal]:
    rate_row = db.latest_rate(conn)
    spot = spot_per_fine_gram(rate_row["rate_24k"]) if rate_row else None
    deals: list[RankedDeal] = []
    for r in db.latest_listings(conn):
        if r["weight_g"] is None or r["purity"] is None:
            continue  # can't rank what we can't measure; see /api/unparsed
        if retailer and r["retailer"] != retailer:
            continue
        if weight_g is not None and abs(r["weight_g"] - weight_g) > 1e-6:
            continue
        if purity is not None and abs(r["purity"] - purity) > 1e-6:
            continue
        if form and r["form"] != form:
            continue
        if in_stock_only and not r["in_stock"]:
            continue
        coupon = (r["coupon_code"] or "listing coupon", r["coupon_value"]) if r["coupon_value"] else None
        b = apply_offers(r["list_price"], r["retailer"], offers, held=held,
                         include_first_order=include_first_order, listing_coupon=coupon)
        pfg = per_fine_gram(b.effective_price, r["weight_g"], r["purity"])
        deals.append(RankedDeal(
            product_id=r["id"], retailer=r["retailer"], title=r["title"], brand=r["brand"], url=r["url"],
            form=r["form"], weight_g=r["weight_g"], purity=r["purity"],
            fine_g=round(r["weight_g"] * r["purity"], 4), in_stock=bool(r["in_stock"]),
            stock_left=r["stock_left"], seen_at=r["seen_at"], breakdown=b.as_dict(),
            per_fine_g=round(pfg, 2), per_g_actual=round(b.effective_price / r["weight_g"], 2),
            premium_vs_spot=round(pfg / spot - 1, 4) if spot else None,
            premium_vs_spot_gst=round(pfg / (spot * (1 + GST)) - 1, 4) if spot else None,
        ))
    deals.sort(key=lambda d: d.per_fine_g)
    return deals


def unparsed(conn: sqlite3.Connection) -> list[dict]:
    """Products whose weight or purity couldn't be read from the title."""
    rows = conn.execute(
        "SELECT id, retailer, title, weight_g, purity FROM products WHERE weight_g IS NULL OR purity IS NULL"
    ).fetchall()
    return [dict(r) for r in rows]
