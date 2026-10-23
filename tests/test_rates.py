import sqlite3
from datetime import date, datetime
from pathlib import Path

import pytest

from goldtracker import db
from goldtracker.config import Settings
from goldtracker.rates import IST, RateError, parse_ibja, parse_tanishq, rate_is_stale, refresh_rates

FIX = Path(__file__).parent / "fixtures"


def html(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


# --- parsers ---------------------------------------------------------------------------------

def test_ibja_today_am():
    r = parse_ibja(html("ibja_weekday_am.html"), today=date(2026, 10, 19))
    assert r.source == "ibja" and r.session == "AM"
    assert r.rate_24k == pytest.approx(14640.6) and r.rate_22k == pytest.approx(13410.8)
    assert r.as_of == "2026-10-19T12:00:00+05:30"


def test_ibja_pm_beats_am():
    h = html("ibja_weekday_am.html").replace('<span id="lblGold999_PM"></span>', '<span id="lblGold999_PM">146900</span>')
    r = parse_ibja(h, today=date(2026, 10, 19))
    assert r.session == "PM" and r.rate_24k == pytest.approx(14690.0)
    assert r.as_of.startswith("2026-10-19T17:00")


def test_ibja_weekend_uses_newest_history_row_pm_first():
    r = parse_ibja(html("ibja_weekend.html"), today=date(2026, 10, 18))
    assert (r.as_of[:10], r.session, r.rate_24k) == ("2026-10-16", "PM", pytest.approx(14642.6))


def test_ibja_holiday_box_showing_old_rate_is_dated_from_history():
    # Today's box repeats Friday's AM value: date it 16 Oct, not "today"
    h = html("ibja_weekday_am.html").replace(">146406<", ">146514<")
    r = parse_ibja(h, today=date(2026, 10, 19))
    assert r.as_of[:10] == "2026-10-16"


def test_ibja_layout_change_raises():
    with pytest.raises(RateError):
        parse_ibja("<html>maintenance</html>", today=date(2026, 10, 19))


def test_tanishq_newest_row():
    r = parse_tanishq(html("tanishq.html"))
    assert (r.source, r.rate_24k, r.rate_22k) == ("tanishq", 14847, 13610)
    assert r.as_of.startswith("2026-10-19")


def test_tanishq_matches_wealthydimes_figures():
    # WealthyDimes showed 14,787 on 16 Oct and 14,809 on 18 Oct, "· Tanishq"
    h = html("tanishq.html")
    assert 'data-goldrate24kt="14787"' in h and 'data-goldrate24kt="14809"' in h
    assert parse_tanishq(h.split("<tr> <td>19-10-2026")[0] + h.split("</tr>", 2)[2]).rate_24k == 14809


def test_tanishq_layout_change_raises():
    with pytest.raises(RateError):
        parse_tanishq("<html></html>")


def test_absurd_values_rejected():
    with pytest.raises(RateError):
        parse_tanishq(html("tanishq.html").replace('data-goldrate24kt="14847"', 'data-goldrate24kt="14"'))


# --- refresh + storage -----------------------------------------------------------------------

def fake_get(pages: dict):
    def get(url: str) -> str:
        for key, body in pages.items():
            if key in url:
                if isinstance(body, Exception):
                    raise body
                return body
        raise AssertionError(url)
    return get


def mem():
    c = db.connect(":memory:")
    db.init_db(c)
    return c


def test_refresh_both_sources_and_dedupe():
    c = mem()
    s = Settings()
    get = fake_get({"ibjarates": html("ibja_weekday_am.html"), "tanishq": html("tanishq.html")})
    rep = refresh_rates(c, s, get=get, today=date(2026, 10, 19))
    assert rep["ibja"]["ok"] and rep["tanishq"]["ok"]
    refresh_rates(c, s, get=get, today=date(2026, 10, 19))  # same rates again: no new rows
    assert c.execute("SELECT COUNT(*) FROM gold_rates").fetchone()[0] == 2
    assert db.benchmark_rate(c, s.rate_sources)["source"] == "ibja"


def test_one_source_failing_keeps_the_other():
    c = mem()
    s = Settings()
    rep = refresh_rates(c, s, get=fake_get({"ibjarates": OSError("blocked"), "tanishq": html("tanishq.html")}),
                        today=date(2026, 10, 19))
    assert not rep["ibja"]["ok"] and "blocked" in rep["ibja"]["error"]
    assert db.benchmark_rate(c, s.rate_sources)["source"] == "tanishq"  # falls back to next source


def test_old_database_is_upgraded(tmp_path):
    p = tmp_path / "old.db"
    old = sqlite3.connect(p)
    old.execute("CREATE TABLE gold_rates (id INTEGER PRIMARY KEY, fetched_at TEXT NOT NULL, rate_24k REAL NOT NULL, "
                "rate_22k REAL NOT NULL, source TEXT NOT NULL)")
    old.execute("INSERT INTO gold_rates VALUES (1, '2026-10-16T05:00:00+00:00', 14787, 13545, 'manual (cli)')")
    old.commit()
    old.close()
    with db.open_db(p) as c:
        cols = {r["name"] for r in c.execute("PRAGMA table_info(gold_rates)")}
        assert {"as_of", "session"} <= cols
        assert db.latest_rate(c)["rate_24k"] == 14787  # old data kept


# --- staleness -------------------------------------------------------------------------------

@pytest.mark.parametrize("as_of,now,stale", [
    ("2026-10-16T17:00:00+05:30", datetime(2026, 10, 18, 20, 0, tzinfo=IST), False),  # Fri PM, seen Sunday
    ("2026-10-16T17:00:00+05:30", datetime(2026, 10, 19, 9, 0, tzinfo=IST), False),   # Fri PM, Monday morning
    ("2026-10-16T17:00:00+05:30", datetime(2026, 10, 20, 18, 0, tzinfo=IST), True),   # Fri PM, Tuesday evening
    (None, datetime(2026, 10, 19, 9, 0, tzinfo=IST), True),
])
def test_rate_staleness(as_of, now, stale):
    assert rate_is_stale(as_of, now) is stale


# --- GoodReturns and international spot (added 2026-10-23) -----------------------------------

def test_goodreturns_today():
    from goldtracker.rates import parse_goodreturns
    r = parse_goodreturns(html("goodreturns.html"), today=date(2026, 10, 23))
    assert (r.source, r.rate_24k, r.rate_22k) == ("goodreturns", 14248, 13060)
    assert r.as_of == "2026-10-23T10:00:00+05:30"


def test_goodreturns_layout_change_raises():
    from goldtracker.rates import parse_goodreturns
    with pytest.raises(RateError):
        parse_goodreturns("<html>new layout</html>", today=date(2026, 10, 23))


def test_xau_converts_troy_ounce_to_gram():
    from goldtracker.rates import parse_xau
    body = ('{"currency":"INR","currencySymbol":"\\u20b9","exchangeRate":94.8964,"name":"Gold",'
            '"price":379955.6866601528,"symbol":"XAU","updatedAt":"2026-10-23T15:53:44Z"}')
    r = parse_xau(body)
    assert r.source == "xau" and r.rate_24k == pytest.approx(12215.86, abs=0.01)
    assert r.as_of == "2026-10-23T21:23:44+05:30"


def test_xau_wrong_currency_raises():
    from goldtracker.rates import parse_xau
    with pytest.raises(RateError):
        parse_xau('{"currency":"USD","price":4003.9}')


def test_default_sources_include_new_ones(monkeypatch):
    monkeypatch.delenv("GOLD_RATE_SOURCES", raising=False)
    assert Settings().rate_sources == ["ibja", "tanishq", "goodreturns", "xau"]


def test_xau_is_left_out_of_row_premiums(tmp_path):
    from goldtracker.collectors import RawListing, save_listings
    from goldtracker.ranking import rank
    conn = db.connect(tmp_path / "g.db")
    db.init_db(conn)
    db.save_rate(conn, 14248, "ibja", as_of="2026-10-23T12:00:00+05:30")
    db.save_rate(conn, 12215.7, "xau", as_of="2026-10-23T21:23:44+05:30")
    save_listings(conn, [RawListing("flipkart", "A", "MMTC 24K 999 Gold Coin 1 g", 15000)])
    deals = rank(conn, [], rate_sources=["ibja", "tanishq", "goodreturns", "xau"])
    assert deals and deals[0].benchmark == "ibja" and set(deals[0].premiums) == {"ibja"}
