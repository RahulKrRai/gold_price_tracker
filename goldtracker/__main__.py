"""Command line: python -m goldtracker <command>"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime

from . import db
from .config import get_settings


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="goldtracker", description="Rank online gold by effective ₹ per fine gram")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="create or upgrade the database")

    r = sub.add_parser("rate", help="fetch, set or show gold rates")
    r.add_argument("--set", type=float, metavar="INR_PER_G", help="save a 24K rate by hand (source 'manual')")
    r.add_argument("--fetch", action="store_true", help="fetch every source in GOLD_RATE_SOURCES (default: ibja,tanishq)")

    i = sub.add_parser("import-csv", help="import listings from a CSV file")
    i.add_argument("path")

    c = sub.add_parser("collect", help="run a retailer collector")
    c.add_argument("retailer", choices=["myntra", "ajio", "flipkart", "amazon"])
    c.add_argument("--dry-run", action="store_true", help="print what was found, don't save")

    k = sub.add_parser("rank", help="print the top deals")
    k.add_argument("-n", type=int, default=15)

    o = sub.add_parser("override", help="fix weight/purity for a listing whose title is wrong or incomplete")
    o.add_argument("retailer")
    o.add_argument("sku", help="the retailer's product id (see `review`)")
    o.add_argument("--weight", type=float, help="total gold weight in grams")
    o.add_argument("--purity", type=float, help="e.g. 0.999, 0.995, 0.916")
    o.add_argument("--exclude", action="store_true", help="hide this listing from the ranking")
    o.add_argument("--note")
    o.add_argument("--remove", action="store_true", help="delete the override")

    sub.add_parser("review", help="list listings left out of the ranking, with the command to fix each")

    sc = sub.add_parser("sale-coupon", help="add/remove a sale-wide coupon everyone can use (e.g. a Myntra flash coupon)")
    sc_sub = sc.add_subparsers(dest="action", required=True)
    sca = sc_sub.add_parser("add")
    sca.add_argument("retailer")
    sca.add_argument("code")
    sca.add_argument("--flat", type=float, default=0, help="INR off")
    sca.add_argument("--percent", type=float, default=0)
    sca.add_argument("--min", type=float, default=0, dest="min_spend")
    sca.add_argument("--cap", type=float, dest="max_cap")
    sca.add_argument("--from", dest="valid_from", help="start, e.g. 2026-10-20T20:00 (India time)")
    sca.add_argument("--until", dest="valid_until", required=True, help="end, e.g. 2026-10-20T23:59 (India time)")
    scr = sc_sub.add_parser("remove")
    scr.add_argument("code")
    sc_sub.add_parser("list")

    p = sub.add_parser("publish", help="write the static site (deals.json etc.) for GitHub Pages")
    p.add_argument("--out", help="folder (default PUBLISH_DIR or ./site)")
    p.add_argument("--push", action="store_true", help="git commit and push the site folder afterwards")

    s = sub.add_parser("serve", help="start the dashboard")
    s.add_argument("--port", type=int, default=8000)
    sub.add_parser("schedule", help="keep refreshing rates and prices until stopped")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()

    if args.cmd == "init":
        with db.open_db(settings.db_path):
            pass
        print(f"Database ready at {settings.db_path}")

    elif args.cmd == "rate":
        from .rates import IST, refresh_rates
        from .status import rates_block

        with db.open_db(settings.db_path) as conn:
            if args.set:
                db.save_rate(conn, args.set, source="manual", as_of=datetime.now(IST).isoformat(timespec="seconds"))
            if args.fetch:
                for src, rep in refresh_rates(conn, settings).items():
                    print(f"{src}: " + (f"₹{rep['rate_24k']:,.1f}/g as of {rep['as_of']}" if rep["ok"]
                                        else f"FAILED {rep['error']}"))
            block = rates_block(conn, settings)
        if not block["rates"]:
            print("No rate saved yet. Use --fetch, or --set 14787.")
        for r in block["rates"]:
            flag = " (benchmark)" if r["benchmark"] else ""
            stale = " STALE" if r["stale"] else ""
            print(f"{r['label']:<10} 24K ₹{r['rate_24k']:,.1f}/g  as of {r['as_of']}"
                  f"{' ' + r['session'] if r['session'] else ''}{flag}{stale}")

    elif args.cmd == "import-csv":
        from .collectors import save_listings
        from .collectors.csv_import import read_csv

        with db.open_db(settings.db_path) as conn:
            print(save_listings(conn, read_csv(args.path)))

    elif args.cmd == "collect":
        from .collectors import save_listings
        from .jobs import refresh_retailer, run_collector
        from .parser import parse_title

        if args.dry_run:
            items = run_collector(args.retailer, settings)
            for it in items:
                pt = parse_title(it.title)
                print(f"₹{it.price:>10,.0f}  {pt.weight_g or '?':>5} g  {pt.purity or '?':>6}  {it.title[:80]}")
            print(f"{len(items)} listings (not saved)")
        else:
            print(refresh_retailer(args.retailer, settings))

    elif args.cmd == "rank":
        from .offers import load_offers
        from .ranking import rank

        with db.open_db(settings.db_path) as conn:
            deals = rank(conn, load_offers(settings.offers_path), held=set(settings.my_offers) or None,
                         include_first_order=settings.include_first_order, rate_sources=settings.rate_sources)
        for n, d in enumerate(deals[: args.n], 1):
            prem = f"{d.premium_vs_spot:+.1%}" if d.premium_vs_spot is not None else "  —"
            print(f"{n:>3}. ₹{d.per_fine_g:>8,.0f}/fine-g {prem:>7}  {d.retailer:<7} {d.weight_g:>5g} g  {d.title[:70]}")

    elif args.cmd == "override":
        with db.open_db(settings.db_path) as conn:
            if args.remove:
                print("removed" if db.remove_override(conn, args.retailer, args.sku) else "no override found")
                return
            if args.weight is None and args.purity is None and not args.exclude:
                ap.error("give --weight, --purity or --exclude")
            if args.purity is not None and not 0.3 < args.purity <= 1:
                ap.error("--purity is a fraction, e.g. 0.999 or 0.916")
            if not conn.execute("SELECT 1 FROM products WHERE retailer = ? AND retailer_sku = ?",
                                (args.retailer, args.sku)).fetchone():
                print(f"note: no {args.retailer} product {args.sku} in the database yet; saved anyway")
            db.set_override(conn, args.retailer, args.sku, weight_g=args.weight, purity=args.purity,
                            exclude=args.exclude, note=args.note)
        print("saved")

    elif args.cmd == "review":
        from .status import review_items

        with db.open_db(settings.db_path) as conn:
            r = review_items(conn, settings)
        if not r["count"]:
            print("Nothing to review.")
        for it in r["items"]:
            print(f"- [{it['retailer']}] {it['title'][:80]}\n    {it['reason']}\n    {it['fix']}")

    elif args.cmd == "sale-coupon":
        from .offers import add_offer, load_offers, remove_offer

        if args.action == "add":
            if not (args.flat or args.percent):
                ap.error("give --flat or --percent")
            offer = {"id": f"sale-{args.retailer}-{args.code.lower()}", "kind": "coupon", "retailer": args.retailer,
                     "label": f"{args.code} (sale)", "flat": args.flat, "percent": args.percent,
                     "min_spend": args.min_spend, "max_cap": args.max_cap, "public": True,
                     "valid_from": args.valid_from, "valid_until": args.valid_until}
            add_offer(settings.offers_path, {k: v for k, v in offer.items() if v not in (None, 0) or k == "flat"})
            print(f"added {offer['id']}")
        elif args.action == "remove":
            ids = [o.id for o in load_offers(settings.offers_path, include_inactive=True)
                   if o.public and o.label.lower().startswith(args.code.lower())]
            print("removed" if ids and all(remove_offer(settings.offers_path, i) for i in ids) else "not found")
        else:
            for o in load_offers(settings.offers_path, include_inactive=True):
                if o.public:
                    print(f"{o.label:<20} {o.retailer or 'any':<8} flat ₹{o.flat:g} {o.percent:g}%  "
                          f"until {o.valid_until}  {'ACTIVE' if o.is_active() else 'inactive'}")

    elif args.cmd == "publish":
        from pathlib import Path

        from .publish import publish

        if args.out:
            settings.publish_dir = Path(args.out).resolve()
        if args.push:
            settings.publish_git_push = True
        print(publish(settings))

    elif args.cmd == "serve":
        import uvicorn

        uvicorn.run("goldtracker.web.app:app", host="127.0.0.1", port=args.port)

    elif args.cmd == "schedule":
        from .jobs import run_scheduler

        run_scheduler(settings)


if __name__ == "__main__":
    main()
