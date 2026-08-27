from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Mapping

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import Settings, get_settings
from app.core.worker_safety import collection_slot, release_process_memory
from app.db.base import SessionLocal
from app.ingestion.adapters.bwf.service import synchronize_current_bwf
from app.ingestion.calendar_draws.service import synchronize_corporate_calendar
from app.ingestion.rankings.service import run_rankings_job
from app.ingestion.player_profiles.service import run_full_queue
from app.modeling.service import run_model_pipeline

logger = logging.getLogger(__name__)
JOB_ID = "bwf-sync"
RANKINGS_JOB_ID = "bwf-rankings-weekly"
PLAYER_PROFILES_JOB_ID = "bwf-player-profiles-daily"
MODEL_JOB_ID = "bwf-model-publication-daily"
CALENDAR_JOB_ID = "bwf-corporate-calendar"
CALENDAR_DEFERRED_RETRY_JOB_ID = "bwf-corporate-calendar-deferred-retry"
CALENDAR_DEFERRED_RETRY_SECONDS = 90


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
    """Synchronize once without overlapping a manual identity collection unit."""
    settings = get_settings()
    with collection_slot("live_sync") as acquired:
        if not acquired:
            retry_seconds = min(settings.poll_live_match_seconds, settings.poll_error_backoff_max_seconds)
            if scheduler:
                scheduler.reschedule_job(JOB_ID, trigger="interval", seconds=retry_seconds)
            logger.info(
                "bwf_sync_deferred",
                extra={"reason": "identity_batch_in_progress", "next_interval_seconds": retry_seconds},
            )
            return
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
        finally:
            release_process_memory(reason="live_sync_complete")


def run_bwf_corporate_calendar_job(
    scheduler: BackgroundScheduler | None = None,
    deferred_retry: bool = False,
) -> None:
    """Collect one bounded authorised calendar/draw unit without live-worker overlap.

    An initial startup collision with the immediate senior live-sync job is retried once
    after a short delay. The retry never schedules another retry, preserving the normal
    12-hour cadence and the existing global collection-slot boundary.
    """
    settings = get_settings()
    with collection_slot("corporate_calendar") as acquired:
        if not acquired:
            if scheduler is not None and not deferred_retry:
                retry_at = datetime.now(timezone.utc) + timedelta(seconds=CALENDAR_DEFERRED_RETRY_SECONDS)
                scheduler.add_job(
                    run_bwf_corporate_calendar_job,
                    trigger="date",
                    run_date=retry_at,
                    id=CALENDAR_DEFERRED_RETRY_JOB_ID,
                    kwargs={"scheduler": scheduler, "deferred_retry": True},
                    replace_existing=True,
                    max_instances=1,
                    coalesce=True,
                )
                logger.info(
                    "bwf_corporate_calendar_deferred_retry_scheduled",
                    extra={
                        "reason": "collection_slot_unavailable",
                        "retry_delay_seconds": CALENDAR_DEFERRED_RETRY_SECONDS,
                    },
                )
            else:
                logger.info(
                    "bwf_corporate_calendar_deferred",
                    extra={
                        "reason": "collection_slot_unavailable",
                        "deferred_retry": deferred_retry,
                    },
                )
            return
        try:
            with SessionLocal.begin() as session:
                result = synchronize_corporate_calendar(session, settings=settings)
            logger.info("bwf_corporate_calendar_complete", extra=result)
        except Exception:
            logger.exception("bwf_corporate_calendar_failed")
        finally:
            release_process_memory(reason="bwf_corporate_calendar_complete")


def run_player_profiles_job() -> None:
    """Run one bounded authorised identity batch without overlapping live collection."""
    settings = get_settings()
    if not settings.bwf_player_profiles_scheduler_enabled:
        logger.info("bwf_player_profiles_job_skipped", extra={"reason": "scheduler_disabled"})
        return
    with collection_slot("player_profiles") as acquired:
        if not acquired:
            logger.info("bwf_player_profiles_job_deferred", extra={"reason": "collection_slot_unavailable"})
            return
        try:
            with SessionLocal.begin() as session:
                result = run_full_queue(session, settings=settings)
            logger.info("bwf_player_profiles_job_complete", extra=result)
        except Exception:
            logger.exception("bwf_player_profiles_job_failed")
            raise
        finally:
            release_process_memory(reason="player_profiles_complete")


def run_model_publication_job() -> None:
    """Publish model outputs only after the modeling service validates its prerequisites."""
    settings = get_settings()
    if not settings.modeling_scheduler_enabled:
        logger.info("bwf_model_publication_job_skipped", extra={"reason": "scheduler_disabled"})
        return
    with collection_slot("model_publication") as acquired:
        if not acquired:
            logger.info("bwf_model_publication_job_deferred", extra={"reason": "collection_slot_unavailable"})
            return
        try:
            with SessionLocal.begin() as session:
                result = run_model_pipeline(session, settings=settings)
            logger.info("bwf_model_publication_job_complete", extra=result)
        except Exception:
            logger.exception("bwf_model_publication_job_failed")
            raise
        finally:
            release_process_memory(reason="model_publication_complete")


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
    if settings.bwf_player_profiles_enabled and settings.bwf_player_profiles_scheduler_enabled:
        scheduler.add_job(
            run_player_profiles_job,
            trigger="interval",
            hours=settings.bwf_player_profiles_refresh_hours,
            id=PLAYER_PROFILES_JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            next_run_time=datetime.now(timezone.utc),
        )
    if settings.modeling_scheduler_enabled:
        scheduler.add_job(
            run_model_publication_job,
            trigger="interval",
            hours=settings.modeling_refresh_hours,
            id=MODEL_JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            next_run_time=datetime.now(timezone.utc),
        )
    # Calendar/draw discovery is separately opt-in and deliberately low frequency.
    # It does not reschedule or otherwise alter adaptive senior live polling.
    if settings.bwf_calendar_enabled and settings.bwf_calendar_scheduler_enabled:
        scheduler.add_job(
            run_bwf_corporate_calendar_job,
            trigger="interval",
            hours=settings.bwf_calendar_refresh_hours,
            id=CALENDAR_JOB_ID,
            kwargs={"scheduler": scheduler},
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            next_run_time=datetime.now(timezone.utc),
        )
    # Rankings are a distinct source and cadence. This fixed weekly job never
    # reschedules, delays, or otherwise alters the adaptive live polling job.
    if settings.bwf_rankings_enabled and settings.bwf_rankings_scheduler_enabled:
        scheduler.add_job(
            run_rankings_job,
            trigger=CronTrigger(
                day_of_week=settings.bwf_rankings_run_day_of_week,
                hour=settings.bwf_rankings_run_hour_utc,
                minute=settings.bwf_rankings_run_minute_utc,
                timezone="UTC",
            ),
            id=RANKINGS_JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=6 * 60 * 60,
        )
    return scheduler
