"""Myntra collector for gold coins and bars.

Data source (checked in a real browser on 2026-10-16): every listing page embeds
window.__myx.searchData.results with
  products[]: productId, productName, brand, price, mrp, landingPageUrl,
              inventoryInfo[].available / .inventory,
              couponData.couponDiscount, couponData.couponDescription.couponCode,
              articleType.typeName ("Gold Coin", "Necklace and Chains", ...)
  hasNextPage, totalCount
50 products per page; `?p=N` for the next page. /gold-coin and /gold-bar overlap heavily, and
/gold-bar also returns gold-plated necklaces (dropped here by articleType and later by the parser).
A snapshot of that run is in data/myntra_2026-10-16.csv.

Myntra refuses connections from cloud/datacenter networks, so run this on your own computer:
    python -m goldtracker collect myntra --dry-run
It opens each page in a real browser (Playwright), one page at a time, with a pause between pages.
Myntra's terms restrict automated access: keep it to personal use at low frequency.
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
MAX_PAGES_PER_QUERY = 8
GOLD_TYPES = {"gold coin", "gold coins", "gold bar", "gold bars"}
LOW_STOCK = 10  # Myntra shows "N left" only when stock is low; we keep the count only below this

# Only pull out the fields we use; everything else stays in the page.
_STATE_JS = """
() => {
  const r = window.__myx && window.__myx.searchData && window.__myx.searchData.results;
  if (!r || !Array.isArray(r.products)) return null;
  return {
    hasNextPage: !!r.hasNextPage,
    totalCount: r.totalCount || null,
    products: r.products.map(p => ({
      productId: p.productId, productName: p.productName, product: p.product, brand: p.brand,
      price: p.price, mrp: p.mrp, landingPageUrl: p.landingPageUrl,
      inventoryInfo: (p.inventoryInfo || []).map(i => ({available: i.available, inventory: i.inventory})),
      couponData: p.couponData ? {couponDiscount: p.couponData.couponDiscount,
        couponDescription: {couponCode: (p.couponData.couponDescription || {}).couponCode}} : null,
      articleType: p.articleType ? {typeName: p.articleType.typeName} : null,
    })),
  };
}
"""


def _money(v) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    digits = re.sub(r"[^\d.]", "", str(v))
    return float(digits) if digits else None


def to_listing(p: dict) -> RawListing | None:
    """Map one raw Myntra product dict to a RawListing; None if it isn't a usable gold listing."""
    title = (p.get("productName") or p.get("product") or "").strip()
    price = _money(p.get("price"))
    if not title or not price:
        return None
    type_name = ((p.get("articleType") or {}).get("typeName") or "").strip().lower()
    if type_name and type_name not in GOLD_TYPES:
        return None  # necklaces, silver, decor coins that sneak into the listing
    inv = p.get("inventoryInfo") or []
    in_stock = any(i.get("available") for i in inv) if inv else True
    left = sum((i.get("inventory") or 0) for i in inv if i.get("available")) if inv else None
    coupon = p.get("couponData") or {}
    code = (coupon.get("couponDescription") or {}).get("couponCode")
    url = p.get("landingPageUrl")
    sku = p.get("productId") or url or title
    return RawListing(
        retailer="myntra", retailer_sku=str(sku), title=title, price=price, brand=p.get("brand"),
        url=f"https://www.myntra.com/{url.lstrip('/')}" if url else None,
        mrp=_money(p.get("mrp")), in_stock=in_stock,
        stock_left=int(left) if left and left < LOW_STOCK else None,
        coupon_code=code or None, coupon_value=_money(coupon.get("couponDiscount")) if code else None,
    )


def parse_results(state: dict | None) -> tuple[list[RawListing], bool]:
    """(listings, has_next_page) from one page's searchData.results."""
    if not state:
        return [], False
    listings = [x for x in (to_listing(p) for p in state.get("products") or []) if x]
    return listings, bool(state.get("hasNextPage"))


def merge(pages: list[list[RawListing]]) -> list[RawListing]:
    """Dedupe across pages and search URLs by product id, keeping the first sighting."""
    seen: dict[str, RawListing] = {}
    for page in pages:
        for item in page:
            seen.setdefault(item.retailer_sku, item)
    return list(seen.values())


def collect(headless: bool = True) -> list[RawListing]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:  # pragma: no cover
        raise SystemExit("Playwright is not installed. Run: pip install playwright && "
                         "python -m playwright install chromium") from e

    from .browser import LAST_PAGES, note_page, why_empty

    pages: list[list[RawListing]] = []
    LAST_PAGES.clear()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        page = browser.new_page(locale="en-IN")
        for base in SEARCH_URLS:
            for n in range(1, MAX_PAGES_PER_QUERY + 1):
                url = base if n == 1 else f"{base}?p={n}"
                response = page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(3000)
                listings, has_next = parse_results(page.evaluate(_STATE_JS))
                note_page(page, response, url, empty=not listings)
                pages.append(listings)
                time.sleep(PAUSE_SECONDS)
                if not has_next:
                    break
        browser.close()
    items = merge(pages)
    if not items:
        raise RuntimeError(why_empty("Myntra"))
    return items
