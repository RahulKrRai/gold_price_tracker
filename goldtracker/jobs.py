"""One refresh cycle, and the scheduler that repeats it."""

from __future__ import annotations

import logging

from . import db
from .alerts import check_and_alert
from .collectors import save_listings
from .config import Settings, get_settings
from .offers import load_offers
from .ranking import rank
from .rates import refresh_rate

log = logging.getLogger("goldtracker")

COLLECTORS = {
    "myntra": "goldtracker.collectors.myntra",
}


def run_collector(name: str) -> list:
    import importlib

    return importlib.import_module(COLLECTORS[name]).collect()


def refresh_once(settings: Settings | None = None, retailers: list[str] | None = None) -> dict:
    settings = settings or get_settings()
    report: dict = {}
    with db.open_db(settings.db_path) as conn:
        try:
            report["rate_24k"] = refresh_rate(conn, settings)
        except Exception as e:  # keep going with the last stored rate
            log.warning("rate refresh failed: %s", e)
            report["rate_error"] = str(e)
        for name in retailers or list(COLLECTORS):
            try:
                report[name] = save_listings(conn, run_collector(name))
            except Exception as e:
                log.warning("%s collector failed: %s", name, e)
                report[name] = {"error": str(e)}
        offers = load_offers(settings.offers_path)
        deals = rank(conn, offers, held=set(settings.my_offers) or None,
                     include_first_order=settings.include_first_order)
        try:
            report["alerts_sent"] = check_and_alert(conn, deals, settings)
        except Exception as e:
            log.warning("alert failed: %s", e)
    log.info("refresh: %s", report)
    return report


def run_scheduler(settings: Settings | None = None) -> None:
    from apscheduler.schedulers.blocking import BlockingScheduler

    settings = settings or get_settings()
    minutes = max(30, min(settings.refresh_minutes, 60))
    sched = BlockingScheduler(timezone="Asia/Kolkata")
    sched.add_job(refresh_once, "interval", minutes=minutes, kwargs={"settings": settings},
                  max_instances=1, coalesce=True, jitter=120)
    log.info("refreshing every %s minutes; Ctrl+C to stop", minutes)
    refresh_once(settings)
    sched.start()
