from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed configuration; no production secrets live in source."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Badminton Data Platform"
    environment: Literal["development", "test", "production"] = "development"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    database_url: str = "sqlite+pysqlite:///./badminton.db"

    bwf_live_base_url: str = "https://extranet-lv.bwfbadminton.com"
    bwf_request_timeout_seconds: int = Field(default=20, ge=1, le=120)
    bwf_user_agent: str = "BadmintonDataPlatform/0.1 (permitted collection)"
    historical_seed_cutoff_date: date = date(2026, 8, 22)
    bwf_ingestion_start_date: date = date(2026, 8, 23)

    # A six-hour discovery interval limits idle scraping. Once a successful
    # discovery response contains a live match, the worker switches itself to
    # the live interval; it returns to idle after a successful response has no
    # confirmed live matches.
    poll_idle_minutes: int = Field(default=360, ge=1, le=1440)
    poll_tournament_minutes: int = Field(default=30, ge=1, le=240)
    poll_live_match_seconds: int = Field(default=60, ge=15, le=3600)
    poll_error_backoff_max_seconds: int = Field(default=900, ge=30, le=86400)

    # Retain enough recent live evidence for audit and diagnosis without allowing
    # continuously polled JSON payloads to consume the database indefinitely.
    raw_retention_days: int = Field(default=7, ge=1, le=3650)
    raw_payload_retention_hours: int = Field(default=24, ge=1, le=8760)
    raw_deduplicate_unchanged: bool = True
    seed_dataset_root: Path = Path("/data/historical_dataset/bwf_match_data_2010_2026_08_22")

    api_rate_limit_per_minute: int = Field(default=120, ge=1, le=100000)
    admin_api_key: str = "replace-before-deployment"
    scheduler_enabled: bool = False

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("bwf_ingestion_start_date")
    @classmethod
    def validate_cutover(cls, value: date, info: object) -> date:
        data = getattr(info, "data", {})
        cutoff = data.get("historical_seed_cutoff_date")
        if cutoff and value <= cutoff:
            raise ValueError("BWF ingestion start date must follow the historical seed cutoff date")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
