"""Amazon collector that reads amazon.in search pages in a real browser.

Used when Creators API keys aren't set (AMAZON_SOURCE=auto, the default) or when forced with
AMAZON_SOURCE=browser. The official Creators API (collectors/amazon.py) is preferred: Amazon's
conditions of use prohibit automated data gathering and it actively blocks bots, so keep this to
personal use at low frequency, and switch to the API once you have keys.

Data source (checked in a real browser on 2026-10-23): each result is
  [data-component-type="s-search-result"][data-asin]
with h2 elements (brand, then title; sponsored cards prefix the h2 aria-label with "Sponsored Ad - "),
price in .a-price:not(.a-text-price) .a-offscreen ("₹16,125") and MRP in .a-price.a-text-price.
60 results per page, `&page=N` for more.
"""

from __future__ import annotations

from urllib.parse import quote_plus

from .base import RawListing
from .browser import browse, money, why_empty

QUERIES = ["24k gold coin", "gold bar 999", "22k gold coin"]
PAGES_PER_QUERY = 2

_EXTRACT_JS = """
() => [...document.querySelectorAll('[data-component-type="s-search-result"][data-asin]')]
  .filter(c => c.getAttribute('data-asin'))
  .map(c => {
    const h2s = [...c.querySelectorAll('h2')].map(h => h.innerText.trim()).filter(Boolean);
    const aria = (c.querySelector('h2[aria-label]') || {getAttribute: () => null}).getAttribute('aria-label');
    const txt = s => { const el = c.querySelector(s); return el ? el.textContent.trim() : null; };
    return {
      asin: c.getAttribute('data-asin'), h2s, aria,
      price: txt('.a-price:not(.a-text-price) .a-offscreen'),
      mrp: txt('.a-price.a-text-price .a-offscreen'),
      sponsored: /\\bSponsored\\b/.test(c.innerText.slice(0, 200)) || /^Sponsored Ad/.test(aria || ''),
      unavailable: /Currently unavailable/i.test(c.innerText),
    };
  })
"""


def to_listing(card: dict) -> RawListing | None:
    h2s = card.get("h2s") or []
    title = (card.get("aria") or "").replace("Sponsored Ad - ", "").strip()
    if not title or len(title) < 8:
        title = h2s[-1] if h2s else ""
    brand = h2s[0] if len(h2s) > 1 else None
    price = money(card.get("price"))
    if not (card.get("asin") and title and price):
        return None
    full_title = f"{brand} {title}" if brand and not title.lower().startswith(brand.lower()) else title
    mrp = money(card.get("mrp"))
    return RawListing(retailer="amazon", retailer_sku=str(card["asin"]), title=full_title, price=price,
                      brand=brand, url=f"https://www.amazon.in/dp/{card['asin']}",
                      mrp=mrp if mrp and mrp > price else None, in_stock=not card.get("unavailable"))


def parse(cards: list | None) -> list[RawListing]:
    return [x for x in (to_listing(c) for c in cards or []) if x]


def collect(headless: bool = True) -> list[RawListing]:
    urls = [f"https://www.amazon.in/s?k={quote_plus(q)}" + (f"&page={n}" if n > 1 else "")
            for q in QUERIES for n in range(1, PAGES_PER_QUERY + 1)]
    pages = browse(urls, _EXTRACT_JS, headless=headless, stop=lambda r: not r)
    seen: dict[str, RawListing] = {}
    for cards in pages:
        for it in parse(cards):
            seen.setdefault(it.retailer_sku, it)
    if not seen:
        raise RuntimeError(why_empty("Amazon"))
    return list(seen.values())
