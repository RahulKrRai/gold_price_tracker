"""CoinBazaar collector for gold coins and bars. No browser needed.

Data source (checked on 2026-10-23): coinbazaar.in runs PrestaShop, so a category page requested
with "Accept: application/json" returns its product list as JSON:
  products[]: id_product, name, price_amount (incl. 3% GST), regular_price_amount, manufacturer_name,
              url, add_to_cart_url (null when out of stock)
  pagination: pages_count, current_page   (12 products per page, ?page=N)
Category 4 ("Buy Gold") holds every gold coin and bar (about 300 products).
"""

from __future__ import annotations

import time

import httpx

from .base import RawListing
from .browser import money

CATEGORY_URL = "https://www.coinbazaar.in/4-buy-gold"
MAX_PAGES = 40
PAUSE_SECONDS = 1.5
HEADERS = {"Accept": "application/json", "Accept-Language": "en-IN",
           "User-Agent": "Mozilla/5.0 (compatible; gold-deal-tracker/0.6; personal use)"}


def to_listing(p: dict) -> RawListing | None:
    name = (p.get("name") or "").strip()
    price = money(p.get("price_amount")) or money(p.get("price"))
    if not (name and price and p.get("id_product")):
        return None
    brand = (p.get("manufacturer_name") or "").strip() or None
    mrp = money(p.get("regular_price_amount"))
    return RawListing(
        retailer="coinbazaar", retailer_sku=str(p["id_product"]), title=name, price=price, brand=brand,
        url=(p.get("url") or p.get("link") or "").split("?")[0] or None,
        mrp=mrp if mrp and mrp > price else None,
        in_stock=bool(p.get("add_to_cart_url")),
    )


def parse(page: dict | None) -> tuple[list[RawListing], int]:
    """(listings, pages_count) from one JSON page."""
    if not page:
        return [], 0
    items = [x for x in (to_listing(p) for p in page.get("products") or []) if x]
    return items, int((page.get("pagination") or {}).get("pages_count") or 1)


def collect(get=None) -> list[RawListing]:
    def default_get(url: str) -> dict:
        r = httpx.get(url, headers=HEADERS, timeout=30, follow_redirects=True)
        r.raise_for_status()
        return r.json()

    get = get or default_get
    seen: dict[str, RawListing] = {}
    n, pages = 1, 1
    while n <= min(pages, MAX_PAGES):
        items, pages = parse(get(CATEGORY_URL + (f"?page={n}" if n > 1 else "")))
        for it in items:
            seen.setdefault(it.retailer_sku, it)
        n += 1
        if n <= pages:
            time.sleep(PAUSE_SECONDS)
    if not seen:
        raise RuntimeError("CoinBazaar returned no products: page layout changed or access was blocked")
    return list(seen.values())
