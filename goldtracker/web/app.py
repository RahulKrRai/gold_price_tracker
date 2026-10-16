"""Local dashboard: FastAPI JSON API + one static HTML page."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse

from .. import db
from ..config import get_settings
from ..offers import Offer, load_offers
from ..ranking import rank, unparsed

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="Gold Deal Tracker")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/meta")
def meta() -> dict:
    s = get_settings()
    with db.open_db(s.db_path) as conn:
        rate = db.latest_rate(conn)
        # Filter options come from what can actually be ranked, so no chip leads to an empty table
        ranked = rank(conn, [], in_stock_only=False)
        retailers = sorted({d.retailer for d in ranked})
        weights = sorted({d.weight_g for d in ranked})
        purities = sorted({d.purity for d in ranked}, reverse=True)
        forms = sorted({d.form for d in ranked if d.form})
        brands = sorted({d.brand for d in ranked if d.brand}, key=str.lower)
        last_sync = conn.execute("SELECT MAX(seen_at) FROM prices").fetchone()[0]
    return {
        "rate": dict(rate) if rate else None,
        "last_sync": last_sync,
        "retailers": retailers, "weights": weights, "purities": purities, "forms": forms, "brands": brands,
        "offers": [{"id": o.id, "kind": o.kind, "label": o.label, "retailer": o.retailer,
                    "first_order_only": o.first_order_only} for o in load_offers(s.offers_path)],
        "my_offers": s.my_offers,
        "include_first_order": s.include_first_order,
    }


@app.get("/api/deals")
def deals(
    retailer: str | None = None,
    weight: float | None = None,
    purity: float | None = None,
    form: str | None = None,
    offers: str | None = Query(None, description="comma-separated offer ids you hold; omit for .env default"),
    first_order: bool | None = None,
    include_out_of_stock: bool = False,
    brand: str | None = None,
    coupon_only: bool = False,
    wallet_pct: float | None = Query(None, ge=0, le=20,
                                     description="Amazon Pay balance bought at this % off (applies to Amazon)"),
) -> dict:
    s = get_settings()
    all_offers = load_offers(s.offers_path)
    held = set(x for x in offers.split(",") if x) if offers is not None else (set(s.my_offers) or None)
    if wallet_pct:
        wallet = wallet_offer(wallet_pct)
        all_offers.append(wallet)
        if held is not None:
            held.add(wallet.id)
    with db.open_db(s.db_path) as conn:
        ranked = rank(conn, all_offers, held=held,
                      include_first_order=s.include_first_order if first_order is None else first_order,
                      retailer=retailer or None, weight_g=weight, purity=purity, form=form or None,
                      in_stock_only=not include_out_of_stock, brand=brand or None, coupon_only=coupon_only)
    return {"count": len(ranked), "deals": [d.as_dict() for d in ranked]}


def wallet_offer(pct: float) -> Offer:
    """Paying with Amazon Pay balance you bought at a discount works like an uncapped card offer.
    You pay with either the balance or a card, so it competes with card offers rather than stacking."""
    return Offer(id="amazon-pay-balance", kind="card", retailer="amazon",
                 label=f"Amazon Pay balance ({pct:g}% off)", percent=pct)


@app.get("/api/history/{product_id}")
def history(product_id: int, days: int = Query(30, ge=1, le=365)) -> dict:
    with db.open_db(get_settings().db_path) as conn:
        return {"product_id": product_id, "points": db.price_history(conn, product_id, days)}


@app.get("/api/unparsed")
def get_unparsed() -> dict:
    """Listings left out of the ranking: no weight/purity in the title, or failed the sanity check."""
    rejected: list = []
    with db.open_db(get_settings().db_path) as conn:
        rank(conn, [], rejected=rejected, in_stock_only=False)
        return {"unparsed": unparsed(conn), "implausible": rejected}


@app.post("/api/refresh")
def refresh() -> dict:
    from ..jobs import refresh_once

    return refresh_once()
