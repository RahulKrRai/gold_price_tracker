# gold_price_tracker

A local tool that ranks Indian online gold coins and bars by **effective ₹ per fine gram**, after coupons, card offers and cashback, and compares each deal with today's 24K rate (IBJA, with Tanishq alongside).

![tests](https://github.com/RahulKrRai/gold_price_tracker/actions/workflows/tests.yml/badge.svg)

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
python -m goldtracker init                          # create or upgrade the SQLite database (data/gold.db)
python -m goldtracker rate --fetch                  # today's 24K rate from IBJA and Tanishq
python -m goldtracker rate --set 14787              # ...or set one by hand
python -m goldtracker import-csv data/sample_history.csv    # sample past prices (for the history chart)
python -m goldtracker import-csv data/sample_listings.csv   # sample current prices
python -m goldtracker rank                          # top deals in the terminal
python -m goldtracker serve                         # dashboard at http://127.0.0.1:8000
```

Collecting live prices:

```bash
python -m goldtracker collect myntra --dry-run      # check what it finds first (also: ajio, flipkart, amazon)
python -m goldtracker collect myntra                # save to the database
python -m goldtracker schedule                      # keep refreshing (see "Scheduler" below)
```

Fixing listings the parser can't read:

```bash
python -m goldtracker review                                   # what's left out, with a fix command for each
python -m goldtracker override myntra 29872327 --purity 0.916  # title has no purity
python -m goldtracker override myntra 41493417 --weight 0.5    # "500 g" that is really 500 mg
python -m goldtracker override myntra 40132168 --exclude       # hide it
python -m goldtracker override myntra 29872327 --remove        # undo
```

Sale-wide coupons (e.g. a Myntra flash coupon everyone can use) apply automatically while valid:

```bash
python -m goldtracker sale-coupon add myntra BLINK750 --flat 750 --from 2026-10-20T20:00 --until 2026-10-20T23:59
python -m goldtracker sale-coupon list
python -m goldtracker sale-coupon remove BLINK750
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
- **Shareable views:** filters and offers live in the URL; "Copy link to this view" copies it. Each row has a **share** link that opens that deal's breakdown.
- **Rates:** the header shows IBJA (benchmark) and Tanishq with their dates; "vs market" shows the premium against both.
- **Warnings:** a banner appears when the rate is stale (more than one weekday old) or a retailer refresh is failing or overdue.
- **Needs review:** listings left out of the ranking (unknown purity, implausible price), each with the command that fixes it.

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
| Premium vs market | ₹ per fine gram ÷ (24K rate ÷ 0.999) − 1, against each rate source |
| Sanity check | listings priced below −25% or above +60% vs market are left out (usually a wrong weight in the title) |

Example: a 1 g 22K coin at ₹15,000 with a ₹400 coupon → ₹14,600 ÷ 0.916 ≈ ₹15,939 per fine gram.

The 24K rate excludes 3% GST and retail prices include it, so a premium of about +3% is roughly the same as buying at spot plus GST. Anything below that is a good deal.

## Offers

Offers live in `data/offers.json`. Each has a `kind` (`coupon`, `card`, `cashback`), optional `retailer`, `percent`, `flat`, `min_spend`, `max_cap`, `fee`, `first_order_only` and `tiers` (extra spend slabs). Set `MY_OFFERS` in `.env` to the offer ids you can actually use; the dashboard also has checkboxes for them. First-order-only coupons are ignored unless `INCLUDE_FIRST_ORDER=true`.

Offers can have `valid_from` / `valid_until` (a date means the whole day; times are India time) and are ignored outside that window. `public: true` marks a sale coupon anyone can use: it applies without being in `MY_OFFERS`.

The SBI slab thresholds in the sample file are estimates from one sale; check the retailer's offer page and update them.

## Gold rate

`GOLD_RATE_SOURCES=ibja,tanishq` (default). The first source with a rate is the benchmark for "vs market"; the others are shown alongside.

| Source | What it is | Where it comes from |
|---|---|---|
| `ibja` | Official India Bullion & Jewellers Association rate, weekdays, AM and PM sessions | ibjarates.com, plain HTML (rates per 10 g, converted to per gram) |
| `tanishq` | Tanishq's published retail rate (the rate WealthyDimes shows) | tanishq.co.in/gold-rate.html, plain HTML |
| `manual` | `GOLD_RATE_24K` in `.env`, or `rate --set` | you |
| `url` | Any JSON endpoint: `GOLD_RATE_URL` + `GOLD_RATE_JSON_KEY` (dot path) | you |

IBJA is the wholesale reference and is about 1% below jewellers' retail rates, so premiums against IBJA read about 1% higher than against Tanishq. If a source fails, its last stored rate is kept and the dashboard warns once it is more than one weekday old.

## Scheduler

`python -m goldtracker schedule` runs:

- **rates** every weekday at `RATE_REFRESH_TIMES` (default 11:00 and 17:00 India time), plus once at start;
- **prices** per retailer every `REFRESH_MINUTES_<RETAILER>` minutes (e.g. `REFRESH_MINUTES_MYNTRA=15`), default `REFRESH_MINUTES`;
- **publish** after each price refresh, if the `PUBLISH_DIR` folder exists.

Every run is logged in the `runs` table (`/api/runs`), which drives the dashboard warnings.

## Retailers

| Retailer | How it's collected | Notes |
|---|---|---|
| Myntra | Browser; reads `window.__myx` on listing pages | Listing coupons (e.g. BFF500) and stock counts included |
| Ajio | Browser; reads `window.__PRELOADED_STATE__.grid.entities` on search pages | Listings only say "Coupon Applicable"; add known Ajio coupons with `sale-coupon` |
| Flipkart | Browser; reads product cards (`[data-id]`) on search pages | No embedded data; class names change often, so only ids, links and text are used |
| Amazon | Creators API when keys are set; otherwise the browser (search result cards) | `AMAZON_SOURCE=auto|api|browser`. Prefer the API: Amazon's terms prohibit automated data gathering |

Choose retailers with `RETAILERS=myntra,ajio,flipkart,amazon`. All browser collectors open one page at a time with a pause between pages. Retailers' terms restrict automated access, so keep it to personal use at low frequency. Some retailers may block cloud servers; a blocked retailer is skipped and reported, it never stops a run.

## Amazon

Amazon replaced the Product Advertising API with the **Creators API** on 30 April 2026. `collectors/amazon.py` uses it (OAuth client credentials, `searchItems`). It needs an approved Amazon Associates account: put the keys in `.env` (`AMAZON_CLIENT_ID`, `AMAZON_CLIENT_SECRET`, `AMAZON_PARTNER_TAG`, `AMAZON_CREDENTIAL_VERSION`), then run `python -m goldtracker collect amazon --dry-run`. The scheduler only adds the Amazon job once keys are set. It is tested against a mock server only, so check the first real run.

## Free hosting (GitHub Actions + GitHub Pages)

`.github/workflows/pages.yml` runs `python -m goldtracker run-once` on GitHub's servers every 2 hours: it fetches rates, collects every retailer, sends alerts and publishes the read-only dashboard to GitHub Pages. Nothing runs on your computer and no long-lived key is stored.

1. **Settings → Pages → Source: GitHub Actions** (one time).
2. Optional: **Settings → Secrets and variables → Actions**: secrets `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `AMAZON_*`; variables `MY_OFFERS`, `ALERT_BELOW_PER_FINE_G`, `RETAILERS`.
3. **Actions → collect-and-publish → Run workflow** for a first run. Each run's page shows a table of which rates and retailers worked.

Security: actions are pinned to commit SHAs; the default token is read-only and only the deploy job can write to Pages; secrets reach only the collect step on scheduled/manual runs; price history is kept in the Actions cache (and a 14-day artifact), never committed. `tests.yml` also runs a gitleaks secret scan on every push. Note: GitHub pauses scheduled workflows in public repos after 60 days without repo activity; re-enable them from the Actions tab.

## Public site (manual publish)

```bash
python -m goldtracker publish          # writes site/: the dashboard in read-only mode + data/*.json
python -m goldtracker publish --push   # ...and commits/pushes site/ (or set PUBLISH_GIT_PUSH=true)
```

`.github/workflows/pages.yml` deploys `site/` whenever it changes. One-time setup on GitHub: **Settings → Pages → Source: GitHub Actions**. The public site ranks deals with the offers in `MY_OFFERS`; visitors can filter but not change cards. The database stays on your computer; only the ranked deals, rates and 30-day price history are published. Pages on a free account requires the repo to be public.

## Telegram alerts (optional)

Set `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` and `ALERT_BELOW_PER_FINE_G` in `.env`. The scheduler sends one message per new deal below that price.

## Tests

```bash
pytest
```

GitHub Actions runs the tests on every push (`.github/workflows/tests.yml`).

## Project layout

```
goldtracker/
  parser.py        weight, purity and form from product titles
  offers.py        coupon / card / cashback rules
  ranking.py       ₹ per fine gram and premium vs spot
  rates.py         gold rates: IBJA, Tanishq, manual, URL; staleness
  db.py            SQLite: products, prices, gold_rates, runs, overrides (+ automatic upgrades)
  collectors/      csv_import.py, myntra.py, ajio.py, flipkart.py, amazon.py (Creators API),
                   amazon_web.py (browser fallback), browser.py (shared Playwright helper)
  jobs.py          rate and price jobs + scheduler
  status.py        dashboard header data: rates, sync times, warnings, review list
  publish.py       static site for GitHub Pages
  alerts.py        Telegram
  web/             FastAPI app + dashboard page
data/              offers.json, sample CSVs, myntra_2026-10-16.csv (the database is created here and git-ignored)
tests/             pytest suite + fixtures/ (saved IBJA, Tanishq and Myntra page structures)
.github/workflows/ tests.yml (CI), pages.yml (GitHub Pages)
```

## Caveats

- Amazon and Myntra restrict automated access in their terms. Keep collection to personal use, at a low rate.
- Myntra refuses connections from cloud servers, so the collector must run on your own computer. Its data format was checked in a real browser on 2026-10-16.
- The Amazon collector is untested against the real API until keys are available.
- Coupons that only appear in the cart or apply only to a first order may not be reflected. Treat prices as estimates.
