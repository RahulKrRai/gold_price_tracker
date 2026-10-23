"""Tata CLiQ collector for gold coins and bars.

Data source (checked in a real browser on 2026-10-23): /search/?searchCategory=all&text=gold%20coin
renders 40 product cards, each a link to "/<slug>/p-mp<id>" containing
  h3.ProductDescription__boldText  brand ("Bangalore Refinery")
  h2.ProductDescription__description  title ("Bangalore Refinery 24k (999.9) 5gm Gold Bar")
  h3.ProductDescription__boldText  selling price ("₹79025"), then a span with the MRP ("₹90000")
A "Show More Products" button appends 40 more without changing the URL. Prices include GST.
Class names are read when present; otherwise the card's text lines are used.
"""

from __future__ import annotations

import re
from urllib.parse import quote

from .base import RawListing
from .browser import browse, money, why_empty

QUERIES = ["gold coin", "gold bar"]
SHOW_MORE_CLICKS = 3  # 40 + 3 x 40 = up to 160 cards per query

_EXTRACT_JS = """
() => {
  const out = {};
  for (const a of document.querySelectorAll('a[href*="/p-mp"]')) {
    const href = a.getAttribute('href').split('?')[0].replace('https://www.tatacliq.com', '');
    const m = href.match(/p-mp(\\d+)/i);
    if (!m || out[m[1]] || !a.innerText.trim()) continue;
    const q = s => { const e = a.querySelector(s); return e ? e.textContent.trim() : null; };
    const bold = [...a.querySelectorAll('h3[class*="boldText"]')].map(e => e.textContent.trim());
    out[m[1]] = {
      id: m[1], href,
      brand: bold.find(t => !t.startsWith('₹')) || null,
      title: q('h2[class*="description"]'),
      price: bold.find(t => t.startsWith('₹')) || null,
      mrp: [...a.querySelectorAll('span')].map(e => e.textContent.trim()).find(t => /^₹[\\d,]+$/.test(t)) || null,
      lines: a.innerText.split('\\n').map(s => s.trim()).filter(Boolean).slice(0, 10),
    };
  }
  return Object.values(out);
}
"""

_PRICE = re.compile(r"^₹\s?[\d,]+(\.\d+)?$")


def _show_more(page) -> None:
    for _ in range(SHOW_MORE_CLICKS):
        btn = page.get_by_role("button", name=re.compile("show more products", re.I))
        if not btn.count():
            return
        btn.first.click()
        page.wait_for_timeout(3000)


def to_listing(card: dict) -> RawListing | None:
    lines = card.get("lines") or []
    title = (card.get("title") or "").strip()
    price = money(card.get("price"))
    if not price:  # fall back to the first ₹ line
        price = next((money(x) for x in lines if _PRICE.match(x)), None)
    if not title:  # the line before the first price
        idx = next((i for i, x in enumerate(lines) if _PRICE.match(x)), None)
        title = lines[idx - 1] if idx else ""
    if not (card.get("id") and title and price):
        return None
    brand = (card.get("brand") or "").strip() or None
    mrp = money(card.get("mrp"))
    text = " ".join(lines).lower()
    href = card.get("href") or ""
    return RawListing(
        retailer="tatacliq", retailer_sku=str(card["id"]),
        title=f"{brand} {title}" if brand and not title.lower().startswith(brand.lower()) else title,
        price=price, brand=brand,
        url=f"https://www.tatacliq.com{href}" if href.startswith("/") else href or None,
        mrp=mrp if mrp and mrp > price else None,
        in_stock="out of stock" not in text and "sold out" not in text,
    )


def parse(cards: list | None) -> list[RawListing]:
    return [x for x in (to_listing(c) for c in cards or []) if x]


def collect(headless: bool = True) -> list[RawListing]:
    urls = [f"https://www.tatacliq.com/search/?searchCategory=all&text={quote(q)}" for q in QUERIES]
    pages = browse(urls, _EXTRACT_JS, headless=headless, wait_ms=6000, before_extract=_show_more)
    seen: dict[str, RawListing] = {}
    for cards in pages:
        for it in parse(cards):
            seen.setdefault(it.retailer_sku, it)
    if not seen:
        raise RuntimeError(why_empty("Tata CLiQ"))
    return list(seen.values())
