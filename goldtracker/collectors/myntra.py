"""Myntra collector for gold coins and bars.

STATUS: written but NOT yet tested against the live site (it couldn't be run from the build
environment). Run it locally with `python -m goldtracker collect myntra --dry-run` and check the
output before trusting it. Myntra's page structure can change at any time.

How it works:
  * Opens each search page in a real browser (Playwright), one page at a time, with a pause
    between pages so we don't hammer the site.
  * Reads the product list from the page's embedded state (window.__myx) when available,
    otherwise falls back to the visible product cards.
Note: Myntra's terms restrict automated access. Keep this to personal use at low frequency.
"""

from __future__ import annotations

import re
import time

from .base import RawListing

SEARCH_URLS = [
    "https://www.myntra.com/gold-coin",
    "https://www.myntra.com/gold-bar",
]
PAUSE_SECONDS = 8
MAX_PAGES_PER_QUERY = 3

_STATE_JS = """
() => {
  const s = window.__myx && window.__myx.searchData && window.__myx.searchData.results;
  if (!s || !Array.isArray(s.products)) return null;
  return s.products.map(p => ({
    id: String(p.productId ?? p.styleId ?? ''),
    title: p.productName ?? p.product ?? '',
    brand: p.brand ?? null,
    price: p.price ?? null,
    mrp: p.mrp ?? null,
    url: p.landingPageUrl ? 'https://www.myntra.com/' + p.landingPageUrl : null,
    inStock: p.inventoryInfo ? p.inventoryInfo.some(i => i.available) : true,
  }));
}
"""

_CARDS_JS = """
() => Array.from(document.querySelectorAll('li.product-base')).map(li => {
  const a = li.querySelector('a');
  const txt = sel => (li.querySelector(sel) || {}).textContent || '';
  return {
    id: (li.id || (a && a.getAttribute('href')) || '').toString(),
    title: (txt('.product-brand') + ' ' + txt('.product-product')).trim(),
    brand: txt('.product-brand').trim() || null,
    price: txt('.product-discountedPrice') || txt('.product-price'),
    mrp: txt('.product-strike') || null,
    url: a ? new URL(a.getAttribute('href'), location.origin).href : null,
    inStock: true,
  };
})
"""


def _money(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    digits = re.sub(r"[^\d.]", "", str(v))
    return float(digits) if digits else None


def _to_listing(p: dict) -> RawListing | None:
    price = _money(p.get("price"))
    if not price or not p.get("title"):
        return None
    sku = p.get("id") or p.get("url") or p["title"]
    return RawListing(
        retailer="myntra", retailer_sku=str(sku), title=p["title"], price=price,
        brand=p.get("brand"), url=p.get("url"), mrp=_money(p.get("mrp")), in_stock=bool(p.get("inStock", True)),
    )


def collect(headless: bool = True) -> list[RawListing]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:  # pragma: no cover
        raise SystemExit("Playwright is not installed. Run: pip install playwright && "
                         "python -m playwright install chromium") from e

    results: dict[str, RawListing] = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        page = browser.new_page(locale="en-IN")
        for base in SEARCH_URLS:
            for n in range(1, MAX_PAGES_PER_QUERY + 1):
                url = base if n == 1 else f"{base}?p={n}"
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(3000)
                raw = page.evaluate(_STATE_JS) or page.evaluate(_CARDS_JS)
                found = [x for x in (_to_listing(p) for p in raw or []) if x]
                for item in found:
                    results.setdefault(item.retailer_sku, item)
                time.sleep(PAUSE_SECONDS)
                if len(found) < 20:  # last page
                    break
        browser.close()
    return list(results.values())
