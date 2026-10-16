import json
from pathlib import Path

import pytest

from goldtracker.offers import Offer, apply_offers, load_offers

OFFERS = load_offers(Path(__file__).parent.parent / "data" / "offers.json")
HELD = {"sbi-card", "cb-1350-29k"}


def test_matches_reference_breakdown():
    # Seen on 2026-10-16: list 39,992 - SBI 2,750 + fee 99 - cashback 1,350 = 35,991
    b = apply_offers(39992, "amazon", OFFERS, held=HELD)
    assert b.card == 2750 and b.fee == 99 and b.cashback == 1350
    assert b.effective_price == 35991


@pytest.mark.parametrize("price,card", [
    (16215, 1250),   # 1 g: 10% capped at 1,250, no extra slab
    (32277, 1750),   # 2 g: + 500 slab
    (48229, 2750),   # 3 g: + 1,500 slab
    (64905, 3750),   # 4 g: + 2,500 slab
])
def test_sbi_slabs(price, card):
    assert apply_offers(price, "amazon", OFFERS, held=HELD).card == card


def test_cashback_needs_min_spend():
    assert apply_offers(16215, "amazon", OFFERS, held=HELD).cashback == 0


def test_only_held_offers_apply():
    b = apply_offers(39992, "amazon", OFFERS, held=set())
    assert b.card == 0 and b.cashback == 0 and b.effective_price == 39992


def test_offers_are_retailer_specific():
    assert apply_offers(39992, "myntra", OFFERS, held=HELD).effective_price == 39992


def test_best_card_wins():
    b = apply_offers(16215, "amazon", OFFERS, held={"sbi-card", "icici-amazon-pay"})
    assert b.card_label == "SBI Credit/Debit Card"  # 1,250 - 99 beats 5% = 811
    # At 1,500: SBI 150 - 99 fee = 51 net; ICICI 5% = 75 -> ICICI wins
    b = apply_offers(1500, "amazon", OFFERS, held={"sbi-card", "icici-amazon-pay"})
    assert b.card_label == "ICICI Amazon Pay Credit Card" and b.fee == 0


def test_first_order_only_is_opt_in():
    b = apply_offers(15980, "myntra", OFFERS, held=None)
    assert b.coupon == 0
    b = apply_offers(15980, "myntra", OFFERS, held=None, include_first_order=True)
    assert b.coupon == 200


def test_listing_coupon_vs_stored_coupon_best_one_wins():
    b = apply_offers(15980, "myntra", OFFERS, held=None, include_first_order=True, listing_coupon=("BFF500", 500))
    assert b.coupon == 500 and b.coupon_label == "BFF500"
    assert b.effective_price == 15480  # matches Myntra listing seen on 2026-10-16


def test_cap_and_min_spend():
    o = Offer(id="x", kind="card", label="x", percent=10, max_cap=100, min_spend=1000)
    assert o.discount_on(999) == 0
    assert o.discount_on(5000) == 100


def test_offer_json_roundtrip(tmp_path):
    p = tmp_path / "o.json"
    p.write_text(json.dumps([{"id": "a", "kind": "coupon", "flat": 50, "active": False},
                             {"id": "b", "kind": "coupon", "flat": 75}]))
    assert [o.id for o in load_offers(p)] == ["b"]
