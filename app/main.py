from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.base import get_db
from app.health.service import build_data_status_payload, build_health_payload
from app.polling.scheduler import build_scheduler
from app.api.v1.routes import router as v1_router

settings = get_settings()
configure_logging(settings.log_level)


@asynccontextmanager
async def lifespan(_: FastAPI):
    scheduler = build_scheduler() if settings.scheduler_enabled else None
    if scheduler:
        scheduler.start()
    try:
        yield
    finally:
        if scheduler:
            scheduler.shutdown(wait=False)


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Provenance-aware historical badminton data and BWF live-ingestion API.",
    lifespan=lifespan,
)
app.include_router(v1_router, prefix=settings.api_prefix)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)


@app.get("/", tags=["service"])
def root() -> dict[str, str]:
    return {"service": settings.app_name, "api_prefix": settings.api_prefix, "docs": "/docs"}


@app.get(f"{settings.api_prefix}/health", tags=["service"])
def health(session: Session = Depends(get_db)) -> dict[str, object]:
    return {"data": build_health_payload(session), "meta": {"api_version": "v1"}}


@app.get(f"{settings.api_prefix}/data-status", tags=["service"])
def data_status(session: Session = Depends(get_db)) -> dict[str, object]:
    return {
        "data": build_data_status_payload(
            session,
            settings.historical_seed_cutoff_date.isoformat(),
            settings.bwf_ingestion_start_date.isoformat(),
        ),
        "meta": {"api_version": "v1"},
    }
