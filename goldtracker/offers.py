"""Coupon, card and cashback rules.

Order of application (matches how Indian retailers usually price checkout):
  1. Best single coupon (listing coupon or a stored coupon offer). Coupons don't stack.
  2. Card discount on the amount after the coupon, respecting min spend and max cap, plus any fee.
  3. Cashback (credited later) on the amount after the coupon.
Only offers the buyer actually holds (MY_OFFERS) are applied, except `public` offers (sale-wide
coupons anyone can use, e.g. a Myntra flash coupon), which always apply. First-order-only offers are
skipped unless INCLUDE_FIRST_ORDER is on. Offers outside valid_from/valid_until are ignored.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass(frozen=True)
class Offer:
    id: str
    kind: str                      # 'coupon' | 'card' | 'cashback'
    label: str
    retailer: str | None = None    # None = any retailer
    percent: float = 0.0
    flat: float = 0.0
    min_spend: float = 0.0
    max_cap: float | None = None
    fee: float = 0.0
    first_order_only: bool = False
    tiers: tuple["Offer", ...] = ()  # extra spend slabs, e.g. SBI "+ up to 2,500 extra"
    public: bool = False             # applies to everyone (sale coupon), no need to hold it
    valid_from: str | None = None    # ISO date/time; naive values are India time
    valid_until: str | None = None

    def is_active(self, now: datetime | None = None) -> bool:
        now = now or _now()
        return ((self.valid_from is None or _when(self.valid_from, end=False) <= now)
                and (self.valid_until is None or now <= _when(self.valid_until, end=True)))

    def discount_on(self, amount: float) -> float:
        """INR off for this offer on `amount` (fee not included). 0 if min spend isn't met."""
        if amount < self.min_spend:
            return 0.0
        value = amount * self.percent / 100.0 + self.flat
        if self.max_cap is not None:
            value = min(value, self.max_cap)
        # Extra slabs: only the highest slab the amount qualifies for is added
        value += max((t.discount_on(amount) for t in self.tiers), default=0.0)
        return round(min(value, amount), 2)

    def applies_to(self, retailer: str) -> bool:
        return self.retailer is None or self.retailer == retailer

    @classmethod
    def from_dict(cls, d: dict) -> "Offer":
        tiers = tuple(cls.from_dict({"id": f"{d['id']}-t{i}", "kind": d["kind"], "label": "", **t})
                      for i, t in enumerate(d.get("tiers", [])))
        return cls(
            id=d["id"], kind=d["kind"], label=d.get("label", d["id"]), retailer=d.get("retailer"),
            percent=float(d.get("percent", 0)), flat=float(d.get("flat", 0)),
            min_spend=float(d.get("min_spend", 0)),
            max_cap=None if d.get("max_cap") is None else float(d["max_cap"]),
            fee=float(d.get("fee", 0)), first_order_only=bool(d.get("first_order_only", False)), tiers=tiers,
            public=bool(d.get("public", False)), valid_from=d.get("valid_from"), valid_until=d.get("valid_until"),
        )


@dataclass
class Breakdown:
    list_price: float
    coupon: float = 0.0
    coupon_label: str | None = None
    card: float = 0.0
    card_label: str | None = None
    fee: float = 0.0
    cashback: float = 0.0
    cashback_label: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def pay_at_checkout(self) -> float:
        return round(self.list_price - self.coupon - self.card + self.fee, 2)

    @property
    def effective_price(self) -> float:
        """What it really costs once cashback lands."""
        return round(self.pay_at_checkout - self.cashback, 2)

    def as_dict(self) -> dict:
        return {
            "list_price": self.list_price, "coupon": self.coupon, "coupon_label": self.coupon_label,
            "card": self.card, "card_label": self.card_label, "fee": self.fee,
            "cashback": self.cashback, "cashback_label": self.cashback_label,
            "pay_at_checkout": self.pay_at_checkout, "effective_price": self.effective_price,
            "notes": self.notes,
        }


def _now() -> datetime:
    """Current India time; tests replace this to pin the date."""
    return datetime.now(IST)


def _when(value: str, *, end: bool) -> datetime:
    """'2026-10-20' means the whole day (start or end of it); naive times are India time."""
    if len(value) == 10:
        dt = datetime.fromisoformat(value) + (timedelta(days=1, microseconds=-1) if end else timedelta())
    else:
        dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=IST)


def load_offers(path: Path | str, now: datetime | None = None, include_inactive: bool = False) -> list[Offer]:
    p = Path(path)
    if not p.exists():
        return []
    offers = [Offer.from_dict(d) for d in json.loads(p.read_text(encoding="utf-8")) if d.get("active", True)]
    return offers if include_inactive else [o for o in offers if o.is_active(now)]


def add_offer(path: Path | str, offer: dict) -> None:
    """Add or replace an offer (by id) in the offers file."""
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    data = [d for d in data if d.get("id") != offer["id"]] + [offer]
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def remove_offer(path: Path | str, offer_id: str) -> bool:
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    kept = [d for d in data if d.get("id") != offer_id]
    p.write_text(json.dumps(kept, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return len(kept) < len(data)


def apply_offers(list_price: float, retailer: str, offers: list[Offer], *, held: set[str] | None = None,
                 include_first_order: bool = False, listing_coupon: tuple[str, float] | None = None) -> Breakdown:
    """Compute the best price for one listing.

    held: ids of offers the buyer can use; None means all.
    listing_coupon: (code, flat INR off) shown on the product listing itself.
    """
    b = Breakdown(list_price=list_price)
    usable = [o for o in offers
              if o.applies_to(retailer)
              and (held is None or o.public or o.id in held)
              and (include_first_order or not o.first_order_only)]

    # 1. best single coupon
    candidates: list[tuple[float, str]] = []
    if listing_coupon and listing_coupon[1]:
        candidates.append((min(listing_coupon[1], list_price), listing_coupon[0]))
    for o in usable:
        if o.kind == "coupon":
            d = o.discount_on(list_price)
            if d > 0:
                candidates.append((d, o.label))
    if candidates:
        b.coupon, b.coupon_label = max(candidates)
    after_coupon = list_price - b.coupon

    # 2. best card offer (one card per order)
    best_card: tuple[float, Offer] | None = None
    for o in usable:
        if o.kind == "card":
            net = o.discount_on(after_coupon) - o.fee
            if o.discount_on(after_coupon) > 0 and (best_card is None or net > best_card[0]):
                best_card = (net, o)
            elif o.discount_on(after_coupon) == 0 and after_coupon < o.min_spend:
                b.notes.append(f"{o.label}: needs min spend ₹{o.min_spend:,.0f}")
    if best_card:
        o = best_card[1]
        b.card, b.card_label, b.fee = o.discount_on(after_coupon), o.label, o.fee

    # 3. cashback offers stack with each other only if the retailer allows; take the best one
    cbs = [(o.discount_on(after_coupon), o.label) for o in usable if o.kind == "cashback"]
    cbs = [c for c in cbs if c[0] > 0]
    if cbs:
        b.cashback, b.cashback_label = max(cbs)
    return b
