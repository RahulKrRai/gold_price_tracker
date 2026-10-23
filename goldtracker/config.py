"""Settings, read from environment variables (and a local .env file if present)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv is optional at runtime
    pass

ROOT = Path(__file__).resolve().parent.parent


def _float(name: str) -> float | None:
    raw = os.getenv(name, "").strip()
    return float(raw) if raw else None


def _list(name: str, default: str = "") -> list[str]:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


@dataclass
class Settings:
    db_path: Path = field(default_factory=lambda: ROOT / os.getenv("GOLD_DB_PATH", "data/gold.db"))
    offers_path: Path = field(default_factory=lambda: ROOT / os.getenv("GOLD_OFFERS_PATH", "data/offers.json"))
    manual_rate_24k: float | None = field(default_factory=lambda: _float("GOLD_RATE_24K"))
    rate_url: str = field(default_factory=lambda: os.getenv("GOLD_RATE_URL", "").strip())
    rate_json_key: str = field(default_factory=lambda: os.getenv("GOLD_RATE_JSON_KEY", "").strip())
    my_offers: list[str] = field(default_factory=lambda: _list("MY_OFFERS"))
    include_first_order: bool = field(
        default_factory=lambda: os.getenv("INCLUDE_FIRST_ORDER", "false").lower() in {"1", "true", "yes"}
    )
    refresh_minutes: int = field(default_factory=lambda: int(os.getenv("REFRESH_MINUTES", "45")))
    # First source is the benchmark for "vs market"; others are shown alongside
    rate_sources: list[str] = field(default_factory=lambda: _list("GOLD_RATE_SOURCES", "ibja,tanishq,goodreturns,xau"))
    # Twice a day on weekdays, after IBJA's AM and PM sessions (IST, "HH:MM")
    rate_times: list[str] = field(default_factory=lambda: _list("RATE_REFRESH_TIMES", "11:00,17:00"))
    publish_dir: Path = field(default_factory=lambda: ROOT / os.getenv("PUBLISH_DIR", "site"))
    publish_git_push: bool = field(
        default_factory=lambda: os.getenv("PUBLISH_GIT_PUSH", "false").lower() in {"1", "true", "yes"})
    # Amazon Creators API (replaced PA-API 5 on 2026-04-30)
    amazon_client_id: str = field(default_factory=lambda: os.getenv("AMAZON_CLIENT_ID", "").strip())
    amazon_client_secret: str = field(default_factory=lambda: os.getenv("AMAZON_CLIENT_SECRET", "").strip())
    amazon_partner_tag: str = field(default_factory=lambda: os.getenv("AMAZON_PARTNER_TAG", "").strip())
    amazon_credential_version: str = field(
        default_factory=lambda: os.getenv("AMAZON_CREDENTIAL_VERSION", "").strip())
    amazon_token_url: str = field(default_factory=lambda: os.getenv("AMAZON_TOKEN_URL", "").strip())
    amazon_api_base: str = field(
        default_factory=lambda: os.getenv("AMAZON_API_BASE", "https://creatorsapi.amazon/catalog/v1/").strip())
    amazon_marketplace: str = field(default_factory=lambda: os.getenv("AMAZON_MARKETPLACE", "www.amazon.in").strip())
    # Which retailers to collect; Amazon uses the Creators API when keys are set, otherwise the browser
    retailers: list[str] = field(default_factory=lambda: _list("RETAILERS", "myntra,ajio,flipkart,amazon,tatacliq,coinbazaar,zepto"))
    amazon_source: str = field(default_factory=lambda: os.getenv("AMAZON_SOURCE", "auto").strip().lower())
    amazon_keywords: list[str] = field(
        default_factory=lambda: _list("AMAZON_KEYWORDS", "24k gold coin,gold bar 999,22k gold coin"))

    telegram_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", "").strip())
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", "").strip())
    alert_below: float | None = field(default_factory=lambda: _float("ALERT_BELOW_PER_FINE_G"))

    @property
    def amazon_api_ready(self) -> bool:
        return bool(self.amazon_client_id and self.amazon_client_secret and self.amazon_partner_tag)

    def refresh_minutes_for(self, retailer: str) -> int:
        """Per-retailer interval, e.g. REFRESH_MINUTES_MYNTRA=15; falls back to REFRESH_MINUTES."""
        raw = os.getenv(f"REFRESH_MINUTES_{retailer.upper()}", "").strip()
        return int(raw) if raw else self.refresh_minutes


def get_settings() -> Settings:
    return Settings()
