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

    # Ranking collection is intentionally opt-in. It must remain disabled until
    # the deployment has the required BWF permission or data licence in place.
    bwf_rankings_enabled: bool = False
    bwf_rankings_base_url: str = "https://extranet-lv.bwfbadminton.com"
    bwf_rankings_request_timeout_seconds: int = Field(default=30, ge=1, le=120)
    bwf_rankings_user_agent: str = "BadmintonDataPlatform/0.1 (authorised rankings collection; contact required)"
    bwf_rankings_page_size: int = Field(default=100, ge=10, le=100)
    bwf_rankings_max_pages_per_scope: int = Field(default=100, ge=1, le=500)
    bwf_rankings_scheduler_enabled: bool = False
    bwf_rankings_allow_live_source: bool = False
    bwf_rankings_permission_required: bool = True
    bwf_rankings_permission_reference: str | None = None
    bwf_rankings_run_day_of_week: str = "tue"
    bwf_rankings_run_hour_utc: int = Field(default=12, ge=0, le=23)
    bwf_rankings_run_minute_utc: int = Field(default=0, ge=0, le=59)
    bwf_rankings_max_entries_per_scope: int = Field(default=5000, ge=1, le=20000)
    bwf_rankings_source_revision: str = "bwf-public-ranking-interface-v1"

    # Player-profile collection is separate from rankings and remains disabled
    # until an authorised source reference and controlled dry run are configured.
    bwf_player_profiles_enabled: bool = False
    bwf_player_profiles_allow_live_source: bool = False
    bwf_player_profiles_permission_required: bool = True
    bwf_player_profiles_permission_reference: str | None = None
    bwf_player_profiles_base_url: str = "https://extranet-lv.bwfbadminton.com"
    bwf_player_profiles_request_timeout_seconds: int = Field(default=30, ge=1, le=120)
    bwf_player_profiles_user_agent: str = "BadmintonDataPlatform/0.1 (authorised player-profile collection)"
    bwf_player_profiles_min_request_interval_seconds: int = Field(default=2, ge=1, le=60)
    bwf_player_profiles_batch_size: int = Field(default=100, ge=1, le=500)
    # Commit and expire ORM state in small units so an authorised batch cannot
    # retain an entire large queue in one request transaction on low-memory hosts.
    bwf_player_profiles_transaction_chunk_size: int = Field(default=10, ge=1, le=100)
    bwf_player_profiles_source_revision: str = "bwf-public-player-profile-v1"
    bwf_player_profiles_auto_confirm: bool = False
    bwf_player_profiles_dry_run: bool = True
    bwf_player_profiles_scheduler_enabled: bool = False
    bwf_player_profiles_refresh_hours: int = Field(default=24, ge=6, le=168)

    # Model publication is deterministic and evidence-gated. It never creates a
    # model output unless the required confirmed identities and validated match
    # history are present.
    modeling_scheduler_enabled: bool = False
    # A separately reviewed real-data validation report must explicitly approve
    # publication. The safe default prevents a development baseline from becoming
    # a public sporting forecast merely because a scheduler is enabled.
    modeling_publication_approved: bool = False
    modeling_refresh_hours: int = Field(default=24, ge=6, le=168)
    modeling_max_forecasts_per_run: int = Field(default=5000, ge=1, le=20000)
    modeling_simulation_count: int = Field(default=1000, ge=100, le=100000)

    # Corporate calendar and direct draw PDFs are a separate authorised source.
    # They remain disabled until a deployment has an explicit permission reference
    # and a separately approved controlled dry run.
    bwf_calendar_enabled: bool = False
    bwf_calendar_scheduler_enabled: bool = False
    bwf_calendar_permission_required: bool = True
    bwf_calendar_permission_reference: str | None = None
    bwf_calendar_request_timeout_seconds: int = Field(default=30, ge=1, le=120)
    bwf_calendar_user_agent: str = "BadmintonDataPlatform/0.1 (authorised BWF Corporate calendar collection)"
    bwf_calendar_refresh_hours: int = Field(default=12, ge=6, le=24)
    bwf_calendar_max_bytes: int = Field(default=4_000_000, ge=100_000, le=10_000_000)
    bwf_draw_document_max_bytes: int = Field(default=10_000_000, ge=100_000, le=25_000_000)
    bwf_draw_document_horizon_days: int = Field(default=14, ge=0, le=60)
    bwf_draw_document_max_per_run: int = Field(default=4, ge=0, le=20)
    bwf_draw_parser_enabled: bool = False
    bwf_calendar_source_revision: str = "bwf-corporate-calendar-v1"

    @field_validator("bwf_calendar_permission_reference")
    @classmethod
    def require_calendar_permission_reference(cls, value: str | None, info: object) -> str | None:
        data = getattr(info, "data", {})
        if data.get("bwf_calendar_enabled") and data.get("bwf_calendar_permission_required") and not value:
            raise ValueError("BWF_CALENDAR_PERMISSION_REFERENCE is required when BWF_CALENDAR_ENABLED=true")
        return value

    @field_validator("bwf_player_profiles_permission_reference")
    @classmethod
    def require_player_profile_permission_reference(cls, value: str | None, info: object) -> str | None:
        data = getattr(info, "data", {})
        if data.get("bwf_player_profiles_enabled") and data.get("bwf_player_profiles_permission_required") and not value:
            raise ValueError("BWF_PLAYER_PROFILES_PERMISSION_REFERENCE is required when BWF_PLAYER_PROFILES_ENABLED=true")
        return value

    @field_validator("bwf_rankings_permission_reference")
    @classmethod
    def require_ranking_permission_reference(cls, value: str | None, info: object) -> str | None:
        data = getattr(info, "data", {})
        if data.get("bwf_rankings_enabled") and data.get("bwf_rankings_permission_required") and not value:
            raise ValueError("BWF_RANKINGS_PERMISSION_REFERENCE is required when BWF_RANKINGS_ENABLED=true")
        return value

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
