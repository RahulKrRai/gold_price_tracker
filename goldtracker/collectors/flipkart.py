"""Flipkart collector for gold coins and bars.

Data source (checked in a real browser on 2026-10-23): search pages have no embedded data object;
each product card is an element with data-id="<Flipkart product id>" whose text lines are
  brand, title ("24K999GC2 24 (999) K 2 g Gold Coin"), "₹32,246" [, "₹33,000" MRP][, "2% off"]
  [, "Only few left"], and a link to "/<slug>/p/itm...". 40 cards per page, `&page=N` for more.
Class names are obfuscated and change often, so only data-id, the link and the text are used.
"""

from __future__ import annotations

import re
from urllib.parse import quote

from .base import RawListing
from .browser import browse, money, why_empty

QUERIES = ["gold coin 24k", "gold coin 22k", "gold bar"]
PAGES_PER_QUERY = 3

_EXTRACT_JS = """
() => [...document.querySelectorAll('[data-id]')].map(c => {
  const a = c.querySelector('a[href*="/p/itm"]');
  const t = c.querySelector('a[title]');
  return {
    id: c.getAttribute('data-id'),
    href: a ? a.getAttribute('href').split('?')[0] : null,
    title: t ? t.getAttribute('title') : null,
    lines: c.innerText.split('\\n').map(s => s.trim()).filter(Boolean).slice(0, 12),
  };
}).filter(x => x.href)
"""

_PRICE = re.compile(r"^₹\s?[\d,]+(\.\d+)?$")
_LOW_STOCK = re.compile(r"only\s+(\d+)\s+left", re.I)


def to_listing(card: dict) -> RawListing | None:
    lines = card.get("lines") or []
    prices = [money(x) for x in lines if _PRICE.match(x)]
    title = (card.get("title") or "").strip()
    if not title:  # fall back to the line before the first price
        idx = next((i for i, x in enumerate(lines) if _PRICE.match(x)), None)
        title = lines[idx - 1] if idx else ""
    if not (card.get("id") and title and prices):
        return None
    brand = lines[0] if lines and lines[0] != title and not _PRICE.match(lines[0]) else None
    text = " ".join(lines).lower()
    left = _LOW_STOCK.search(text)
    full_title = f"{brand} {title}" if brand and not title.lower().startswith(brand.lower()) else title
    return RawListing(
        retailer="flipkart", retailer_sku=str(card["id"]), title=full_title, price=prices[0], brand=brand,
        url=f"https://www.flipkart.com{card['href']}" if card.get("href", "").startswith("/") else card.get("href"),
        mrp=prices[1] if len(prices) > 1 and prices[1] > prices[0] else None,
        in_stock="sold out" not in text and "out of stock" not in text,
        stock_left=int(left.group(1)) if left else None,
    )


def parse(cards: list | None) -> list[RawListing]:
    return [x for x in (to_listing(c) for c in cards or []) if x]


def collect(headless: bool = True) -> list[RawListing]:
    urls = [f"https://www.flipkart.com/search?q={quote(q)}" + (f"&page={n}" if n > 1 else "")
            for q in QUERIES for n in range(1, PAGES_PER_QUERY + 1)]
    pages = browse(urls, _EXTRACT_JS, headless=headless)
    seen: dict[str, RawListing] = {}
    for cards in pages:
        for it in parse(cards):
            seen.setdefault(it.retailer_sku, it)
    if not seen:
        raise RuntimeError(why_empty("Flipkart"))
    return list(seen.values())
