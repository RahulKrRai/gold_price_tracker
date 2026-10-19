import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from goldtracker import db
from goldtracker.collectors import save_listings
from goldtracker.collectors.amazon import AmazonConfigError, collect, parse_items
from goldtracker.collectors.csv_import import read_csv
from goldtracker.config import Settings
from goldtracker.publish import publish
from goldtracker.rates import IST

ROOT = Path(__file__).parent.parent


# --- publish (GitHub Pages) ------------------------------------------------------------------

def test_publish_writes_static_site(tmp_path, monkeypatch):
    monkeypatch.setenv("GOLD_DB_PATH", str(tmp_path / "p.db"))
    monkeypatch.setenv("PUBLISH_DIR", str(tmp_path / "site"))
    monkeypatch.setenv("MY_OFFERS", "sbi-card,cb-1350-29k")
    s = Settings()
    with db.open_db(s.db_path) as c:
        db.save_rate(c, 14640.6, "ibja", as_of="2026-10-16T17:00:00+05:30", session="PM")
        save_listings(c, read_csv(ROOT / "data" / "sample_listings.csv"))
    r = publish(s, now=datetime(2026, 10, 16, 18, 0, tzinfo=IST))
    site = tmp_path / "site"
    assert r["deals"] == 14 and not r["pushed"]
    page = (site / "index.html").read_text()
    assert "window.GT_STATIC = true" in page and page.index("GT_STATIC") < page.rindex("<script>")
    deals = json.loads((site / "data" / "deals.json").read_text())["deals"]
    assert deals[0]["breakdown"]["effective_price"] == 35991  # SBI + cashback applied
    meta = json.loads((site / "data" / "meta.json").read_text())
    assert meta["benchmark"] == "ibja" and meta["published_at"].startswith("2026-10-16T18:00")
    assert str(tmp_path) not in (site / "data" / "meta.json").read_text()  # no local paths leak
    hist = json.loads((site / "data" / "history.json").read_text())
    assert str(deals[0]["product_id"]) in hist
    assert (site / ".nojekyll").exists()


# --- Amazon Creators API (mocked) ----------------------------------------------------------

SEARCH_RESPONSE = {"searchResult": {"items": [
    {"asin": "B0TEST0001", "detailPageURL": "https://www.amazon.in/dp/B0TEST0001",
     "itemInfo": {"title": {"displayValue": "MMTC PAMP 24K 999.9 Lakshmi Gold Coin 2 Gram"},
                  "byLineInfo": {"brand": {"displayValue": "MMTC-PAMP"}}},
     "offersV2": {"listings": [{"price": {"money": {"amount": 32480, "currency": "INR"}},
                                "availability": {"type": "IN_STOCK"}}]}},
    {"asin": "B0TEST0002", "itemInfo": {"title": {"displayValue": "No price item"}}},
    {"ASIN": "B0TEST0003", "DetailPageURL": "https://www.amazon.in/dp/B0TEST0003",
     "ItemInfo": {"Title": {"DisplayValue": "Kalyan 22K 916 Gold Coin 4 g"}},
     "Offers": {"Listings": [{"Price": {"Amount": 60715}, "Availability": {"Type": "OUT_OF_STOCK"}}]}},
]}}


def test_parse_items_camel_and_pascal():
    items = {i.retailer_sku: i for i in parse_items(SEARCH_RESPONSE)}
    assert set(items) == {"B0TEST0001", "B0TEST0003"}
    a = items["B0TEST0001"]
    assert (a.price, a.brand, a.in_stock) == (32480, "MMTC-PAMP", True)
    assert items["B0TEST0003"].in_stock is False


def test_collect_with_mock_server(monkeypatch):
    for k, v in {"AMAZON_CLIENT_ID": "id", "AMAZON_CLIENT_SECRET": "secret", "AMAZON_PARTNER_TAG": "tag-21",
                 "AMAZON_CREDENTIAL_VERSION": "2.2", "AMAZON_KEYWORDS": "gold coin"}.items():
        monkeypatch.setenv(k, v)
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        if req.url.path.endswith("/oauth2/token"):
            assert req.headers["Authorization"].startswith("Basic ")
            assert b"scope=creatorsapi%2Fdefault" in req.content
            return httpx.Response(200, json={"access_token": "tok", "token_type": "bearer", "expires_in": 3600})
        assert req.url.path == "/catalog/v1/searchItems"
        assert req.headers["Authorization"] == "Bearer tok, Version 2.2"
        assert req.headers["x-marketplace"] == "www.amazon.in"
        body = json.loads(req.content)
        assert body["partnerTag"] == "tag-21" and body["itemCount"] == 10 and body["keywords"] == "gold coin"
        return httpx.Response(200, json=SEARCH_RESPONSE)

    items = collect(Settings(), client=httpx.Client(transport=httpx.MockTransport(handler)), pause=0)
    assert {i.retailer_sku for i in items} == {"B0TEST0001", "B0TEST0003"}
    assert calls[0].url.host == "creatorsapi.auth.eu-south-2.amazoncognito.com"
    assert sum(1 for c in calls if "token" in c.url.path) == 1  # token reused


def test_collect_without_keys_explains():
    with pytest.raises(AmazonConfigError, match="AMAZON_CLIENT_ID"):
        collect(Settings())
