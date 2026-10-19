"""What the dashboard header shows: rates per source, last sync per retailer, and warnings."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from . import db
from .config import Settings
from .offers import load_offers
from .rates import IST, rate_is_stale
from .ranking import rank

SOURCE_LABELS = {"ibja": "IBJA", "tanishq": "Tanishq", "manual": "Manual", "url": "Custom URL"}


def _label(source: str) -> str:
    return SOURCE_LABELS.get(source, source)


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    dt = datetime.fromisoformat(ts)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def rates_block(conn: sqlite3.Connection, settings: Settings, now: datetime | None = None) -> dict:
    bench = db.benchmark_rate(conn, settings.rate_sources)
    rows = db.latest_rates(conn)
    order = settings.rate_sources + sorted(s for s in rows if s not in settings.rate_sources)
    rates = []
    for src in order:
        r = rows.get(src)
        if r is None:
            continue
        rates.append({"source": src, "label": _label(src), "rate_24k": r["rate_24k"], "rate_22k": r["rate_22k"],
                      "as_of": r["as_of"] or r["fetched_at"], "session": r["session"],
                      "benchmark": bench is not None and src == bench["source"],
                      "stale": rate_is_stale(r["as_of"] or r["fetched_at"], now)})
    return {"benchmark": bench["source"] if bench else None, "rates": rates}


def warnings(conn: sqlite3.Connection, settings: Settings, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(IST)
    out: list[dict] = []
    rb = rates_block(conn, settings, now)
    if not rb["rates"]:
        out.append({"kind": "rate", "message": "No gold rate yet. Run `python -m goldtracker rate --fetch` "
                                               "or set GOLD_RATE_24K."})
    else:
        bench = next(r for r in rb["rates"] if r["benchmark"])
        if bench["stale"]:
            out.append({"kind": "rate", "message": f"{bench['label']} rate is from "
                        f"{_parse(bench['as_of']).astimezone(IST):%d %b}; 'vs market' may be off."})
    runs = db.last_runs(conn)
    seen = db.last_seen_by_retailer(conn)
    for retailer in sorted(set(seen) | {j for j in runs if j != "rates"}):
        limit = timedelta(minutes=3 * settings.refresh_minutes_for(retailer))
        run = runs.get(retailer)
        last_ok = _parse((run or {}).get("last_success")) or _parse(seen.get(retailer))
        if run and not run["last_ok"] and run.get("last_error"):
            out.append({"kind": "retailer", "retailer": retailer,
                        "message": f"{retailer.title()} refresh failing: {run['last_error'][:120]}"})
        elif run and last_ok and now - last_ok > limit:
            out.append({"kind": "retailer", "retailer": retailer,
                        "message": f"{retailer.title()} prices last updated {_ago(now - last_ok)} ago."})
    if runs.get("rates") and not runs["rates"]["last_ok"]:
        out.append({"kind": "rate", "message": f"Rate refresh failing: {(runs['rates']['last_error'] or '')[:120]}"})
    return out


def _ago(d: timedelta) -> str:
    m = int(d.total_seconds() // 60)
    return f"{m} min" if m < 120 else f"{m // 60} h" if m < 48 * 60 else f"{m // 1440} days"


def build_meta(conn: sqlite3.Connection, settings: Settings, now: datetime | None = None) -> dict:
    # Filter options come from what can actually be ranked, so no chip leads to an empty table
    ranked = rank(conn, [], in_stock_only=False, rate_sources=settings.rate_sources)
    rb = rates_block(conn, settings, now)
    bench = next((r for r in rb["rates"] if r["benchmark"]), None)
    seen = db.last_seen_by_retailer(conn)
    return {
        # "rate" kept for older pages/tests: the benchmark row
        "rate": {"rate_24k": bench["rate_24k"], "rate_22k": bench["rate_22k"], "source": bench["label"],
                 "as_of": bench["as_of"], "session": bench["session"]} if bench else None,
        "rates": rb["rates"], "benchmark": rb["benchmark"],
        "last_sync": max(seen.values()) if seen else None,
        "retailer_sync": seen,
        "warnings": warnings(conn, settings, now),
        "retailers": sorted({d.retailer for d in ranked}),
        "weights": sorted({d.weight_g for d in ranked}),
        "purities": sorted({d.purity for d in ranked}, reverse=True),
        "forms": sorted({d.form for d in ranked if d.form}),
        "brands": sorted({d.brand for d in ranked if d.brand}, key=str.lower),
        "offers": [{"id": o.id, "kind": o.kind, "label": o.label, "retailer": o.retailer,
                    "first_order_only": o.first_order_only, "public": o.public, "valid_until": o.valid_until}
                   for o in load_offers(settings.offers_path)],
        "my_offers": settings.my_offers,
        "include_first_order": settings.include_first_order,
    }


def review_items(conn: sqlite3.Connection, settings: Settings) -> dict:
    """Listings left out of the ranking, each with the command that fixes it."""
    from .parser import parse_title
    from .ranking import unparsed

    rejected: list = []
    rank(conn, [], rejected=rejected, in_stock_only=False, rate_sources=settings.rate_sources)
    items = []
    for u in unparsed(conn):
        p = parse_title(u["title"])
        missing = [k for k in ("weight_g", "purity") if u[k] is None]
        hint = " ".join(f"--{'weight' if k == 'weight_g' else 'purity'} <{'grams' if k == 'weight_g' else '0.999'}>"
                        for k in missing)
        items.append({**u, "reason": "no " + " or ".join("weight" if k == "weight_g" else "purity" for k in missing)
                      + " in title", "guess_form": p.form,
                      "fix": f"python -m goldtracker override {u['retailer']} {u['retailer_sku']} {hint}"})
    for r in rejected:
        items.append({**r, "reason": f"price is {r['premium_vs_spot']:+.0%} vs market (weight likely wrong)",
                      "fix": f"python -m goldtracker override {r['retailer']} {r['retailer_sku']} --weight <grams>"
                             f"   # or --exclude"})
    return {"count": len(items), "items": items}
