from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import require_admin
from app.db.base import Base, get_db
from app.db.models import ImportBatch, Match
from app.main import app


def test_match_route_and_admin_protection() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        match = Match(
            source_match_key="test-source-match",
            status="COMPLETED",
            completion_basis="HISTORICAL_SEED_ROW",
            source_completeness="COMPLETE",
            historical_seed_flag=True,
        )
        session.add(match)
        session.flush()
        match_id = match.id

    def override_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        response = client.get(f"/api/v1/matches/{match_id}")
        assert response.status_code == 200
        assert response.json()["data"]["historical_seed"] is True
        admin = client.get("/api/v1/admin/import-batches")
        assert admin.status_code in {401, 503}
    finally:
        app.dependency_overrides.clear()


def test_authorized_import_batch_audit_is_bounded_and_includes_diagnostic_metadata() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(
            ImportBatch(
                batch_type="rankings",
                status="FAILED",
                importer_version="test",
                input_row_count=100,
                accepted_count=90,
                rejected_count=10,
                duplicate_count=0,
                error_summary="display name required",
            )
        )

    def override_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin] = lambda: None
    try:
        response = TestClient(app).get("/api/v1/admin/import-batches?limit=1")
        assert response.status_code == 200
        batch = response.json()["data"][0]
        assert batch["batch_type"] == "rankings"
        assert batch["error_summary"] == "display name required"
        assert batch["input_row_count"] == 100
    finally:
        app.dependency_overrides.clear()
