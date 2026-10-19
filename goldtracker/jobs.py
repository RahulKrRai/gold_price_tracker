"""Refresh jobs and the scheduler.

  * rates:   every weekday at RATE_REFRESH_TIMES (default 11:00 and 17:00 IST), plus once at start
  * prices:  one job per retailer every REFRESH_MINUTES_<RETAILER> minutes (default REFRESH_MINUTES)
  * publish: after each price refresh, if a site folder exists (see publish.py)

Every run is logged in the `runs` table so the dashboard can warn when something stops working.
"""

from __future__ import annotations

import importlib
import logging

from . import db
from .alerts import check_and_alert
from .collectors import save_listings
from .config import Settings, get_settings
from .offers import load_offers
from .ranking import rank
from .rates import refresh_rates

log = logging.getLogger("goldtracker")

COLLECTORS = {
    "myntra": "goldtracker.collectors.myntra",
    "amazon": "goldtracker.collectors.amazon",
}


def enabled_retailers(settings: Settings) -> list[str]:
    """Myntra always; Amazon only once Creators API keys are configured."""
    out = ["myntra"]
    if settings.amazon_client_id and settings.amazon_client_secret and settings.amazon_partner_tag:
        out.append("amazon")
    return out


def run_collector(name: str, settings: Settings | None = None) -> list:
    mod = importlib.import_module(COLLECTORS[name])
    return mod.collect(settings) if name == "amazon" else mod.collect()


def refresh_rates_job(settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    with db.open_db(settings.db_path) as conn:
        run = db.start_run(conn, "rates")
        report = refresh_rates(conn, settings)
        ok = [s for s, r in report.items() if r["ok"]]
        errors = "; ".join(f"{s}: {r['error']}" for s, r in report.items() if not r["ok"])
        db.finish_run(conn, run, ok=bool(ok), count=len(ok), error=errors or None)
    log.info("rates: %s", report)
    return report


def refresh_retailer(name: str, settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    with db.open_db(settings.db_path) as conn:
        run = db.start_run(conn, name)
        try:
            result = save_listings(conn, run_collector(name, settings))
            db.finish_run(conn, run, ok=result["saved"] > 0, count=result["saved"],
                          error=None if result["saved"] else "collector returned no listings")
        except Exception as e:
            log.warning("%s collector failed: %s", name, e)
            db.finish_run(conn, run, ok=False, error=f"{type(e).__name__}: {e}")
            return {"error": str(e)}
        deals = rank(conn, load_offers(settings.offers_path), held=set(settings.my_offers) or None,
                     include_first_order=settings.include_first_order, rate_sources=settings.rate_sources)
        try:
            result["alerts_sent"] = check_and_alert(conn, deals, settings)
        except Exception as e:
            log.warning("alert failed: %s", e)
    _maybe_publish(settings)
    log.info("%s: %s", name, result)
    return result


def _maybe_publish(settings: Settings) -> None:
    if not settings.publish_dir.exists():
        return
    try:
        from .publish import publish
        publish(settings)
    except Exception as e:
        log.warning("publish failed: %s", e)


def refresh_once(settings: Settings | None = None, retailers: list[str] | None = None) -> dict:
    """Rates, then every enabled retailer. Used by the dashboard's Refresh button."""
    settings = settings or get_settings()
    report: dict = {"rates": refresh_rates_job(settings)}
    for name in retailers or enabled_retailers(settings):
        report[name] = refresh_retailer(name, settings)
    return report


def build_scheduler(settings: Settings, scheduler_cls=None):
    """Create (but don't start) the scheduler; split out so tests can inspect the jobs."""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    sched = (scheduler_cls or BlockingScheduler)(timezone="Asia/Kolkata")
    for hhmm in settings.rate_times:
        h, m = (int(x) for x in hhmm.split(":"))
        sched.add_job(refresh_rates_job, CronTrigger(day_of_week="mon-fri", hour=h, minute=m,
                                                     timezone="Asia/Kolkata"),
                      kwargs={"settings": settings}, id=f"rates-{hhmm}", max_instances=1, coalesce=True)
    for name in enabled_retailers(settings):
        minutes = max(10, min(settings.refresh_minutes_for(name), 180))
        sched.add_job(refresh_retailer, "interval", minutes=minutes, args=[name], kwargs={"settings": settings},
                      id=f"prices-{name}", max_instances=1, coalesce=True, jitter=60)
    return sched


def run_scheduler(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    sched = build_scheduler(settings)
    for job in sched.get_jobs():
        log.info("scheduled %s: %s", job.id, job.trigger)
    refresh_once(settings)
    sched.start()
