"""Zepto collector for gold coins and bars.

Data source (checked in a real browser on 2026-10-23): zepto.com/search?query=gold%20coin shows
results without choosing a delivery location (Zepto's default store; prices can differ by area).
Each card is a link to "/pn/<slug>/pvid/<uuid>" whose text lines are
  ["ADD" | "Notify Me"], brand ("Augmont"), title ("24 Karat 999 Pure Gold Coin | 2 g"),
  "₹2,499" price, [MRP], rating ...
Search results mix in puja coins, silver and gold-plated items; the title parser drops those.
"""

from __future__ import annotations

import re
from urllib.parse import quote

from .base import RawListing
from .browser import browse, money, why_empty

QUERIES = ["gold coin", "gold bar"]

_EXTRACT_JS = """
() => {
  const out = {};
  for (const a of document.querySelectorAll('a[href*="/pvid/"]')) {
    const href = a.getAttribute('href').split('?')[0];
    const m = href.match(/\\/pvid\\/([0-9a-f-]+)/i);
    if (!m || out[m[1]]) continue;
    out[m[1]] = {id: m[1], href,
                 lines: a.innerText.split('\\n').map(s => s.trim()).filter(Boolean).slice(0, 12)};
  }
  return Object.values(out);
}
"""

_PRICE = re.compile(r"^₹\s?[\d,]+(\.\d+)?$")
_BUTTONS = {"add", "notify me", "notify", "sold out", "out of stock"}


def to_listing(card: dict) -> RawListing | None:
    lines = card.get("lines") or []
    text = " ".join(lines).lower()
    words = [x for x in lines if x.lower() not in _BUTTONS and not x.lower().startswith("save ")]
    idx = next((i for i, x in enumerate(words) if _PRICE.match(x)), None)
    if not card.get("id") or idx is None or idx == 0:
        return None
    prices = [money(x) for x in words[idx:idx + 2] if _PRICE.match(x)]
    title = words[idx - 1]
    brand = words[idx - 2] if idx >= 2 else None
    href = card.get("href") or ""
    return RawListing(
        retailer="zepto", retailer_sku=str(card["id"]),
        title=f"{brand} {title}" if brand and not title.lower().startswith(brand.lower()) else title,
        price=prices[0], brand=brand,
        url=f"https://www.zepto.com{href}" if href.startswith("/") else href or None,
        mrp=prices[1] if len(prices) > 1 and prices[1] > prices[0] else None,
        in_stock=not any(w in text for w in ("notify me", "sold out", "out of stock")),
    )


def parse(cards: list | None) -> list[RawListing]:
    return [x for x in (to_listing(c) for c in cards or []) if x]


def collect(headless: bool = True) -> list[RawListing]:
    urls = [f"https://www.zepto.com/search?query={quote(q)}" for q in QUERIES]
    pages = browse(urls, _EXTRACT_JS, headless=headless, wait_ms=6000, scroll=True)
    seen: dict[str, RawListing] = {}
    for cards in pages:
        for it in parse(cards):
            seen.setdefault(it.retailer_sku, it)
    if not seen:
        raise RuntimeError(why_empty("Zepto"))
    return list(seen.values())
