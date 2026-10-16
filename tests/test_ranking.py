from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from goldtracker import db
from goldtracker.collectors import save_listings
from goldtracker.collectors.csv_import import read_csv
from goldtracker.offers import load_offers
from goldtracker.ranking import per_fine_gram, rank

ROOT = Path(__file__).parent.parent


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    db.init_db(c)
    db.save_rate(c, 14787, source="test")
    save_listings(c, read_csv(ROOT / "data" / "sample_listings.csv"))
    yield c
    c.close()


def test_per_fine_gram_example_from_tracker():
    # 1 g 22K coin at 15,000 with a 400 coupon -> 14,600 / 0.916 ~= 15,939
    assert per_fine_gram(14600, 1, 0.916) == pytest.approx(15938.86, abs=0.01)


def test_rank_sorted_and_complete(conn):
    deals = rank(conn, load_offers(ROOT / "data" / "offers.json"), held={"sbi-card", "cb-1350-29k"})
    assert len(deals) == 14
    assert [d.per_fine_g for d in deals] == sorted(d.per_fine_g for d in deals)
    best = deals[0]
    assert best.title.startswith("PNG Jewellers 2.5 gram")
    assert best.breakdown["effective_price"] == 35991
    assert best.per_fine_g == pytest.approx(35991 / (2.5 * 0.995), abs=0.01)
    assert best.premium_vs_spot < 0


def test_filters(conn):
    offers = load_offers(ROOT / "data" / "offers.json")
    assert {d.retailer for d in rank(conn, offers, retailer="myntra")} == {"myntra"}
    assert {d.weight_g for d in rank(conn, offers, weight_g=10)} == {10}
    assert {d.purity for d in rank(conn, offers, purity=0.916)} == {0.916}


def test_price_history_uses_latest(conn):
    pid = conn.execute("SELECT id FROM products WHERE retailer_sku='sample-m1'").fetchone()[0]
    db.add_price(conn, pid, list_price=15000, seen_at="2999-01-01T00:00:00+00:00")
    d = [x for x in rank(conn, []) if x.product_id == pid][0]
    assert d.breakdown["list_price"] == 15000


def test_out_of_stock_hidden_by_default(conn):
    pid = conn.execute("SELECT id FROM products WHERE retailer_sku='sample-m1'").fetchone()[0]
    db.add_price(conn, pid, list_price=15000, in_stock=False, seen_at="2999-01-01T00:00:00+00:00")
    assert pid not in {d.product_id for d in rank(conn, [])}
    assert pid in {d.product_id for d in rank(conn, [], in_stock_only=False)}


def test_api(tmp_path, monkeypatch):
    monkeypatch.setenv("GOLD_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("MY_OFFERS", "sbi-card,cb-1350-29k")
    with db.open_db(tmp_path / "t.db") as c:
        db.save_rate(c, 14787, source="test")
        save_listings(c, read_csv(ROOT / "data" / "sample_listings.csv"))
    from goldtracker.web.app import app

    client = TestClient(app)
    assert client.get("/").status_code == 200
    meta = client.get("/api/meta").json()
    assert meta["rate"]["rate_24k"] == 14787 and "amazon" in meta["retailers"]
    deals = client.get("/api/deals").json()
    assert deals["count"] == 14 and deals["deals"][0]["breakdown"]["effective_price"] == 35991
    none_held = client.get("/api/deals", params={"offers": ""}).json()
    assert none_held["deals"][0]["breakdown"]["card"] == 0
    assert client.get("/api/deals", params={"retailer": "myntra"}).json()["count"] == 7


def test_premium_inr_and_coupon_flag(conn):
    deals = rank(conn, load_offers(ROOT / "data" / "offers.json"), held={"sbi-card", "cb-1350-29k"})
    best = deals[0]
    assert best.premium_inr == pytest.approx(best.per_fine_g - 14787 / 0.999, abs=0.01)
    myntra = [d for d in deals if d.retailer == "myntra"]
    assert any(d.has_coupon for d in myntra)
    assert all(d.has_coupon for d in rank(conn, [], coupon_only=True))


def test_brand_filter_case_insensitive(conn):
    assert {d.brand for d in rank(conn, [], brand="bhima")} == {"BHIMA"}


def test_price_drop_and_30d_low(conn):
    pid = conn.execute("SELECT id FROM products WHERE retailer_sku='sample-m1'").fetchone()[0]
    d = [x for x in rank(conn, []) if x.product_id == pid][0]
    assert d.prev_price is None and d.price_change is None and not d.at_30d_low  # flat price isn't news
    db.add_price(conn, pid, list_price=15700, seen_at="2999-01-01T00:00:00+00:00")
    d = [x for x in rank(conn, []) if x.product_id == pid][0]
    assert d.prev_price == 15980 and d.price_change == -280 and d.at_30d_low
    db.add_price(conn, pid, list_price=15800, seen_at="2999-01-02T00:00:00+00:00")
    d = [x for x in rank(conn, []) if x.product_id == pid][0]
    assert d.price_change == 100 and not d.at_30d_low


def test_api_wallet_history_and_filters(tmp_path, monkeypatch):
    monkeypatch.setenv("GOLD_DB_PATH", str(tmp_path / "w.db"))
    monkeypatch.setenv("MY_OFFERS", "")
    with db.open_db(tmp_path / "w.db") as c:
        db.save_rate(c, 14787, source="test")
        save_listings(c, read_csv(ROOT / "data" / "sample_listings.csv"))
    from goldtracker.web.app import app

    client = TestClient(app)
    # 7% wallet on 39,992 = 2,799.44, uncapped, no fee
    d = client.get("/api/deals", params={"offers": "", "wallet_pct": 7, "retailer": "amazon"}).json()["deals"]
    ring = [x for x in d if x["title"].startswith("PNG Jewellers 2.5")][0]
    assert ring["breakdown"]["card"] == pytest.approx(2799.44) and ring["breakdown"]["fee"] == 0
    # wallet doesn't apply on Myntra
    m = client.get("/api/deals", params={"offers": "", "wallet_pct": 7, "retailer": "myntra"}).json()["deals"]
    assert all(x["breakdown"]["card"] == 0 for x in m)
    assert client.get("/api/deals", params={"wallet_pct": 50}).status_code == 422
    assert "BHIMA" in client.get("/api/meta").json()["brands"]
    assert client.get("/api/deals", params={"coupon_only": True}).json()["count"] == 6
    pid = ring["product_id"]
    h = client.get(f"/api/history/{pid}").json()
    assert len(h["points"]) == 1 and h["points"][0]["list_price"] == 39992


def test_csv_backfill_builds_history(tmp_path):
    c = db.connect(":memory:")
    db.init_db(c)
    p = tmp_path / "h.csv"
    p.write_text("retailer,sku,title,price,seen_at\n"
                 "myntra,x1,Kalyan 24K 999 Gold Coin 1 g,16000,2026-10-10\n"
                 "myntra,x1,Kalyan 24K 999 Gold Coin 1 g,15500,2026-10-12T09:30\n")
    save_listings(c, read_csv(p))
    rows = c.execute("SELECT seen_at, list_price FROM prices ORDER BY seen_at").fetchall()
    assert [r["list_price"] for r in rows] == [16000, 15500]
    assert rows[0]["seen_at"] == "2026-10-09T18:30:00+00:00"  # midnight IST in UTC
    d = rank(c, [])[0]
    assert d.prev_price == 16000 and d.price_change == -500


def test_sanity_check_drops_mislabelled_weight(conn):
    # "500 g" for INR 8,880 is really 500 mg: must not top the ranking
    from goldtracker.collectors import RawListing
    save_listings(conn, [RawListing(retailer="myntra", retailer_sku="bad", price=8880,
                                    title="C KRISHNIAH CHETTY 24KT Gold Goddess Lakshmi Coin - 500 g")])
    rejected = []
    deals = rank(conn, [], rejected=rejected)
    assert all(d.title.find("500 g") < 0 for d in deals)
    assert rejected and rejected[0]["premium_vs_spot"] < -0.9
