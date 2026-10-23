"""Shared helper for collectors that read retailer listing pages in a real browser (Playwright).

One page at a time, with a pause between pages, so it browses like a person rather than a bot.
Retailers' terms restrict automated access: keep this to personal use at low frequency.
Most Indian retailers refuse cloud/datacenter networks, so run collectors on your own computer.
"""

from __future__ import annotations

import time
from typing import Callable, Iterable

PAUSE_SECONDS = 8


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
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        page = browser.new_page(locale="en-IN", viewport={"width": 1366, "height": 900})
        for url in urls:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(wait_ms)
            if scroll:  # lazy-loaded grids
                for _ in range(4):
                    page.mouse.wheel(0, 2500)
                    page.wait_for_timeout(800)
            result = page.evaluate(extract_js)
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
