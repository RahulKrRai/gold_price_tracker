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
