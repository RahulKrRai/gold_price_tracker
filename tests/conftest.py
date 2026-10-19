from datetime import datetime

import pytest

from goldtracker import offers

# The sample data and offers are from 16 Oct 2026; pin "now" so time-limited offers stay valid in tests.
FIXED_NOW = datetime(2026, 10, 16, 12, 0, tzinfo=offers.IST)


@pytest.fixture(autouse=True)
def _pin_offer_clock(monkeypatch):
    monkeypatch.setattr(offers, "_now", lambda: FIXED_NOW)
    yield


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    # A developer's own .env must not leak into tests
    for k in ["GOLD_RATE_SOURCES", "REFRESH_MINUTES", "REFRESH_MINUTES_MYNTRA", "PUBLISH_DIR", "PUBLISH_GIT_PUSH",
              "AMAZON_CLIENT_ID", "AMAZON_CLIENT_SECRET", "AMAZON_PARTNER_TAG", "GOLD_RATE_24K",
              "TELEGRAM_BOT_TOKEN", "ALERT_BELOW_PER_FINE_G"]:
        monkeypatch.delenv(k, raising=False)
    yield
