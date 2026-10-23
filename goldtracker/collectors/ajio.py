"""Ajio collector for gold coins and bars.

Data source (checked in a real browser on 2026-10-23): search pages embed
window.__PRELOADED_STATE__.grid.entities, keyed by product code, each with
  code, name ("1 Gm 24 Kt (999) Yellow Gold Bar"), fnlColorVariantData.brandName,
  price.value (selling price), wasPriceData.value (MRP), offerPrice.value, couponStatus,
  url ("/bangalore-refinery-.../p/6005289300_multi"), brickNameText ("Bars & Coins"),
  verticalNameText ("Fine Jewellery" / "Silver Jewellery")
45 products per page; more load as you scroll. Listings only say "Coupon Applicable"; the coupon
amount is on the product page, so add Ajio coupons by hand (sale-coupon) when you know them.
"""

from __future__ import annotations

from urllib.parse import quote

from .base import RawListing
from .browser import browse, money, why_empty

QUERIES = ["gold coin", "gold bar 24k"]
PAGES_PER_QUERY = 3
KEEP_BRICKS = {"bars & coins", "idols & coins"}
DROP_VERTICALS = {"silver jewellery", "fashion jewellery"}

_EXTRACT_JS = """
() => {
  const s = window.__PRELOADED_STATE__;
  const e = s && s.grid && s.grid.entities;
  if (!e) return null;
  return Object.values(e).map(p => ({
    code: p.code, name: p.name,
    brand: p.fnlColorVariantData ? p.fnlColorVariantData.brandName : null,
    price: p.price ? p.price.value : null,
    mrp: p.wasPriceData ? p.wasPriceData.value : null,
    offer: p.offerPrice ? p.offerPrice.value : null,
    couponStatus: p.couponStatus || null,
    url: p.url || null,
    brick: p.brickNameText || p.brickName || null,
    vertical: p.verticalNameText || p.verticalName || null,
  }));
}
"""


def to_listing(p: dict) -> RawListing | None:
    name = (p.get("name") or "").strip()
    price = money(p.get("offer")) or money(p.get("price"))
    if not name or not price or not p.get("code"):
        return None
    vertical = (p.get("vertical") or "").strip().lower()
    brick = (p.get("brick") or "").strip().lower()
    if vertical in DROP_VERTICALS:
        return None
    if brick and not brick.isdigit() and brick not in KEEP_BRICKS:
        return None  # necklaces, pendants etc.
    brand = (p.get("brand") or "").strip() or None
    title = f"{brand} {name}" if brand and not name.lower().startswith(brand.lower()) else name
    url = p.get("url")
    return RawListing(retailer="ajio", retailer_sku=str(p["code"]), title=title, price=price, brand=brand,
                      url=f"https://www.ajio.com{url}" if url and url.startswith("/") else url,
                      mrp=money(p.get("mrp")))


def parse(state_items: list | None) -> list[RawListing]:
    return [x for x in (to_listing(p) for p in state_items or []) if x]


def collect(headless: bool = True) -> list[RawListing]:
    urls = [f"https://www.ajio.com/search/?text={quote(q)}" + (f"&currentPage={n}" if n > 1 else "")
            for q in QUERIES for n in range(1, PAGES_PER_QUERY + 1)]
    pages = browse(urls, _EXTRACT_JS, headless=headless, scroll=True)
    seen: dict[str, RawListing] = {}
    for items in pages:
        for it in parse(items):
            seen.setdefault(it.retailer_sku, it)
    if not seen:
        raise RuntimeError(why_empty("Ajio"))
    return list(seen.values())
