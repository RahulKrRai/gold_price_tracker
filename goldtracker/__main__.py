"""Command line: python -m goldtracker <command>"""

from __future__ import annotations

import argparse
import logging

from . import db
from .config import get_settings


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="goldtracker", description="Rank online gold by effective ₹ per fine gram")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="create the database")
    r = sub.add_parser("rate", help="set or fetch today's 24K rate")
    r.add_argument("--set", type=float, metavar="INR_PER_G", help="save a 24K rate manually")
    r.add_argument("--fetch", action="store_true", help="fetch from GOLD_RATE_URL")
    i = sub.add_parser("import-csv", help="import listings from a CSV file")
    i.add_argument("path")
    c = sub.add_parser("collect", help="run a retailer collector")
    c.add_argument("retailer", choices=["myntra"])
    c.add_argument("--dry-run", action="store_true", help="print what was found, don't save")
    k = sub.add_parser("rank", help="print the top deals")
    k.add_argument("-n", type=int, default=15)
    s = sub.add_parser("serve", help="start the dashboard")
    s.add_argument("--port", type=int, default=8000)
    sub.add_parser("schedule", help="refresh every REFRESH_MINUTES until stopped")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()

    if args.cmd == "init":
        with db.open_db(settings.db_path):
            pass
        print(f"Database ready at {settings.db_path}")

    elif args.cmd == "rate":
        from .rates import fetch_from_url

        with db.open_db(settings.db_path) as conn:
            if args.set:
                db.save_rate(conn, args.set, source="manual (cli)")
            elif args.fetch:
                db.save_rate(conn, fetch_from_url(settings.rate_url, settings.rate_json_key), source=settings.rate_url)
            row = db.latest_rate(conn)
            print(f"24K ₹{row['rate_24k']:,.0f}/g, 22K ₹{row['rate_22k']:,.0f}/g ({row['source']}, {row['fetched_at']})"
                  if row else "No rate saved yet. Use --set 14787 or configure GOLD_RATE_URL.")

    elif args.cmd == "import-csv":
        from .collectors import save_listings
        from .collectors.csv_import import read_csv

        with db.open_db(settings.db_path) as conn:
            print(save_listings(conn, read_csv(args.path)))

    elif args.cmd == "collect":
        from .collectors import save_listings
        from .jobs import run_collector
        from .parser import parse_title

        items = run_collector(args.retailer)
        if args.dry_run:
            for it in items:
                p = parse_title(it.title)
                print(f"₹{it.price:>10,.0f}  {p.weight_g or '?':>5} g  {p.purity or '?':>6}  {it.title[:80]}")
            print(f"{len(items)} listings (not saved)")
        else:
            with db.open_db(settings.db_path) as conn:
                print(save_listings(conn, items))

    elif args.cmd == "rank":
        from .offers import load_offers
        from .ranking import rank

        with db.open_db(settings.db_path) as conn:
            deals = rank(conn, load_offers(settings.offers_path), held=set(settings.my_offers) or None,
                         include_first_order=settings.include_first_order)
        for n, d in enumerate(deals[: args.n], 1):
            prem = f"{d.premium_vs_spot:+.1%}" if d.premium_vs_spot is not None else "  —"
            print(f"{n:>3}. ₹{d.per_fine_g:>8,.0f}/fine-g {prem:>7}  {d.retailer:<7} {d.weight_g:>4g} g  {d.title[:70]}")

    elif args.cmd == "serve":
        import uvicorn

        uvicorn.run("goldtracker.web.app:app", host="127.0.0.1", port=args.port)

    elif args.cmd == "schedule":
        from .jobs import run_scheduler

        run_scheduler(settings)


if __name__ == "__main__":
    main()
