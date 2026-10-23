"""Scheduler, run logging, warnings, overrides, review panel, Myntra parsing, sale coupons."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from goldtracker import db, jobs
from goldtracker.collectors import save_listings
from goldtracker.collectors.csv_import import read_csv
from goldtracker.collectors.myntra import merge, parse_results, to_listing
from goldtracker.config import Settings
from goldtracker.offers import add_offer, apply_offers, load_offers
from goldtracker.rates import IST
from goldtracker.ranking import rank
from goldtracker.status import build_meta, review_items, warnings

ROOT = Path(__file__).parent.parent
FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    db.init_db(c)
    db.save_rate(c, 14640.6, "ibja", as_of="2026-10-16T17:00:00+05:30", session="PM")
    db.save_rate(c, 14787, "tanishq", as_of="2026-10-16T10:00:00+05:30")
    save_listings(c, read_csv(ROOT / "data" / "myntra_2026-10-16.csv"))
    yield c
    c.close()


# --- scheduler ---------------------------------------------------------------------------

def test_scheduler_jobs(monkeypatch):
    from apscheduler.schedulers.background import BackgroundScheduler

    monkeypatch.setenv("REFRESH_MINUTES_MYNTRA", "15")
    sched = jobs.build_scheduler(Settings(), scheduler_cls=BackgroundScheduler)
    ids = {j.id: j for j in sched.get_jobs()}
    assert set(ids) == {"rates-11:00", "rates-17:00", "prices-myntra", "prices-ajio", "prices-flipkart",
                        "prices-amazon", "prices-tatacliq", "prices-coinbazaar", "prices-zepto"}
    assert ids["prices-myntra"].trigger.interval.total_seconds() == 15 * 60
    nxt = ids["rates-11:00"].trigger.get_next_fire_time(None, datetime(2026, 10, 17, 12, 0, tzinfo=IST))  # Saturday
    assert (nxt.weekday(), nxt.hour, nxt.minute) == (0, 11, 0)  # next is Monday 11:00


def test_amazon_source_routing(monkeypatch):
    assert jobs.enabled_retailers(Settings()) == ["myntra", "ajio", "flipkart", "amazon", "tatacliq",
                                                 "coinbazaar", "zepto"]
    assert jobs.amazon_module(Settings()) == "amazon_web"          # auto, no keys -> browser
    for k in ("AMAZON_CLIENT_ID", "AMAZON_CLIENT_SECRET", "AMAZON_PARTNER_TAG"):
        monkeypatch.setenv(k, "x")
    assert jobs.amazon_module(Settings()) == "amazon"              # auto, keys -> official API
    monkeypatch.setenv("AMAZON_SOURCE", "browser")
    assert jobs.amazon_module(Settings()) == "amazon_web"          # forced


def test_retailers_setting(monkeypatch):
    monkeypatch.setenv("RETAILERS", "myntra,flipkart,nykaa")
    assert jobs.enabled_retailers(Settings()) == ["myntra", "flipkart"]   # unknown ones skipped
    monkeypatch.setenv("RETAILERS", "amazon")
    monkeypatch.setenv("AMAZON_SOURCE", "api")
    assert jobs.enabled_retailers(Settings()) == []                        # api forced but no keys


def test_failed_run_is_logged_and_warned(tmp_path, monkeypatch):
    monkeypatch.setenv("GOLD_DB_PATH", str(tmp_path / "j.db"))

    def boom(name, settings=None):
        raise RuntimeError("Myntra returned no products")
    monkeypatch.setattr(jobs, "run_collector", boom)
    s = Settings()
    assert "error" in jobs.refresh_retailer("myntra", s)
    with db.open_db(s.db_path) as c:
        r = db.last_runs(c)["myntra"]
        assert r["last_ok"] is False and "no products" in r["last_error"]
        assert any("Myntra refresh failing" in w["message"] for w in warnings(c, s))


# --- warnings / meta -------------------------------------------------------------------------

def test_meta_has_both_rates_and_benchmark(conn):
    m = build_meta(conn, Settings(), now=datetime(2026, 10, 17, 9, 0, tzinfo=IST))
    assert m["benchmark"] == "ibja" and [r["source"] for r in m["rates"]] == ["ibja", "tanishq"]
    assert m["rate"]["source"] == "IBJA" and m["rate"]["rate_24k"] == pytest.approx(14640.6)
    assert m["warnings"] == []


def test_stale_rate_warning(conn):
    w = warnings(conn, Settings(), now=datetime(2026, 10, 21, 18, 0, tzinfo=IST))
    assert any(x["kind"] == "rate" and "IBJA rate is from 16 Oct" in x["message"] for x in w)


def test_stale_retailer_warning(conn):
    s = Settings()
    run = db.start_run(conn, "myntra")
    db.finish_run(conn, run, ok=True, count=109)
    later = datetime.now(IST).replace(microsecond=0)
    from datetime import timedelta
    w = warnings(conn, s, now=later + timedelta(hours=5))  # 3 x 45 min = 2 h 15 min limit
    assert any(x.get("retailer") == "myntra" and "last updated" in x["message"] for x in w)


def test_premiums_against_both_sources(conn):
    d = rank(conn, [], rate_sources=["ibja", "tanishq"])[0]
    assert d.benchmark == "ibja"
    assert set(d.premiums) == {"ibja", "tanishq"}
    assert d.premiums["ibja"] > d.premiums["tanishq"]  # IBJA is the lower (wholesale) rate
    assert d.premium_vs_spot == d.premiums["ibja"]


# --- overrides + review ------------------------------------------------------------------

def test_review_lists_unparsed_and_implausible_with_fix(conn):
    r = review_items(conn, Settings())
    titles = [i["title"] for i in r["items"]]
    assert any("Joyalukkas Lord Krishna Gold Coin 1G" in t for t in titles)          # no purity
    assert any("500 g" in t for t in titles)                                          # implausible
    krishna = next(i for i in r["items"] if "Lord Krishna" in i["title"])
    assert krishna["fix"] == "python -m goldtracker override myntra 29872327 --purity <0.999>"


def test_override_fixes_purity_and_weight(conn):
    before = {d.retailer_sku for d in rank(conn, [])}
    assert "29872327" not in before
    db.set_override(conn, "myntra", "29872327", purity=0.916, note="Joyalukkas coins are 22K")
    d = next(d for d in rank(conn, []) if d.retailer_sku == "29872327")
    assert d.purity == 0.916 and d.overridden
    db.set_override(conn, "myntra", "41493417", weight_g=0.5)  # "500 g" is really 500 mg
    d = next(d for d in rank(conn, []) if d.retailer_sku == "41493417")
    assert d.weight_g == 0.5 and 0 < d.premium_vs_spot < 0.3


def test_override_exclude_and_remove(conn):
    db.set_override(conn, "myntra", "23250690", exclude=True)
    assert "23250690" not in {d.retailer_sku for d in rank(conn, [])}
    assert db.remove_override(conn, "myntra", "23250690")
    assert "23250690" in {d.retailer_sku for d in rank(conn, [])}


def test_override_cli(tmp_path, monkeypatch, capsys):
    from goldtracker.__main__ import main

    monkeypatch.setenv("GOLD_DB_PATH", str(tmp_path / "c.db"))
    main(["override", "myntra", "123", "--purity", "0.916"])
    assert "saved" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["override", "myntra", "123", "--purity", "916"])  # must be a fraction


# --- Myntra parsing -----------------------------------------------------------------------

def test_myntra_fixture_parsing():
    state = json.loads((FIX / "myntra_results.json").read_text())
    items, has_next = parse_results(state)
    assert has_next is True
    by_sku = {i.retailer_sku: i for i in items}
    assert "32151750" not in by_sku  # necklace dropped by article type
    bhima = by_sku["23250690"]
    assert (bhima.price, bhima.mrp, bhima.coupon_code, bhima.coupon_value) == (16072, 16876, "BFF500", 500)
    assert bhima.url.startswith("https://www.myntra.com/gold-coin/bhima/") and bhima.stock_left is None
    assert by_sku["31416965"].stock_left == 5          # low stock kept
    assert by_sku["22810428"].coupon_code is None
    assert by_sku["99999999"].in_stock is False


def test_myntra_merge_dedupes_across_pages():
    state = json.loads((FIX / "myntra_results.json").read_text())
    a, _ = parse_results(state)
    b, _ = parse_results({"products": state["products"][:2], "hasNextPage": False})
    assert len(merge([a, b])) == len(a)


def test_myntra_empty_and_bad_rows():
    assert parse_results(None) == ([], False)
    assert to_listing({"productName": "x", "price": None}) is None


# --- sale coupons / validity ----------------------------------------------------------------

def test_public_sale_coupon_applies_without_holding(tmp_path):
    p = tmp_path / "offers.json"
    add_offer(p, {"id": "sale-myntra-blink750", "kind": "coupon", "retailer": "myntra", "label": "BLINK750 (sale)",
                  "flat": 750, "public": True, "valid_from": "2026-10-16T10:00", "valid_until": "2026-10-16T23:59"})
    offers = load_offers(p)  # clock pinned to 16 Oct 12:00 IST
    b = apply_offers(15980, "myntra", offers, held=set(), listing_coupon=("BFF500", 500))
    assert b.coupon == 750 and b.coupon_label == "BLINK750 (sale)"  # best coupon wins, not stacked


def test_expired_and_future_offers_are_ignored(tmp_path):
    p = tmp_path / "offers.json"
    add_offer(p, {"id": "old", "kind": "coupon", "flat": 100, "valid_until": "2026-10-15"})
    add_offer(p, {"id": "later", "kind": "coupon", "flat": 100, "valid_from": "2026-10-17"})
    add_offer(p, {"id": "today", "kind": "coupon", "flat": 100, "valid_until": "2026-10-16"})  # whole day
    assert [o.id for o in load_offers(p)] == ["today"]
    assert len(load_offers(p, include_inactive=True)) == 3


def test_sale_coupon_cli(tmp_path, monkeypatch, capsys):
    from goldtracker.__main__ import main

    p = tmp_path / "offers.json"
    p.write_text("[]")
    monkeypatch.setenv("GOLD_OFFERS_PATH", str(p))
    main(["sale-coupon", "add", "myntra", "BLINK750", "--flat", "750", "--until", "2026-10-16T23:59"])
    saved = json.loads(p.read_text())
    assert saved[0]["public"] is True and saved[0]["flat"] == 750
    main(["sale-coupon", "remove", "BLINK750"])
    assert json.loads(p.read_text()) == []


def test_run_once_survives_blocked_retailers(tmp_path, monkeypatch):
    from goldtracker import rates as rates_mod
    from goldtracker.__main__ import main

    monkeypatch.setenv("GOLD_DB_PATH", str(tmp_path / "r.db"))
    monkeypatch.setenv("PUBLISH_DIR", str(tmp_path / "site"))
    monkeypatch.setenv("RETAILERS", "myntra,flipkart")
    snapshot = read_csv(ROOT / "data" / "myntra_2026-10-16.csv")

    def fake_collector(name, settings=None):
        if name == "flipkart":
            raise RuntimeError("Flipkart returned no products: access was blocked")
        return snapshot
    monkeypatch.setattr(jobs, "run_collector", fake_collector)
    monkeypatch.setattr(rates_mod, "default_get", lambda url: (FIX / ("tanishq.html" if "tanishq" in url
                                                                       else "ibja_weekday_am.html")).read_text())
    summary = tmp_path / "summary.md"
    main(["run-once", "--report", str(tmp_path / "report.json"), "--summary", str(summary)])
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["rates"]["ibja"]["ok"] and report["rates"]["tanishq"]["ok"]
    assert report["retailers"]["myntra"]["saved"] == 109
    assert "blocked" in report["retailers"]["flipkart"]["error"]
    assert report["publish"]["deals"] > 0 and (tmp_path / "site" / "data" / "deals.json").exists()
    md = summary.read_text()
    assert "| flipkart | ❌" in md and "| myntra | ✅ 109 listings" in md


def test_freshness_rows(tmp_path, monkeypatch):
    from goldtracker import db
    from goldtracker.config import Settings
    from goldtracker.status import freshness
    monkeypatch.delenv("GOLD_RATE_SOURCES", raising=False)
    conn = db.connect(tmp_path / "g.db")
    db.init_db(conn)
    db.save_rate(conn, 14248, "ibja", as_of="2026-10-23T12:00:00+05:30")
    run = db.start_run(conn, "rates")
    db.finish_run(conn, run, ok=True, count=1, error="tanishq: HTTPStatusError: 403 Forbidden")
    run = db.start_run(conn, "myntra")
    db.finish_run(conn, run, ok=False, error="RuntimeError: Myntra returned no products: blocked")
    rows = {r["id"]: r for r in freshness(conn, Settings())}
    assert rows["ibja"]["ok"] and rows["ibja"]["as_of"] == "2026-10-23T12:00:00+05:30"
    assert not rows["tanishq"]["ok"] and "403" in rows["tanishq"]["error"]
    assert "goodreturns" not in rows  # never fetched, never failed
    assert rows["myntra"]["kind"] == "retailer" and not rows["myntra"]["ok"] and "blocked" in rows["myntra"]["error"]
