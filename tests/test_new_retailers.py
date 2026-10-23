"""Ajio, Flipkart and Amazon (browser) collectors, using data shapes seen on the live sites on 2026-10-23."""

import pytest

from goldtracker import db
from goldtracker.collectors import ajio, amazon_web, flipkart, save_listings
from goldtracker.parser import parse_title
from goldtracker.ranking import rank

AJIO_ITEMS = [
    {"code": "600528930", "name": "1 Gm 24 Kt (999) Yellow Gold Bar", "brand": "Bangalore Refinery",
     "price": 15577, "mrp": 16447.34, "offer": 15577, "couponStatus": "Coupon Applicable",
     "url": "/bangalore-refinery-1-gm-24-kt-999-yellow-gold-bar/p/6005289300_multi",
     "brick": "Bars & Coins", "vertical": "Fine Jewellery"},
    {"code": "600598510", "name": "5 gm 24 Kt (999.9+) Lakshmi Yellow Gold Coin", "brand": "Mmtc Pamp",
     "price": 78346, "mrp": 80000, "offer": 78346, "url": "/mmtc-pamp-5-gm/p/600598510_multi",
     "brick": "Bars & Coins", "vertical": "Fine Jewellery"},
    {"code": "600641327", "name": "1 Gm 22 Kt (916) Lakshmi Coin", "brand": "Bhima Jewels", "price": 14426,
     "mrp": 15100, "offer": 14426, "url": "/bhima-1-gm/p/600641327_multi", "brick": "Bars & Coins",
     "vertical": "Fine Jewellery"},
    {"code": "700000001", "name": "10 g 999 Silver Lakshmi Coin", "brand": "Ajio Silver", "price": 1400,
     "url": "/x/p/700000001", "brick": "Idols & Coins", "vertical": "Silver Jewellery"},
    {"code": "700000002", "name": "Gold-Plated Pendant Necklace", "brand": "X", "price": 999,
     "url": "/y/p/700000002", "brick": "Necklaces & Pendants", "vertical": "Fine Jewellery"},
]

FLIPKART_CARDS = [
    {"id": "CONGUHZGJPQ4A8DB", "href": "/pc-chandra-jewellers-pure-24-999-k-2-g-gold-coin/p/itm6ccad9267818f",
     "title": "24K999GC2 24 (999) K 2 g Gold Coin",
     "lines": ["PC Chandra Jewellers", "24K999GC2 24 (999) K 2 g Gold Coin", "₹32,246"]},
    {"id": "CONHRZ6EVQXCZKQJ", "href": "/mmtc-pamp-2-g-oval/p/itm4b5b8d491c0de",
     "title": "AUYyOPG2.01414 24 (9999) K 2 g Gold Coin",
     "lines": ["MMTC-PAMP India Pvt Ltd", "AUYyOPG2.01414 24 (9999) K 2 g Gold Coin", "₹32,730", "₹33,500",
               "2% off", "Only 3 left"]},
    {"id": "CONHM8GSAKMCNGMA", "href": "/pc-chandra-0-5-g/p/itm112a579c5ceb3",
     "title": "24K999GC500 24 (999) K 0.5 g Gold Coin",
     "lines": ["PC Chandra Jewellers", "24K999GC500 24 (999) K 0.5 g Gold Coin", "₹8,427"]},
    {"id": "CONGHSF7MWZB6GAH", "href": "/pc-chandra-1-g/p/itm6445da04f1cac", "title": None,
     "lines": ["PC Chandra Jewellers", "24KGC1P 24 (995) K 1 g Gold Coin", "₹16,110", "Top Discount of the Sale"]},
    {"id": "BAD", "href": "/x/p/itm0", "title": "no price card", "lines": ["Brand", "no price card"]},
]

AMAZON_CARDS = [
    {"asin": "B0GJLG6F9Q", "h2s": ["INDRIYA", "24 KT 999 5gm Lakshmi-Ganesha Gold Bar/Gold Coin - for Dhanteras"],
     "aria": "Sponsored Ad - 24 KT 999 5gm Lakshmi-Ganesha Gold Bar/Gold Coin - for Dhanteras",
     "price": "₹79,146", "mrp": "₹95,000", "sponsored": True},
    {"asin": "B01HVB3PSY", "h2s": ["Bangalore Refinery", "24k (999.9) 1 gm Yellow Gold Bar"],
     "aria": "24k (999.9) 1 gm Yellow Gold Bar", "price": "₹16,125", "mrp": None, "sponsored": False},
    {"asin": "B09RSRYJM7", "h2s": ["Joyalukkas", "1 gm 24K (999) Pure Gold Bar | Assayer Certified"],
     "aria": None, "price": "₹16,300", "mrp": "₹16,300", "sponsored": False, "unavailable": True},
    {"asin": "B0NOPRICE1", "h2s": ["X", "Gold coin"], "aria": None, "price": None},
]


def test_ajio_mapping():
    items = {i.retailer_sku: i for i in ajio.parse(AJIO_ITEMS)}
    assert set(items) == {"600528930", "600598510", "600641327"}  # silver and necklace dropped
    a = items["600528930"]
    assert a.title == "Bangalore Refinery 1 Gm 24 Kt (999) Yellow Gold Bar"
    assert (a.price, a.mrp) == (15577, 16447.34)
    assert a.url == "https://www.ajio.com/bangalore-refinery-1-gm-24-kt-999-yellow-gold-bar/p/6005289300_multi"


def test_flipkart_mapping():
    items = {i.retailer_sku: i for i in flipkart.parse(FLIPKART_CARDS)}
    assert set(items) == {"CONGUHZGJPQ4A8DB", "CONHRZ6EVQXCZKQJ", "CONHM8GSAKMCNGMA", "CONGHSF7MWZB6GAH"}
    m = items["CONHRZ6EVQXCZKQJ"]
    assert m.title.startswith("MMTC-PAMP India Pvt Ltd") and (m.price, m.mrp, m.stock_left) == (32730, 33500, 3)
    assert items["CONGHSF7MWZB6GAH"].title == "PC Chandra Jewellers 24KGC1P 24 (995) K 1 g Gold Coin"  # no title attr
    assert items["CONGUHZGJPQ4A8DB"].url.startswith("https://www.flipkart.com/pc-chandra")


def test_amazon_web_mapping():
    items = {i.retailer_sku: i for i in amazon_web.parse(AMAZON_CARDS)}
    assert set(items) == {"B0GJLG6F9Q", "B01HVB3PSY", "B09RSRYJM7"}
    s = items["B0GJLG6F9Q"]
    assert s.title.startswith("INDRIYA 24 KT 999 5gm") and "Sponsored" not in s.title
    assert (s.price, s.mrp, s.url) == (79146, 95000, "https://www.amazon.in/dp/B0GJLG6F9Q")
    assert items["B09RSRYJM7"].in_stock is False and items["B09RSRYJM7"].mrp is None


@pytest.mark.parametrize("title,weight,purity", [
    ("PC Chandra Jewellers 24K999GC2 24 (999) K 2 g Gold Coin", 2, 0.999),
    ("MMTC-PAMP India Pvt Ltd AUYyOPG2.01414 24 (9999) K 2 g Gold Coin", 2, 0.9999),
    ("PC Chandra Jewellers 24K999GC500 24 (999) K 0.5 g Gold Coin", 0.5, 0.999),
    ("PC Chandra Jewellers 24KGC1P 24 (995) K 1 g Gold Coin", 1, 0.995),
    ("Mmtc Pamp 5 gm 24 Kt (999.9+) Lakshmi Yellow Gold Coin", 5, 0.9999),
    ("Bhima Jewels 1 Gm 22 Kt (916) Lakshmi Coin", 1, 0.916),
    ("INDRIYA 24 KT 999 5gm Lakshmi-Ganesha Gold Bar/Gold Coin - for Dhanteras", 5, 0.999),
    ("Bangalore Refinery 24k (999.9) 1 gm Yellow Gold Bar", 1, 0.9999),
])
def test_new_retailer_titles_parse(title, weight, purity):
    p = parse_title(title)
    assert (p.weight_g, p.purity) == (pytest.approx(weight), pytest.approx(purity)), title


def test_all_four_retailers_rank_together():
    c = db.connect(":memory:")
    db.init_db(c)
    db.save_rate(c, 14145, "ibja", as_of="2026-10-23T12:00:00+05:30", session="AM")
    for items in (ajio.parse(AJIO_ITEMS), flipkart.parse(FLIPKART_CARDS), amazon_web.parse(AMAZON_CARDS)):
        save_listings(c, items)
    deals = rank(c, [])
    assert {d.retailer for d in deals} == {"ajio", "flipkart", "amazon"}
    assert [d.per_fine_g for d in deals] == sorted(d.per_fine_g for d in deals)


def test_why_empty_explains_blocks_and_layout_changes():
    from goldtracker.collectors import browser

    browser.LAST_PAGES[:] = [{"status": 403, "title": "Access Denied", "snippet": "You don't have permission"}]
    msg = browser.why_empty("Myntra")
    assert "refused the request" in msg and "HTTP 403" in msg and "Access Denied" in msg
    browser.LAST_PAGES[:] = [{"status": 200, "title": "Gold Coins - Buy online", "snippet": "Filters Sort by"}]
    assert "layout changed" in browser.why_empty("Ajio")
    browser.LAST_PAGES.clear()
    assert "access was blocked" in browser.why_empty("Amazon")
