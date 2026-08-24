from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Mapping

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import Settings, get_settings
from app.db.base import SessionLocal
from app.ingestion.adapters.bwf.service import synchronize_current_bwf

logger = logging.getLogger(__name__)
JOB_ID = "bwf-sync"


def interval_for_sync_result(settings: Settings, result: Mapping[str, int | str]) -> tuple[int, str]:
    """Choose the next poll only from successfully observed BWF activity."""
    if str(result.get("status")) != "ok":
        return settings.poll_error_backoff_max_seconds, "BACKOFF"
    if int(result.get("live_matches", 0)) > 0:
        return settings.poll_live_match_seconds, "LIVE"
    if int(result.get("tournaments", 0)) > 0:
        return settings.poll_tournament_minutes * 60, "TOURNAMENT"
    return settings.poll_idle_minutes * 60, "IDLE"


def run_bwf_sync_job(scheduler: BackgroundScheduler | None = None) -> None:
    """Synchronize once, then schedule the next run from the observed source state."""
    settings = get_settings()
    try:
        with SessionLocal.begin() as session:
            result = synchronize_current_bwf(session, settings=settings)
        interval_seconds, mode = interval_for_sync_result(settings, result)
        if scheduler:
            scheduler.reschedule_job(JOB_ID, trigger="interval", seconds=interval_seconds)
        logger.info(
            "bwf_sync_complete",
            extra={**result, "polling_mode": mode, "next_interval_seconds": interval_seconds},
        )
    except Exception:
        if scheduler:
            scheduler.reschedule_job(
                JOB_ID,
                trigger="interval",
                seconds=settings.poll_error_backoff_max_seconds,
            )
        logger.exception("bwf_sync_failed")


def build_scheduler() -> BackgroundScheduler:
    settings = get_settings()
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        run_bwf_sync_job,
        trigger="interval",
        seconds=settings.poll_idle_minutes * 60,
        id=JOB_ID,
        kwargs={"scheduler": scheduler},
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        # Run one discovery fetch immediately after the worker starts; later
        # intervals are set from confirmed live/current/idle source state.
        next_run_time=datetime.now(timezone.utc),
    )
    return scheduler
