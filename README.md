# gold_price_tracker

A local tool that ranks Indian online gold coins and bars by **effective ₹ per fine gram**, after coupons, card offers and cashback, and compares each deal with today's 24K rate.

## Setup

Needs Python 3.10+.

```bash
git clone https://github.com/RahulKrRai/gold_price_tracker.git
cd gold_price_tracker
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium   # only needed for the Myntra collector
cp .env.example .env               # then edit .env
```

## How to run

```bash
python -m goldtracker init                          # create the SQLite database (data/gold.db)
python -m goldtracker rate --set 14787              # today's 24K rate, ₹/g excl. GST
python -m goldtracker import-csv data/sample_history.csv    # sample past prices (for the history chart)
python -m goldtracker import-csv data/sample_listings.csv   # sample current prices
python -m goldtracker rank                          # top deals in the terminal
python -m goldtracker serve                         # dashboard at http://127.0.0.1:8000
```

Collecting live prices:

```bash
python -m goldtracker collect myntra --dry-run      # check what it finds first
python -m goldtracker collect myntra                # save to the database
python -m goldtracker schedule                      # refresh every REFRESH_MINUTES (30–60)
```

You can add any deal by hand to a CSV with the columns
`retailer, sku, title, price, brand, url, mrp, coupon_code, coupon_value, in_stock, stock_left, seen_at`
and import it with `import-csv`.

## Dashboard

- **Best value by weight:** the cheapest deal per weight, with the best overall highlighted. Click a card to filter.
- **Filters:** retailer, brand, purity, form, quick weight chips, and "only listings with a coupon".
- **Pay with:** tick the cards, cashback and coupons you can use, or enter the discount on Amazon Pay balance you bought. Prices re-rank instantly.
- **Vs market** in ₹ per fine gram and %, plus a **price breakdown** per row (coupon, card, fee, cashback).
- **Price history:** every crawl stores a price, so rows show a ▼/▲ change badge, "30-day low", and a 30-day price chart in the breakdown.
- **Shareable views:** filters and offers live in the URL; "Copy link to this view" copies it.

## Price history

History builds itself: each `collect` or scheduled refresh adds one price row per product. To backfill older prices, import a CSV with a `seen_at` column (`2026-10-01` or `2026-10-01T09:30`, read as India time), e.g. `python -m goldtracker import-csv data/sample_history.csv`. The API serves it at `/api/history/{product_id}`.

## How the math works

| Step | Formula |
|---|---|
| Fine grams | weight (g) × purity — 999.9 = 0.9999, 999 / 24K = 0.999, 995 = 0.995, 916 / 22K = 0.916 |
| Coupon | best single coupon (listing coupon or one from `data/offers.json`); coupons don't stack |
| Card discount | % of price after coupon, capped at `max_cap`, plus the highest extra slab you qualify for, minus nothing if below `min_spend`; card fee is added back |
| Cashback | flat or % after coupon, if `min_spend` is met (credited later) |
| Effective price | listed − coupon − card discount + card fee − cashback |
| ₹ per fine gram | effective price ÷ fine grams |
| Premium vs spot | ₹ per fine gram ÷ (24K rate ÷ 0.999) − 1 |

Example: a 1 g 22K coin at ₹15,000 with a ₹400 coupon → ₹14,600 ÷ 0.916 ≈ ₹15,939 per fine gram.

The 24K rate excludes 3% GST and retail prices include it, so a premium of about +3% is roughly the same as buying at spot plus GST. Anything below that is a good deal.

## Offers

Offers live in `data/offers.json`. Each has a `kind` (`coupon`, `card`, `cashback`), optional `retailer`, `percent`, `flat`, `min_spend`, `max_cap`, `fee`, `first_order_only` and `tiers` (extra spend slabs). Set `MY_OFFERS` in `.env` to the offer ids you can actually use; the dashboard also has checkboxes for them. First-order-only coupons are ignored unless `INCLUDE_FIRST_ORDER=true`.

The SBI slab thresholds in the sample file are estimates from one sale; check the retailer's offer page and update them.

## Gold rate

No rate source has been chosen yet. Use `rate --set`, `GOLD_RATE_24K` in `.env`, or point `GOLD_RATE_URL` and `GOLD_RATE_JSON_KEY` at any JSON endpoint that returns the 24K ₹/g rate.

## Telegram alerts (optional)

Set `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` and `ALERT_BELOW_PER_FINE_G` in `.env`. The scheduler sends one message per new deal below that price.

## Tests

```bash
pytest
```

## Project layout

```
goldtracker/
  parser.py        weight, purity and form from product titles
  offers.py        coupon / card / cashback rules
  ranking.py       ₹ per fine gram and premium vs spot
  rates.py         today's gold rate
  db.py            SQLite schema: products, prices, offers, gold_rates
  collectors/      csv_import.py, myntra.py
  jobs.py          one refresh cycle + scheduler
  alerts.py        Telegram
  web/             FastAPI app + dashboard page
data/              offers.json, sample_listings.csv (the database is created here and git-ignored)
tests/
```

## Caveats

- Amazon and Myntra restrict automated access in their terms. Keep collection to personal use, at a low rate.
- The Myntra collector hasn't been tested against the live site yet.
- Amazon isn't collected yet; the plan is the Product Advertising API once access is approved.
- Coupons that only appear in the cart or apply only to a first order may not be reflected. Treat prices as estimates.
