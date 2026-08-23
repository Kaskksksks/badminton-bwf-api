from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base, get_db
from app.db.models import Match
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
