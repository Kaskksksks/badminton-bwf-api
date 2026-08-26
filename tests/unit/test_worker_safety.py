from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1 import routes
from app.core import worker_safety
from app.ingestion.player_profiles import service as identity_service
from app.polling import scheduler as polling_scheduler


def test_collection_slot_excludes_overlapping_collection_units() -> None:
    with worker_safety.collection_slot("identity_batch") as identity_acquired:
        assert identity_acquired is True
        with worker_safety.collection_slot("live_sync") as live_acquired:
            assert live_acquired is False
    with worker_safety.collection_slot("live_sync") as live_after_release:
        assert live_after_release is True


def test_release_process_memory_collects_and_trims_when_glibc_is_available(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    class Trim:
        argtypes: object | None = None
        restype: object | None = None

        def __call__(self, amount: int) -> int:
            calls.append(amount)
            return 1

    trim = Trim()
    monkeypatch.setattr(worker_safety.ctypes, "CDLL", lambda _: SimpleNamespace(malloc_trim=trim))
    monkeypatch.setattr(worker_safety, "process_resident_memory_bytes", lambda: 123456)

    assert worker_safety.release_process_memory(reason="test") == 123456
    assert calls == [0]


def test_identity_route_rejects_overlap_before_invoking_resolver() -> None:
    with worker_safety.collection_slot("live_sync") as acquired:
        assert acquired is True
        with pytest.raises(HTTPException) as error:
            routes.run_identity_batch(object())  # type: ignore[arg-type]
    assert error.value.status_code == 409


def test_live_scheduler_defers_when_identity_collection_is_active(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    settings = SimpleNamespace(poll_live_match_seconds=60, poll_error_backoff_max_seconds=300)

    @contextmanager
    def busy_slot(_: str):
        yield False

    monkeypatch.setattr(polling_scheduler, "get_settings", lambda: settings)
    monkeypatch.setattr(polling_scheduler, "collection_slot", busy_slot)
    monkeypatch.setattr(polling_scheduler, "synchronize_current_bwf", lambda *_args, **_kwargs: pytest.fail("live sync must not start"))

    class Scheduler:
        def reschedule_job(self, job_id: str, **kwargs: object) -> None:
            calls.append((job_id, kwargs))

    polling_scheduler.run_bwf_sync_job(Scheduler())
    assert calls == [(polling_scheduler.JOB_ID, {"trigger": "interval", "seconds": 60})]


def test_identity_checkpoint_uses_allocator_release_after_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []

    class Session:
        def commit(self) -> None:
            events.append("commit")

        def expire_all(self) -> None:
            events.append("expire")

    monkeypatch.setattr(identity_service, "release_process_memory", lambda *, reason: events.append(reason) or 654321)
    identity_service.checkpoint_batch_memory(
        Session(),  # type: ignore[arg-type]
        {"selected": 10, "confirmed_auto": 7, "conflicted": 1, "unresolved": 2, "errors": 0},
        reason="chunk_complete",
    )
    assert events == ["commit", "expire", "identity_chunk_complete"]
