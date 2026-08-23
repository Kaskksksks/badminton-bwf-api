from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import get_settings
from app.db.base import SessionLocal
from app.ingestion.adapters.bwf.service import synchronize_current_bwf

logger = logging.getLogger(__name__)


def run_bwf_sync_job() -> None:
    """Database transaction boundary for a scheduled BWF synchronization run."""
    try:
        with SessionLocal.begin() as session:
            result = synchronize_current_bwf(session)
            logger.info("bwf_sync_complete", extra={"result": result})
    except Exception:
        logger.exception("bwf_sync_failed")


def build_scheduler() -> BackgroundScheduler:
    settings = get_settings()
    scheduler = BackgroundScheduler(timezone="UTC")
    # The worker chooses live/tournament/idle behavior from current source state.
    # A 60-second scheduler tick is an orchestration heartbeat, not a claim that
    # every scope will be polled every minute.
    scheduler.add_job(
        run_bwf_sync_job,
        trigger="interval",
        seconds=min(settings.poll_live_match_seconds, 60),
        id="bwf-sync",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    return scheduler
