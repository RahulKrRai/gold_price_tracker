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
    telegram_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", "").strip())
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", "").strip())
    alert_below: float | None = field(default_factory=lambda: _float("ALERT_BELOW_PER_FINE_G"))


def get_settings() -> Settings:
    return Settings()
