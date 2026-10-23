"""Tata CLiQ, CoinBazaar and Zepto collectors, using data shapes seen on the live sites on 2026-10-23."""

from goldtracker import db
from goldtracker.collectors import coinbazaar, save_listings, tatacliq, zepto
from goldtracker.jobs import COLLECTORS, RETAILERS, enabled_retailers
from goldtracker.config import Settings
from goldtracker.ranking import rank

TATA_CARDS = [
    {"id": "000000006947478", "href": "/bangalore-refinery-24k-9999-5gm-gold-bar/p-mp000000006947478",
     "brand": "Bangalore Refinery", "title": "Bangalore Refinery 24k (999.9) 5gm Gold Bar", "price": "₹79025",
     "mrp": "₹90000", "lines": ["Bangalore Refinery", "Bangalore Refinery 24k (999.9) 5gm Gold Bar", "₹79025",
                                "₹9000012% off", "4.7", "(338)"]},
    # class names gone: fall back to text lines
    {"id": "000000006947479", "href": "/x/p-mp000000006947479", "brand": None, "title": None, "price": None,
     "mrp": None, "lines": ["Bangalore Refinery", "MMTC 24K 999 2 g Gold Coin", "₹31850", "₹4100022% off"]},
    {"id": "1", "href": "/y/p-mp1", "lines": ["no price"]},
]

COINBAZAAR_PAGE = {
    "pagination": {"pages_count": 2, "current_page": 1},
    "products": [
        {"id_product": 25, "name": "1 Gram Gold Coin - RSBL 24K (995 Purity) | Live Price Today",
         "price_amount": 15561.2, "regular_price_amount": 15561.2, "manufacturer_name": "RSBL",
         "url": "https://www.coinbazaar.in/1-gram/25-1-gram-gold-coin.html", "add_to_cart_url": "https://x/cart"},
        {"id_product": 8094, "name": "NIBR Gold coin of 0.5 / Half Grams in 24Kt 999 Purity", "price_amount": 8003,
         "regular_price_amount": 8400, "manufacturer_name": "NIBR", "url": "https://www.coinbazaar.in/n.html",
         "add_to_cart_url": None},
        {"id_product": 1, "name": "", "price_amount": 10},
    ],
}

ZEPTO_CARDS = [
    {"id": "ae93cec0-1", "href": "/pn/augmont-24k-0-5g/pvid/ae93cec0-1",
     "lines": ["ADD", "Augmont", "24 Karat 999 Pure Gold Coin | 0.5 g", "₹7,999", "₹12,999", "4.8", "(1.7k)"]},
    {"id": "643d7cc7-1", "href": "/pn/puja/pvid/643d7cc7-1",
     "lines": ["ADD", "Happy Mail", "Lakshmi Kuber Artificial Gold Puja Coins Set", "₹39", "₹99"]},
    {"id": "9ec7f486-1", "href": "/pn/x/pvid/9ec7f486-1",
     "lines": ["Notify Me", "Muthoot Exim", "Gold Coin 24K 999 | 1 g", "₹15,499"]},
    {"id": "bad", "href": "/pn/y/pvid/bad", "lines": ["ADD"]},
]


def test_tatacliq_cards():
    items = tatacliq.parse(TATA_CARDS)
    assert len(items) == 2
    a, b = items
    assert (a.retailer, a.retailer_sku, a.price, a.mrp, a.brand) == (
        "tatacliq", "000000006947478", 79025, 90000, "Bangalore Refinery")
    assert a.url == "https://www.tatacliq.com/bangalore-refinery-24k-9999-5gm-gold-bar/p-mp000000006947478"
    assert b.title == "MMTC 24K 999 2 g Gold Coin" and b.price == 31850 and b.mrp is None


def test_coinbazaar_json_page_and_paging():
    calls = []

    def get(url):
        calls.append(url)
        return COINBAZAAR_PAGE

    coinbazaar.PAUSE_SECONDS = 0
    items = coinbazaar.collect(get=get)
    assert calls == ["https://www.coinbazaar.in/4-buy-gold", "https://www.coinbazaar.in/4-buy-gold?page=2"]
    assert [i.retailer_sku for i in items] == ["25", "8094"]
    one, half = items
    assert one.price == 15561.2 and one.mrp is None and one.in_stock and one.brand == "RSBL"
    assert half.mrp == 8400 and not half.in_stock


def test_zepto_cards():
    items = zepto.parse(ZEPTO_CARDS)
    assert [i.retailer_sku for i in items] == ["ae93cec0-1", "643d7cc7-1", "9ec7f486-1"]
    a = items[0]
    assert (a.title, a.price, a.mrp, a.brand) == ("Augmont 24 Karat 999 Pure Gold Coin | 0.5 g", 7999, 12999, "Augmont")
    assert a.url == "https://www.zepto.com/pn/augmont-24k-0-5g/pvid/ae93cec0-1"
    assert not items[2].in_stock


def test_new_retailers_rank_and_drop_junk(tmp_path):
    conn = db.connect(tmp_path / "g.db")
    db.init_db(conn)
    db.save_rate(conn, 14248, "ibja", as_of="2026-10-23T12:00:00+05:30")
    res = save_listings(conn, tatacliq.parse(TATA_CARDS) + zepto.parse(ZEPTO_CARDS)
                        + coinbazaar.parse(COINBAZAAR_PAGE)[0])
    assert res["skipped_non_bullion"] == 1  # the artificial puja coin set
    got = {(d.retailer, d.weight_g) for d in rank(conn, [], in_stock_only=False)}
    assert {("tatacliq", 5.0), ("tatacliq", 2.0), ("zepto", 0.5), ("zepto", 1.0),
            ("coinbazaar", 1.0), ("coinbazaar", 0.5)} <= got


def test_registered_and_enabled_by_default(monkeypatch):
    monkeypatch.delenv("RETAILERS", raising=False)
    for r in ("tatacliq", "coinbazaar", "zepto"):
        assert r in COLLECTORS and r in RETAILERS
    assert {"tatacliq", "coinbazaar", "zepto"} <= set(enabled_retailers(Settings()))
