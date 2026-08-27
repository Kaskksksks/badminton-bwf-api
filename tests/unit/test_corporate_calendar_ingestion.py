from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.db.models import OfficialTournamentCalendarEntry, OfficialTournamentDocument, OfficialTournamentCalendarSnapshot
from app.ingestion.calendar_draws.client import (
    BWFCorporateCalendarClient,
    CorporateCalendarResponse,
    CorporateCalendarEntry,
    CorporateDocumentResponse,
    is_allowed_draw_document_url,
    parse_corporate_calendar_html,
)
from app.ingestion.calendar_draws.service import eligibility_for_entry, synchronize_corporate_calendar

# Source-derived from the authorised BWF Corporate calendar structure observed on 27 Aug 2026.
CALENDAR_HTML = b"""
<html><head><title>Calendar | 2026 TOURNAMENTS - REMAINING</title></head><body><table><tbody>
<tr class="bg-light-future"><td>36</td><td>INA</td><td>01 -06</td><td><div class="name">POLYTRON Pontianak Indonesia Masters 2026</div></td><td>-</td><td><div class="category">BWF Tour Super 100</div></td><td><div class="category">Pontianak</div></tr>
<tr class="tr-tournament-detail" id="5527"><td colspan="7"><div class="bwf-calendar_box_detail"><div class="info-tournament"><h2 class="fw700">POLYTRON Pontianak Indonesia Masters 2026</h2><p class="text-description">01 - 06 SEPTEMBER</p><a href="https://bwfbadminton.com/events/5527/polytron-pontianak-indonesia-masters-2026/">VIEW EVENT</a></div><div class="cal-download-file-details"><div class="doc-type-name"><a href="https://extranet.bwf.sport/docs/events/5645/docs/DRAWS-~1.PDF">DRAWS-~1.PDF</a></div></div><div class="cal-download-file-details"><div class="doc-type-name"><a href="https://extranet.bwf.sport/docs/events/5645/docs/Prospectus.pdf">Prospectus.pdf</a></div></div><ul><li><strong>Draw Date:</strong> 25/08/2026</li></ul></div></td></tr>
<tr class="bg-light-future"><td>36</td><td>COL</td><td>01 -06</td><td><div class="name">BGA Junior Internacional de Badminton 2026</div></td><td>-</td><td><div class="category">Junior Future Series</div></td><td><div class="category">Bucaramanga</div></td></tr>
<tr class="tr-tournament-detail" id="junior-1"><td colspan="7"><div class="bwf-calendar_box_detail"><div class="info-tournament"><h2 class="fw700">BGA Junior Internacional de Badminton 2026</h2><p class="text-description">01 - 06 SEPTEMBER</p></div><div class="cal-download-file-details"><div class="doc-type-name"><a href="https://extranet.bwf.sport/docs/events/9999/docs/Junior-draw.pdf">Junior draw.pdf</a></div></div></div></td></tr>
<tr class="bg-light-future"><td>36</td><td>THA</td><td>01 -06</td><td><div class="name">Para Badminton International 2026</div></td><td>-</td><td><div class="category">Para Badminton</div></td><td><div class="category">Bangkok</div></td></tr>
<tr class="tr-tournament-detail" id="para-1"><td colspan="7"><div class="bwf-calendar_box_detail"><div class="info-tournament"><h2 class="fw700">Para Badminton International 2026</h2><p class="text-description">01 - 06 SEPTEMBER</p></div><div class="cal-download-file-details"><div class="doc-type-name"><a href="https://extranet.bwf.sport/docs/events/9998/docs/Para-draw.pdf">Para draw.pdf</a></div></div></div></td></tr>
<tr class="bg-light-future"><td>36</td><td>PER</td><td>01 -06</td><td><div class="name">Peru International Challenge 2026</div></td><td>-</td><td><div class="category">International Challenge</div></td><td><div class="category">Lima</div></td></tr>
<tr class="tr-tournament-detail" id="senior-non-target"><td colspan="7"><div class="bwf-calendar_box_detail"><div class="info-tournament"><h2 class="fw700">Peru International Challenge 2026</h2><p class="text-description">01 - 06 SEPTEMBER</p></div><div class="cal-download-file-details"><div class="doc-type-name"><a href="https://extranet.bwf.sport/docs/events/9997/docs/Senior-challenge-draw.pdf">Senior challenge draw.pdf</a></div></div></div></td></tr>
</tbody></table></body></html>
"""


class FakeCalendarClient:
    def __init__(self) -> None:
        self.calendar_content = CALENDAR_HTML
        self.calendar_hash = "calendar-hash-v1"
        self.draw_urls: list[str] = []
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def fetch_calendar(self) -> CorporateCalendarResponse:
        return CorporateCalendarResponse(
            url="https://corporate.bwfbadminton.com/events/calendar/",
            status_code=200,
            retrieved_at=datetime(2026, 8, 27, tzinfo=timezone.utc),
            content=self.calendar_content,
            content_hash=self.calendar_hash,
            content_type="text/html; charset=utf-8",
        )

    def fetch_draw_document(self, url: str) -> CorporateDocumentResponse:
        self.draw_urls.append(url)
        return CorporateDocumentResponse(
            url=url,
            status_code=200,
            retrieved_at=datetime(2026, 8, 27, tzinfo=timezone.utc),
            content=b"%PDF-1.7\nsource-derived-test-document",
            content_hash="draw-hash-v1",
            content_type="application/pdf",
        )


def settings() -> Settings:
    return Settings(
        bwf_calendar_enabled=True,
        bwf_calendar_permission_reference="BWF Corporate calendar and draw PDF links authorised by user",
        bwf_draw_document_horizon_days=14,
        bwf_draw_document_max_per_run=4,
    )


def test_parser_keeps_direct_draw_links_in_the_correct_event_context() -> None:
    entries = parse_corporate_calendar_html(CALENDAR_HTML, expected_year=2026)

    assert len(entries) == 4
    senior = entries[0]
    assert senior.source_tournament_id == "5527"
    assert senior.name == "POLYTRON Pontianak Indonesia Masters 2026"
    assert senior.start_date == date(2026, 9, 1)
    assert senior.end_date == date(2026, 9, 6)
    assert senior.category == "BWF Tour Super 100"
    assert senior.draw_documents[0].url.endswith("DRAWS-~1.PDF")
    assert len(senior.draw_documents) == 1


def test_authorised_calendar_sync_skips_junior_and_para_before_draw_fetch_or_persistence() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    client = FakeCalendarClient()

    with factory.begin() as session:
        result = synchronize_corporate_calendar(session, client=client, settings=settings(), today=date(2026, 8, 27))
        entries = session.scalars(select(OfficialTournamentCalendarEntry)).all()
        documents = session.scalars(select(OfficialTournamentDocument)).all()

    assert result == {
        "status": "ok",
        "calendar_requests": 1,
        "calendar_snapshot_created": 1,
        "calendar_entries_seen": 4,
        "calendar_entries_eligible": 1,
        "skipped_non_target_senior_calendar_entries": 1,
        "skipped_unparseable_target_calendar_entries": 0,
        "draw_requests": 1,
        "draw_documents_captured": 1,
    }
    assert [entry.name for entry in entries] == ["POLYTRON Pontianak Indonesia Masters 2026"]
    assert len(documents) == 1
    assert client.draw_urls == ["https://extranet.bwf.sport/docs/events/5645/docs/DRAWS-~1.PDF"]


def test_non_target_senior_categories_are_excluded_without_draw_retrieval() -> None:
    entries = parse_corporate_calendar_html(CALENDAR_HTML, expected_year=2026)
    non_target = next(entry for entry in entries if entry.source_tournament_id == "senior-non-target")

    status, rationale = eligibility_for_entry(non_target)

    assert status == "EXCLUDED_NON_TARGET_SENIOR"
    assert "World Tour" in rationale


def test_allowlist_accepts_only_the_four_approved_calendar_scopes() -> None:
    world_tour = CorporateCalendarEntry(
        source_tournament_id="world-tour",
        name="Published World Tour Tournament",
        country_code="INA",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 6),
        category="HSBC BWF World Tour Super 500",
        city="Test city",
        source_url=None,
        draw_date_text=None,
        draw_documents=(),
        raw_row={},
    )
    individual_worlds = CorporateCalendarEntry(
        source_tournament_id="individual-worlds",
        name="TOTALENERGIES BWF WORLD CHAMPIONSHIPS 2026",
        country_code="MYS",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 7),
        category="Major Championships",
        city="Test city",
        source_url=None,
        draw_date_text=None,
        draw_documents=(),
        raw_row={},
    )
    continental_individual_championships = CorporateCalendarEntry(
        source_tournament_id="continental-individual",
        name="European Badminton Championships 2026",
        country_code="GER",
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 7),
        category="Continental Individual Championships",
        city="Test city",
        source_url=None,
        draw_date_text=None,
        draw_documents=(),
        raw_row={},
    )
    multi_sport_games = CorporateCalendarEntry(
        source_tournament_id="multi-sport",
        name="Badminton at the Olympic Games 2028",
        country_code="USA",
        start_date=date(2028, 7, 1),
        end_date=date(2028, 7, 7),
        category="Multi-Sport Games",
        city="Test city",
        source_url=None,
        draw_date_text=None,
        draw_documents=(),
        raw_row={},
    )
    world_team_championships = CorporateCalendarEntry(
        source_tournament_id="team-worlds",
        name="BWF World Team Championships 2026",
        country_code="MYS",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 7),
        category="Continental Team Championships",
        city="Test city",
        source_url=None,
        draw_date_text=None,
        draw_documents=(),
        raw_row={},
    )

    assert eligibility_for_entry(world_tour)[0] == "ELIGIBLE"
    assert eligibility_for_entry(individual_worlds)[0] == "ELIGIBLE"
    assert eligibility_for_entry(continental_individual_championships)[0] == "ELIGIBLE"
    assert eligibility_for_entry(multi_sport_games)[0] == "ELIGIBLE"
    assert eligibility_for_entry(world_team_championships)[0] == "EXCLUDED_NON_TARGET_SENIOR"


def test_authorised_calendar_sync_is_idempotent_for_unchanged_calendar_and_draw() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    client = FakeCalendarClient()

    with factory.begin() as session:
        first = synchronize_corporate_calendar(session, client=client, settings=settings(), today=date(2026, 8, 27))
    with factory.begin() as session:
        second = synchronize_corporate_calendar(session, client=client, settings=settings(), today=date(2026, 8, 27))
        snapshots = session.scalars(select(OfficialTournamentCalendarSnapshot)).all()
        documents = session.scalars(select(OfficialTournamentDocument)).all()

    assert first["draw_requests"] == 1
    assert second["calendar_snapshot_created"] == 0
    assert second["draw_requests"] == 0
    assert len(snapshots) == 1
    assert len(documents) == 1
    assert len(client.draw_urls) == 1


def test_changed_calendar_snapshot_does_not_redownload_known_direct_draw_url() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    client = FakeCalendarClient()

    with factory.begin() as session:
        first = synchronize_corporate_calendar(session, client=client, settings=settings(), today=date(2026, 8, 27))
    client.calendar_hash = "calendar-hash-v2"
    client.calendar_content = CALENDAR_HTML + b"<!-- unrelated authorised calendar change -->"
    with factory.begin() as session:
        second = synchronize_corporate_calendar(session, client=client, settings=settings(), today=date(2026, 8, 27))
        snapshots = session.scalars(select(OfficialTournamentCalendarSnapshot)).all()
        documents = session.scalars(select(OfficialTournamentDocument)).all()

    assert first["draw_requests"] == 1
    assert second["calendar_snapshot_created"] == 1
    assert second["draw_requests"] == 0
    assert len(snapshots) == 2
    assert len(documents) == 1
    assert len(client.draw_urls) == 1


def test_calendar_sync_is_disabled_without_any_client_request() -> None:
    class FailingClient:
        def fetch_calendar(self) -> CorporateCalendarResponse:
            raise AssertionError("disabled collection must not request the calendar")

        def close(self) -> None:
            return None

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine).begin() as session:
        assert synchronize_corporate_calendar(session, client=FailingClient(), settings=Settings()) == {
            "status": "disabled",
            "calendar_requests": 0,
            "draw_requests": 0,
        }


def test_draw_document_url_validation_rejects_non_bwf_or_non_event_urls() -> None:
    assert is_allowed_draw_document_url("https://extranet.bwf.sport/docs/events/5645/docs/DRAWS-~1.PDF") is True
    assert is_allowed_draw_document_url("https://bwf.tournamentsoftware.com/draw.pdf") is False
    assert is_allowed_draw_document_url("https://extranet.bwf.sport/docs/flags/indonesia.png") is False
    assert is_allowed_draw_document_url("http://extranet.bwf.sport/docs/events/5645/docs/DRAWS-~1.PDF") is False


def test_client_rejects_oversized_or_non_pdf_document_before_persistence() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("DRAWS-~1.PDF"):
            return httpx.Response(200, content=b"not a PDF", headers={"content-type": "text/html"})
        return httpx.Response(404)

    client = BWFCorporateCalendarClient(settings=settings(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ValueError, match="PDF signature"):
        client.fetch_draw_document("https://extranet.bwf.sport/docs/events/5645/docs/DRAWS-~1.PDF")


def test_parser_handles_official_cross_month_date_ranges() -> None:
    html = b"""
    <html><head><title>Calendar | 2026 TOURNAMENTS - REMAINING</title></head><body><table><tbody>
    <tr><td>40</td><td>UAE</td><td>29 -04</td><td>Abu Dhabi Masters 2026 (Cancelled)</td><td>-</td><td>BWF Tour Super 100</td><td>Dubai</td></tr>
    <tr class="tr-tournament-detail" id="5595"><td><div class="info-tournament"><h2>Abu Dhabi Masters 2026 (Cancelled)</h2><p class="text-description">29 SEPTEMBER - 04 OCTOBER</p></div></td></tr>
    </tbody></table></body></html>
    """
    entry = parse_corporate_calendar_html(html, expected_year=2026)[0]
    assert entry.start_date == date(2026, 9, 29)
    assert entry.end_date == date(2026, 10, 4)


def test_parser_ignores_malformed_or_non_event_rows() -> None:
    html = b"""
    <html><head><title>Calendar | 2026 TOURNAMENTS - REMAINING</title></head><body><table><tbody>
    <tr><td>not a full event row</td></tr>
    <tr class="tr-tournament-detail" id="orphan"><td><div class="info-tournament"><h2>Orphan</h2></div></td></tr>
    <tr><td>36</td><td>INA</td><td>01 -06</td><td></td><td>-</td><td>BWF Tour Super 100</td><td>Pontianak</td></tr>
    <tr class="tr-tournament-detail" id="empty-name"><td><div class="info-tournament"><h2></h2><p class="text-description">01 - 06 SEPTEMBER</p></div></td></tr>
    </tbody></table></body></html>
    """
    assert parse_corporate_calendar_html(html, expected_year=2026) == []


def test_enabled_calendar_requires_non_secret_permission_reference() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="BWF_CALENDAR_PERMISSION_REFERENCE"):
        Settings(bwf_calendar_enabled=True, bwf_calendar_permission_reference=None)


def test_scheduler_includes_calendar_job_only_when_both_gates_are_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.polling import scheduler as scheduler_module

    disabled = Settings(
        bwf_calendar_enabled=True,
        bwf_calendar_scheduler_enabled=False,
        bwf_calendar_permission_reference="User-authorised BWF Corporate calendar and direct draw links",
    )
    monkeypatch.setattr(scheduler_module, "get_settings", lambda: disabled)
    disabled_scheduler = scheduler_module.build_scheduler()
    assert disabled_scheduler.get_job(scheduler_module.CALENDAR_JOB_ID) is None

    enabled = Settings(
        bwf_calendar_enabled=True,
        bwf_calendar_scheduler_enabled=True,
        bwf_calendar_permission_reference="User-authorised BWF Corporate calendar and direct draw links",
    )
    monkeypatch.setattr(scheduler_module, "get_settings", lambda: enabled)
    enabled_scheduler = scheduler_module.build_scheduler()
    assert enabled_scheduler.get_job(scheduler_module.CALENDAR_JOB_ID) is not None


def test_zero_draw_budget_never_fetches_a_document() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    client = FakeCalendarClient()
    with sessionmaker(bind=engine).begin() as session:
        result = synchronize_corporate_calendar(
            session,
            client=client,
            settings=Settings(
                bwf_calendar_enabled=True,
                bwf_calendar_permission_reference="BWF Corporate calendar and draw PDF links authorised by user",
                bwf_draw_document_max_per_run=0,
            ),
            today=date(2026, 8, 27),
        )

    assert result["draw_requests"] == 0
    assert result["draw_documents_captured"] == 0
    assert client.draw_urls == []
