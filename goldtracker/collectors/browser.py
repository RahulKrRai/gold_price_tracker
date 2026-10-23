"""Shared helper for collectors that read retailer listing pages in a real browser (Playwright).

One page at a time, with a pause between pages, so it browses like a person rather than a bot.
Retailers' terms restrict automated access: keep this to personal use at low frequency.
Most Indian retailers refuse cloud/datacenter networks, so run collectors on your own computer.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Callable, Iterable

PAUSE_SECONDS = 8

# What each page looked like on the last browse() call, so a failure can say *why* there were no products
# (e.g. "HTTP 403 'Access Denied'" means the site refused us; a normal title means the layout changed).
LAST_PAGES: list[dict] = []


def note_page(page, response, url: str, empty: bool) -> None:
    """Record status/title/snippet for one page; screenshot it if empty and GOLD_DIAG_DIR is set."""
    info = {"url": url, "status": response.status if response else None}
    try:
        info["title"] = (page.title() or "")[:120]
        info["snippet"] = re.sub(r"\s+", " ", page.inner_text("body", timeout=3000))[:200]
    except Exception:  # noqa: BLE001 - diagnostics must never break a collector
        pass
    diag = os.environ.get("GOLD_DIAG_DIR")
    if empty and diag:
        try:
            Path(diag).mkdir(parents=True, exist_ok=True)
            name = re.sub(r"[^a-z0-9]+", "-", url.lower())[8:80]
            page.screenshot(path=str(Path(diag) / f"{name}.png"))
            info["screenshot"] = f"{name}.png"
        except Exception:  # noqa: BLE001
            pass
    LAST_PAGES.append(info)


def why_empty(retailer: str) -> str:
    """Error message for a collector that found nothing, using what the first page showed."""
    base = f"{retailer} returned no products"
    if not LAST_PAGES:
        return f"{base}: page layout changed or access was blocked"
    p = LAST_PAGES[0]
    seen = f"HTTP {p.get('status')}, page title {p.get('title', '')!r}"
    blocked = (p.get("status") or 200) >= 400 or re.search(
        r"access denied|forbidden|captcha|robot|unusual traffic|blocked|sorry", 
        f"{p.get('title', '')} {p.get('snippet', '')}", re.I)
    hint = "the site refused the request (blocked)" if blocked else "page loaded but no products found (layout changed?)"
    return f"{base}: {hint}; {seen}; text: {p.get('snippet', '')[:120]!r}"


def browse(urls: Iterable[str], extract_js: str, *, pause: float = PAUSE_SECONDS, wait_ms: int = 3000,
           headless: bool = True, scroll: bool = False, stop: Callable[[object], bool] | None = None) -> list:
    """Open each URL, run `extract_js` in the page and collect what it returns.

    stop(result) -> True ends the walk early (e.g. a page with no products = past the last page).
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:  # pragma: no cover
        raise SystemExit("Playwright is not installed. Run: pip install playwright && "
                         "python -m playwright install chromium") from e

    results = []
    LAST_PAGES.clear()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        page = browser.new_page(locale="en-IN", viewport={"width": 1366, "height": 900})
        for url in urls:
            response = page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(wait_ms)
            if scroll:  # lazy-loaded grids
                for _ in range(4):
                    page.mouse.wheel(0, 2500)
                    page.wait_for_timeout(800)
            result = page.evaluate(extract_js)
            note_page(page, response, url, empty=not result)
            results.append(result)
            time.sleep(pause)
            if stop and stop(result):
                break
        browser.close()
    return results


def money(v) -> float | None:
    """'₹1,57,852' / 'Rs.15,577.00' / 15577 -> float."""
    import re

    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"^\D*", "", str(v))           # drop currency prefix
    s = re.sub(r"[^\d.]", "", s)
    try:
        return float(s) if s else None
    except ValueError:
        return None
