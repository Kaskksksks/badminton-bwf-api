from fastapi.testclient import TestClient

from app.main import app


def test_root_and_data_status_are_available() -> None:
    client = TestClient(app)
    root = client.get("/")
    assert root.status_code == 200
    assert root.json()["api_prefix"] == "/api/v1"

    status = client.get("/api/v1/data-status")
    assert status.status_code == 200
    assert status.json()["data"]["historical_seed"]["cutoff_date"] == "2026-08-22"
    assert status.json()["data"]["bwf_live"]["start_date"] == "2026-08-23"
