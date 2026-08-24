from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.v1.routes import router as v1_router
from app.api.v1.website_routes import router as website_router
from app.core.config import get_settings
from app.core.rate_limit import SlidingWindowRateLimiter, client_key_from_headers
from app.core.logging import configure_logging
from app.db.base import get_db
from app.health.service import build_data_status_payload, build_health_payload
from app.polling.scheduler import build_scheduler

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
app.include_router(website_router, prefix=settings.api_prefix)
rate_limiter = SlidingWindowRateLimiter(limit=settings.api_rate_limit_per_minute)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)


@app.middleware("http")
async def enforce_rate_limit(request: Request, call_next: ASGIApp):
    """Apply the documented read API limit before database work begins."""
    if request.url.path.startswith(settings.api_prefix):
        client_key = client_key_from_headers(
            request.headers.get("x-forwarded-for"),
            request.client.host if request.client else None,
        )
        allowed, retry_after = rate_limiter.check(client_key)
        if not allowed:
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(retry_after)},
                content={
                    "detail": {"code": "rate_limit_exceeded", "limit_per_minute": settings.api_rate_limit_per_minute},
                    "meta": {"api_version": "v1"},
                },
            )
    return await call_next(request)


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(_: Request, exc: SQLAlchemyError) -> JSONResponse:
    """Avoid opaque 500 responses when the database is unavailable or unmigrated."""
    return JSONResponse(
        status_code=503,
        headers={"Retry-After": "30"},
        content={
            "detail": {
                "code": "database_schema_or_connection_error",
                "error": type(exc).__name__,
            },
            "meta": {"api_version": "v1"},
        },
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
