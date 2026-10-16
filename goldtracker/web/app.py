"""Local dashboard: FastAPI JSON API + one static HTML page."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse

from .. import db
from ..config import get_settings
from ..offers import load_offers
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
        retailers = [r[0] for r in conn.execute("SELECT DISTINCT retailer FROM products ORDER BY 1")]
        weights = [r[0] for r in conn.execute(
            "SELECT DISTINCT weight_g FROM products WHERE weight_g IS NOT NULL ORDER BY 1")]
        purities = [r[0] for r in conn.execute(
            "SELECT DISTINCT purity FROM products WHERE purity IS NOT NULL ORDER BY 1 DESC")]
        forms = [r[0] for r in conn.execute("SELECT DISTINCT form FROM products ORDER BY 1")]
        last_sync = conn.execute("SELECT MAX(seen_at) FROM prices").fetchone()[0]
    return {
        "rate": dict(rate) if rate else None,
        "last_sync": last_sync,
        "retailers": retailers, "weights": weights, "purities": purities, "forms": forms,
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
) -> dict:
    s = get_settings()
    held = set(x for x in offers.split(",") if x) if offers is not None else (set(s.my_offers) or None)
    with db.open_db(s.db_path) as conn:
        ranked = rank(conn, load_offers(s.offers_path), held=held,
                      include_first_order=s.include_first_order if first_order is None else first_order,
                      retailer=retailer or None, weight_g=weight, purity=purity, form=form or None,
                      in_stock_only=not include_out_of_stock)
    return {"count": len(ranked), "deals": [d.as_dict() for d in ranked]}


@app.get("/api/unparsed")
def get_unparsed() -> list[dict]:
    with db.open_db(get_settings().db_path) as conn:
        return unparsed(conn)


@app.post("/api/refresh")
def refresh() -> dict:
    from ..jobs import refresh_once

    return refresh_once()
