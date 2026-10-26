"""Environment-based settings."""

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    refresh_token: str
    country: str
    language: str
    app_version: str
    db_path: Path
    timezone: str
    sync_interval_hours: float
    app_token: str
    host: str
    port: int


@lru_cache
def get_settings() -> Settings:
    return Settings(
        refresh_token=os.environ.get("LIDL_REFRESH_TOKEN", "").strip(),
        country=os.environ.get("LIDL_COUNTRY", "HU").upper(),
        language=os.environ.get("LIDL_LANGUAGE", "hu").lower(),
        # The API rejects unrealistic app versions; bump this if requests start failing.
        app_version=os.environ.get("LIDL_APP_VERSION", "16.45.5"),
        db_path=Path(os.environ.get("DB_PATH", "data/lidl.sqlite3")),
        timezone=os.environ.get("TIMEZONE", "Europe/Budapest"),
        sync_interval_hours=float(os.environ.get("SYNC_INTERVAL_HOURS", "6")),
        # Optional shared secret; when set, every /api request needs it.
        app_token=os.environ.get("APP_TOKEN", ""),
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
    )
