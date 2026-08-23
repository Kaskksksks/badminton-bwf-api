from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import desc, func, select, text
from sqlalchemy.orm import Session

from app.db.models import DataSource, ImportBatch, Match


def build_health_payload(session: Session) -> dict[str, object]:
    database_status = "ok"
    database_error: str | None = None
    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:  # health reporting must not mask a dependency failure
        database_status = "error"
        database_error = type(exc).__name__

    if database_status != "ok":
        return {
            "api_status": "degraded",
            "database_status": database_status,
            "database_error": database_error,
            "collector_status": "unknown",
            "bwf_source_status": "unknown",
            "last_successful_collection": None,
            "current_polling_mode": "unknown",
            "live_match_count": 0,
            "latest_data_timestamp": None,
            "errors_last_24_hours": None,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    latest_batch = session.scalar(select(ImportBatch).order_by(desc(ImportBatch.completed_at)))
    latest_match = session.scalar(select(Match).order_by(desc(Match.updated_at)))
    live_count = session.scalar(select(func.count()).select_from(Match).where(Match.status == "LIVE")) or 0
    bwf_source = session.scalar(select(DataSource).where(DataSource.code == "BWF_LIVE"))
    return {
        "api_status": "ok",
        "database_status": database_status,
        "database_error": None,
        "collector_status": "configured" if bwf_source else "not_started",
        "bwf_source_status": "configured" if bwf_source else "not_started",
        "last_successful_collection": latest_batch.completed_at.isoformat() if latest_batch and latest_batch.completed_at else None,
        "current_polling_mode": "database-backed worker configuration",
        "live_match_count": int(live_count),
        "latest_data_timestamp": latest_match.updated_at.isoformat() if latest_match else None,
        "errors_last_24_hours": 0,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def build_data_status_payload(session: Session, historical_cutoff: str, live_start: str) -> dict[str, object]:
    try:
        latest_batch = session.scalar(select(ImportBatch).order_by(desc(ImportBatch.completed_at)))
        source_codes = set(session.scalars(select(DataSource.code)).all())
    except Exception:
        latest_batch = None
        source_codes = set()
    historical_status = "imported" if "HISTORICAL_SEED" in source_codes and latest_batch else "not_imported"
    return {
        "historical_seed": {
            "status": historical_status,
            "cutoff_date": historical_cutoff,
            "latest_import_batch_id": latest_batch.id if latest_batch else None,
            "last_verified": latest_batch.completed_at.isoformat() if latest_batch and latest_batch.completed_at else None,
        },
        "bwf_live": {
            "status": "configured" if "BWF_LIVE" in source_codes else "not_started",
            "start_date": live_start,
        },
        "live_game_state": {
            "status": "available" if "BWF_LIVE" in source_codes else "not_started",
            "precision_rule": "collection timestamps are not source rally timestamps",
        },
    }
