"""SQLite storage: products, prices, offers, gold_rates."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id            INTEGER PRIMARY KEY,
    retailer      TEXT NOT NULL,              -- 'myntra', 'amazon', ...
    retailer_sku  TEXT NOT NULL,              -- the retailer's own product id
    title         TEXT NOT NULL,
    brand         TEXT,
    url           TEXT,
    weight_g      REAL,                       -- parsed from title, NULL if unknown
    purity        REAL,                       -- 0.999, 0.995, 0.916 ... NULL if unknown
    form          TEXT,                       -- 'coin', 'bar', 'pendant', 'ring', 'other'
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    UNIQUE (retailer, retailer_sku)
);

CREATE TABLE IF NOT EXISTS prices (
    id            INTEGER PRIMARY KEY,
    product_id    INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    seen_at       TEXT NOT NULL,
    list_price    REAL NOT NULL,              -- price shown on the product page (incl. GST)
    mrp           REAL,                       -- struck-out price, if any
    coupon_code   TEXT,                       -- coupon shown on the listing, if any
    coupon_value  REAL,                       -- flat INR off for that coupon
    in_stock      INTEGER NOT NULL DEFAULT 1,
    stock_left    INTEGER                     -- "N left", if shown
);
CREATE INDEX IF NOT EXISTS idx_prices_product_time ON prices(product_id, seen_at DESC);

CREATE TABLE IF NOT EXISTS offers (
    id               TEXT PRIMARY KEY,        -- e.g. 'sbi-card'
    retailer         TEXT,                    -- NULL = any retailer
    kind             TEXT NOT NULL,           -- 'coupon', 'card', 'cashback'
    label            TEXT NOT NULL,
    percent          REAL DEFAULT 0,          -- e.g. 10 for 10%
    flat             REAL DEFAULT 0,          -- flat INR off
    min_spend        REAL DEFAULT 0,
    max_cap          REAL,                    -- NULL = no cap
    fee              REAL DEFAULT 0,          -- processing fee added back
    first_order_only INTEGER DEFAULT 0,
    active           INTEGER DEFAULT 1,
    valid_until      TEXT
);

CREATE TABLE IF NOT EXISTS gold_rates (
    id          INTEGER PRIMARY KEY,
    fetched_at  TEXT NOT NULL,
    rate_24k    REAL NOT NULL,               -- INR per gram, excl. GST
    rate_22k    REAL NOT NULL,
    source      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts_sent (
    product_id  INTEGER NOT NULL,
    per_fine_g  REAL NOT NULL,
    sent_at     TEXT NOT NULL,
    PRIMARY KEY (product_id, per_fine_g)
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path | str) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


@contextmanager
def open_db(path: Path | str) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        init_db(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert_product(conn: sqlite3.Connection, *, retailer: str, retailer_sku: str, title: str,
                   brand: str | None, url: str | None, weight_g: float | None,
                   purity: float | None, form: str | None) -> int:
    ts = now_iso()
    conn.execute(
        """
        INSERT INTO products (retailer, retailer_sku, title, brand, url, weight_g, purity, form, first_seen, last_seen)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (retailer, retailer_sku) DO UPDATE SET
            title = excluded.title, brand = excluded.brand, url = excluded.url,
            weight_g = excluded.weight_g, purity = excluded.purity, form = excluded.form,
            last_seen = excluded.last_seen
        """,
        (retailer, retailer_sku, title, brand, url, weight_g, purity, form, ts, ts),
    )
    row = conn.execute(
        "SELECT id FROM products WHERE retailer = ? AND retailer_sku = ?", (retailer, retailer_sku)
    ).fetchone()
    return int(row["id"])


def add_price(conn: sqlite3.Connection, product_id: int, *, list_price: float, mrp: float | None = None,
              coupon_code: str | None = None, coupon_value: float | None = None,
              in_stock: bool = True, stock_left: int | None = None, seen_at: str | None = None) -> None:
    conn.execute(
        """INSERT INTO prices (product_id, seen_at, list_price, mrp, coupon_code, coupon_value, in_stock, stock_left)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (product_id, seen_at or now_iso(), list_price, mrp, coupon_code, coupon_value, int(in_stock), stock_left),
    )


def save_rate(conn: sqlite3.Connection, rate_24k: float, source: str, rate_22k: float | None = None) -> None:
    conn.execute(
        "INSERT INTO gold_rates (fetched_at, rate_24k, rate_22k, source) VALUES (?, ?, ?, ?)",
        (now_iso(), rate_24k, rate_22k if rate_22k is not None else round(rate_24k * 0.916, 2), source),
    )


def latest_rate(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM gold_rates ORDER BY fetched_at DESC, id DESC LIMIT 1").fetchone()


def price_stats(conn: sqlite3.Connection, days: int = 30) -> dict[int, dict]:
    """Per product: lowest list price in the last `days`, and the previous different price."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    stats: dict[int, dict] = {}
    for r in conn.execute(
        "SELECT product_id, MIN(list_price) AS low, COUNT(*) AS n FROM prices WHERE seen_at >= ? GROUP BY product_id",
        (since,),
    ):
        stats[r["product_id"]] = {"low_30d": r["low"], "samples_30d": r["n"], "prev_price": None}
    # previous price = most recent row whose price differs from the latest one
    for r in conn.execute(
        """
        WITH ranked AS (
            SELECT product_id, list_price, seen_at,
                   ROW_NUMBER() OVER (PARTITION BY product_id ORDER BY seen_at DESC, id DESC) AS rn
            FROM prices
        ), latest AS (SELECT product_id, list_price FROM ranked WHERE rn = 1)
        SELECT r.product_id, r.list_price
        FROM ranked r JOIN latest l ON l.product_id = r.product_id
        WHERE r.rn > 1 AND r.list_price != l.list_price
          AND r.rn = (SELECT MIN(r2.rn) FROM ranked r2
                      WHERE r2.product_id = r.product_id AND r2.rn > 1 AND r2.list_price != l.list_price)
        """
    ):
        stats.setdefault(r["product_id"], {"low_30d": None, "samples_30d": 0, "prev_price": None})
        stats[r["product_id"]]["prev_price"] = r["list_price"]
    return stats


def price_history(conn: sqlite3.Connection, product_id: int, days: int = 30) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    rows = conn.execute(
        "SELECT seen_at, list_price, in_stock FROM prices WHERE product_id = ? AND seen_at >= ? ORDER BY seen_at",
        (product_id, since),
    ).fetchall()
    return [dict(r) for r in rows]


def latest_listings(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Each product with its most recent price row."""
    return conn.execute(
        """
        SELECT p.*, pr.list_price, pr.mrp, pr.coupon_code, pr.coupon_value, pr.in_stock,
               pr.stock_left, pr.seen_at
        FROM products p
        JOIN prices pr ON pr.id = (
            SELECT id FROM prices WHERE product_id = p.id ORDER BY seen_at DESC, id DESC LIMIT 1
        )
        """
    ).fetchall()
