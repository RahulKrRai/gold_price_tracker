"""Gold rates from several sources.

The first source in GOLD_RATE_SOURCES is the benchmark for "vs market"; the others are shown
alongside. Defaults: IBJA (official Indian bullion association rate, weekdays, AM and PM sessions)
then Tanishq (a retail jeweller's published rate, the one WealthyDimes uses).

Both pages are plain HTML (checked 2026-10-19):
  * ibjarates.com: today's rates in <span id="lblGold999_AM|PM"> (INR per 10 g), and history rows
    <td data-label="AM|PM"><strong>DD/MM/YYYY</strong></td> ... <td data-label="Gold 999">146514</td>
  * tanishq.co.in/gold-rate.html: history rows
    <td>DD-MM-YYYY</td> ... data-goldrate22kt="13610" data-goldrate24kt="14847" (INR per gram)

  * goodreturns.in/gold-rates/ (checked 2026-10-23): <span id="24K-price">&#x20b9;14,248</span>,
    <span id="22K-price">...</span> and <span id="metal-price-date">23 October 2026</span> (INR per gram)
  * api.gold-api.com/price/XAU/INR (free, no key): {"price": <INR per troy ounce>, "updatedAt": "...Z"}.
    International spot converted to INR per gram. It has no Indian import duty or GST, so it reads
    about 15% below Indian rates; it is shown for reference and is never a good benchmark.

MCX futures are not included: mcxindia.com blocks scripted access and its data terms forbid reuse.

Rates exclude GST. If a source fails, the last stored rate for it is kept.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable

import httpx

from . import db
from .config import Settings

IST = timezone(timedelta(hours=5, minutes=30))
SESSION_TIME = {"AM": time(12, 0), "PM": time(17, 0)}  # IBJA publishes around noon and 5 pm
UA = "Mozilla/5.0 (compatible; gold-deal-tracker/0.6; personal use)"
IBJA_URL = "https://ibjarates.com/"
TANISHQ_URL = "https://www.tanishq.co.in/gold-rate.html"
GOODRETURNS_URL = "https://www.goodreturns.in/gold-rates/"
XAU_URL = "https://api.gold-api.com/price/XAU/INR"
TROY_OUNCE_G = 31.1034768


@dataclass(frozen=True)
class Rate:
    source: str
    rate_24k: float          # INR per gram, 24K (999), excl. GST
    rate_22k: float | None   # INR per gram, 22K (916)
    as_of: str               # ISO time the source published it
    session: str | None = None


class RateError(RuntimeError):
    pass


def _check(value: float, what: str) -> float:
    if not 1_000 < value < 100_000:
        raise RateError(f"{what} = {value} doesn't look like INR per gram")
    return value


def _iso(d: date, t: time) -> str:
    return datetime.combine(d, t, IST).isoformat(timespec="seconds")


# --- IBJA ---------------------------------------------------------------------------------

_IBJA_TODAY = re.compile(r'id="lblGold(999|916)_(AM|PM)"\s*>\s*([\d.,]*)\s*<', re.I)
_IBJA_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.I | re.S)
_IBJA_SESSION_DATE = re.compile(
    r'data-label="(AM|PM)"[^>]*>\s*(?:<strong>)?\s*(\d{2}/\d{2}/\d{4})', re.I)
_IBJA_CELL = re.compile(r'data-label="Gold (999|916)"[^>]*>\s*([\d.,]+)', re.I)


def _num(s: str) -> float:
    return float(s.replace(",", "").strip())


def parse_ibja(html: str, today: date) -> Rate:
    """Latest IBJA 999/916 rate. Today's PM beats today's AM; otherwise the newest history row."""
    history: list[tuple[date, str, dict]] = []
    for row in _IBJA_ROW.findall(html):
        m = _IBJA_SESSION_DATE.search(row)
        if not m:
            continue
        cells = {k: _num(v) for k, v in _IBJA_CELL.findall(row)}
        if "999" in cells:
            history.append((datetime.strptime(m.group(2), "%d/%m/%Y").date(), m.group(1).upper(), cells))

    today_vals: dict[tuple[str, str], float] = {}
    for purity, session, val in _IBJA_TODAY.findall(html):
        if val.strip():
            today_vals[(purity, session.upper())] = _num(val)

    for session in ("PM", "AM"):
        v999 = today_vals.get(("999", session))
        if v999:
            # On holidays the "today" box can still show the last rate; date it from history if it matches
            day = next((d for d, s, c in history if s == session and c.get("999") == v999), today)
            v916 = today_vals.get(("916", session))
            return Rate("ibja", _check(v999 / 10, "IBJA 999"), v916 / 10 if v916 else None,
                        _iso(day, SESSION_TIME[session]), session)

    if history:
        d, s, c = max(history, key=lambda h: (h[0], h[1] == "PM"))
        return Rate("ibja", _check(c["999"] / 10, "IBJA 999"), c["916"] / 10 if "916" in c else None,
                    _iso(d, SESSION_TIME[s]), s)
    raise RateError("IBJA page had no gold rates (layout changed?)")


# --- Tanishq ------------------------------------------------------------------------------

_TANISHQ_ROW = re.compile(
    r"<td>\s*(\d{2}-\d{2}-\d{4})\s*</td>\s*<td[^>]*>.*?<span[^>]*?(data-goldrate[^>]*)>", re.I | re.S)
_TANISHQ_ATTR = re.compile(r'data-goldrate(22|24|18)kt="([\d.,]+)"', re.I)


def parse_tanishq(html: str) -> Rate:
    """Newest dated row of Tanishq's gold rate history (INR per gram)."""
    rows = []
    for d, attrs in _TANISHQ_ROW.findall(html):
        vals = {k: _num(v) for k, v in _TANISHQ_ATTR.findall(attrs)}
        if "24" in vals:
            rows.append((datetime.strptime(d, "%d-%m-%Y").date(), vals))
    if not rows:
        raise RateError("Tanishq page had no gold rates (layout changed?)")
    d, vals = max(rows, key=lambda r: r[0])
    # Tanishq updates its rate in the morning; date-only, so stamp it 10:00 IST
    return Rate("tanishq", _check(vals["24"], "Tanishq 24K"), vals.get("22"), _iso(d, time(10, 0)))


# --- GoodReturns --------------------------------------------------------------------------

_GR_PRICE = re.compile(r'id="(24|22)K-price"[^>]*>\s*(?:&#x20b9;|&#8377;|₹|Rs\.?)?\s*([\d,]+(?:\.\d+)?)', re.I)
_GR_DATE = re.compile(r'id="metal-price-date"[^>]*>\s*(\d{1,2} [A-Za-z]+ \d{4})', re.I)


def parse_goodreturns(html: str, today: date) -> Rate:
    """Today's 24K/22K rate per gram from GoodReturns' price cards."""
    vals = {k: _num(v) for k, v in _GR_PRICE.findall(html)}
    if "24" not in vals:
        raise RateError("GoodReturns page had no 24K rate (layout changed?)")
    m = _GR_DATE.search(html)
    d = datetime.strptime(m.group(1), "%d %B %Y").date() if m else today
    # GoodReturns updates its rate in the morning; date-only, so stamp it 10:00 IST like Tanishq
    return Rate("goodreturns", _check(vals["24"], "GoodReturns 24K"), vals.get("22"), _iso(d, time(10, 0)))


# --- International spot (XAU) -------------------------------------------------------------

def parse_xau(text: str) -> Rate:
    """gold-api.com XAU priced in INR per troy ounce -> INR per gram (no duty, no GST)."""
    import json

    data = json.loads(text)
    if (data.get("currency") or "").upper() != "INR" or not data.get("price"):
        raise RateError(f"gold-api.com returned no INR price: {text[:120]}")
    per_g = float(data["price"]) / TROY_OUNCE_G
    as_of = data.get("updatedAt")
    as_of = (datetime.fromisoformat(as_of.replace("Z", "+00:00")).astimezone(IST).isoformat(timespec="seconds")
             if as_of else datetime.now(IST).isoformat(timespec="seconds"))
    return Rate("xau", _check(round(per_g, 2), "XAU per gram"), round(per_g * 0.916, 2), as_of)


# --- providers ----------------------------------------------------------------------------

HttpGet = Callable[[str], str]


def default_get(url: str) -> str:
    r = httpx.get(url, timeout=30, follow_redirects=True, headers={"User-Agent": UA, "Accept-Language": "en-IN"})
    r.raise_for_status()
    return r.text


def _dig(data, dotted: str):
    for part in dotted.split("."):
        data = data[int(part)] if isinstance(data, list) else data[part]
    return data


def fetch_source(source: str, settings: Settings, get: HttpGet | None = None,
                 today: date | None = None) -> Rate:
    get = get or default_get
    today = today or datetime.now(IST).date()
    now = datetime.now(IST).isoformat(timespec="seconds")
    if source == "ibja":
        return parse_ibja(get(IBJA_URL), today)
    if source == "tanishq":
        return parse_tanishq(get(TANISHQ_URL))
    if source == "goodreturns":
        return parse_goodreturns(get(GOODRETURNS_URL), today)
    if source == "xau":
        return parse_xau(get(XAU_URL))
    if source == "url":
        if not (settings.rate_url and settings.rate_json_key):
            raise RateError("GOLD_RATE_URL and GOLD_RATE_JSON_KEY must be set for the 'url' source")
        import json
        value = float(_dig(json.loads(get(settings.rate_url)), settings.rate_json_key))
        return Rate("url", _check(value, "URL rate"), None, now)
    if source == "manual":
        if not settings.manual_rate_24k:
            raise RateError("GOLD_RATE_24K is not set")
        return Rate("manual", _check(settings.manual_rate_24k, "GOLD_RATE_24K"), None, now)
    raise RateError(f"unknown rate source {source!r}")


def fetch_from_url(url: str, json_key: str, timeout: float = 15.0) -> float:
    """Kept for the `rate --fetch` CLI command."""
    resp = httpx.get(url, timeout=timeout, headers={"User-Agent": UA})
    resp.raise_for_status()
    return _check(float(_dig(resp.json(), json_key)), "URL rate")


def refresh_rates(conn: sqlite3.Connection, settings: Settings, get: HttpGet | None = None,
                  today: date | None = None) -> dict[str, dict]:
    """Fetch every configured source; store what works, report what doesn't. Never raises."""
    report: dict[str, dict] = {}
    for source in settings.rate_sources:
        try:
            r = fetch_source(source, settings, get, today)
            db.save_rate(conn, r.rate_24k, r.source, r.rate_22k, as_of=r.as_of, session=r.session)
            report[source] = {"ok": True, "rate_24k": r.rate_24k, "as_of": r.as_of, "session": r.session}
        except Exception as e:  # keep the last stored rate for this source
            report[source] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}
    conn.commit()
    return report


# --- staleness ----------------------------------------------------------------------------

def weekdays_between(a: date, b: date) -> int:
    """Number of weekdays after `a` up to and including `b`."""
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def rate_is_stale(as_of_iso: str | None, now: datetime | None = None) -> bool:
    """Stale if more than one weekday has passed since the rate's date (so weekends and a
    single holiday are fine), or if we don't know its date and it was fetched >36 h ago."""
    if not as_of_iso:
        return True
    now = now or datetime.now(IST)
    as_of = datetime.fromisoformat(as_of_iso).astimezone(IST)
    return weekdays_between(as_of.date(), now.astimezone(IST).date()) > 1
