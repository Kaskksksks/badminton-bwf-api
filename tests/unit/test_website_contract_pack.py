from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.website_contract_service import active_senior_participants, calendar_entries, draw_documents, model_contract, official_bracket, tournament_simulation_snapshot
from app.db.base import Base, get_db
from app.db.models import (
    DataSource,
    Event,
    Match,
    MatchParticipantContext,
    OfficialTournamentCalendarEntry,
    OfficialTournamentCalendarSnapshot,
    OfficialTournamentDocument,
    OfficialDrawNode,
    Participant,
    ParticipantMember,
    Player,
    Tournament,
)
from app.ingestion.calendar_draws.topology import (
    parse_direct_draw_text,
    publish_topology_after_full_reconciliation,
    record_canonical_reconciliation,
    stage_topology_from_extracted_text,
)
from app.main import app


def session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def eligible_calendar_entry(session):
    source = DataSource(code="BWF_CORPORATE_CALENDAR", source_kind="BWF_CORPORATE_CALENDAR", display_name="BWF Corporate", base_url="https://corporate.bwfbadminton.com/events/calendar/")
    session.add(source)
    session.flush()
    snapshot = OfficialTournamentCalendarSnapshot(source_id=source.id, source_url="https://corporate.bwfbadminton.com/events/calendar/", retrieved_at=datetime(2026, 8, 27, tzinfo=timezone.utc), content_hash="calendar-source-hash", content_type="text/html", byte_size=321, parser_version="bwf-corporate-calendar-v1", snapshot_status="PARSED", entry_count=1)
    session.add(snapshot)
    session.flush()
    entry = OfficialTournamentCalendarEntry(snapshot_id=snapshot.id, source_tournament_id="5527", name="BWF World Tour Super 500", country_code="INA", start_date=date(2026, 9, 1), end_date=date(2026, 9, 6), category="BWF World Tour Super 500", city="Jakarta", source_url="https://bwfbadminton.com/events/5527/", draw_date_text="25/08/2026", eligibility_status="ELIGIBLE", eligibility_rationale="Approved calendar category", raw_payload={"must_not": "leave_server"})
    session.add(entry)
    session.flush()
    return entry


def test_calendar_and_document_contracts_are_read_only_and_eligible_only() -> None:
    factory = session_factory()
    with factory.begin() as session:
        entry = eligible_calendar_entry(session)
        excluded = OfficialTournamentCalendarEntry(snapshot_id=entry.snapshot_id, source_tournament_id="x", name="Future Series", country_code=None, start_date=date(2026, 9, 1), end_date=date(2026, 9, 3), category="Future Series", city=None, source_url=None, draw_date_text=None, eligibility_status="EXCLUDED_NON_TARGET_SENIOR", eligibility_rationale="Excluded", raw_payload={})
        session.add(excluded)
        session.add(OfficialTournamentDocument(calendar_entry_id=entry.id, source_url="https://extranet.bwf.sport/docs/events/5645/docs/DRAWS-~1.PDF", document_label="DRAWS-~1.PDF", retrieved_at=datetime(2026, 8, 27, tzinfo=timezone.utc), content_hash="official-pdf-hash", content_type="application/pdf", byte_size=2048, parser_version="bwf-corporate-calendar-v1", parser_status="CAPTURED_REVIEW_REQUIRED", parser_issue="Awaiting real document validation"))
        session.flush()
        calendar, total = calendar_entries(session, page=1, page_size=50)
        documents = draw_documents(session, entry.id)
        excluded_documents = draw_documents(session, excluded.id)

    assert total == 1
    assert calendar[0].name == "BWF World Tour Super 500"
    assert calendar[0].provenance.source_code == "BWF_CORPORATE_CALENDAR"
    assert not hasattr(calendar[0], "raw_payload")
    assert documents[0].content_hash == "official-pdf-hash"
    assert not hasattr(documents[0], "content")
    assert excluded_documents == []


def test_active_pair_contract_requires_confirmed_members_and_recent_approved_senior_context() -> None:
    factory = session_factory()
    with factory.begin() as session:
        tournament = Tournament(name="BWF World Tour Super 500", source_name_raw="BWF World Tour Super 500", source_category_raw="BWF World Tour Super 500", status="ACTIVE")
        session.add(tournament)
        session.flush()
        event = Event(tournament_id=tournament.id, event_type="MD", category="BWF World Tour Super 500")
        first, second = Player(full_name="One", identity_status="CONFIRMED"), Player(full_name="Two", identity_status="CONFIRMED")
        session.add_all([event, first, second])
        session.flush()
        pair = Participant(participant_kind="PAIR", canonical_member_hash="pair-hash", display_name="One / Two", identity_resolution_status="UNRESOLVED")
        session.add(pair)
        session.flush()
        session.add_all([ParticipantMember(participant_id=pair.id, player_id=first.id, member_order=1), ParticipantMember(participant_id=pair.id, player_id=second.id, member_order=2)])
        match = Match(source_match_key="test:approved-pair", match_date=date.today(), tournament_id=tournament.id, event_id=event.id, status="COMPLETED", completion_basis="BWF_OFFICIAL_RESPONSE")
        session.add(match)
        session.flush()
        session.add(MatchParticipantContext(match_id=match.id, participant_id=pair.id, side=1))
        session.flush()
        data, total = active_senior_participants(session, page=1, page_size=20)

    assert total == 1
    assert data[0].kind == "pair"
    assert data[0].member_ids == [first.id, second.id]
    assert data[0].recent_eligible_match_count == 1
    assert "Every required underlying member is provider-confirmed" in data[0].eligibility_rationale


def test_direct_draw_parser_stays_withheld_until_all_nodes_are_reconciled() -> None:
    factory = session_factory()
    with factory.begin() as session:
        entry = eligible_calendar_entry(session)
        document = OfficialTournamentDocument(calendar_entry_id=entry.id, source_url="https://extranet.bwf.sport/docs/events/5645/docs/DRAWS-~1.PDF", document_label="DRAWS-~1.PDF", retrieved_at=datetime.now(timezone.utc), content_hash="draw-hash", content_type="application/pdf", byte_size=1024, parser_version="bwf-corporate-calendar-v1", parser_status="CAPTURED_REVIEW_REQUIRED", parser_issue=None)
        session.add(document)
        session.flush()
        assert parse_direct_draw_text("32\nAlice vs Bob", discipline="MS")[0].round_label == "32"
        availability, _, _, nodes = official_bracket(session, calendar_entry_id=entry.id, discipline="MS")
        assert availability.available is False
        assert nodes == []
        topology = stage_topology_from_extracted_text(session, document_id=document.id, discipline="MS", source_content_hash="draw-hash", extracted_text="32\nAlice vs Bob")
        availability, _, _, nodes = official_bracket(session, calendar_entry_id=entry.id, discipline="MS")
        assert availability.reason == "topology_pending_review"
        assert nodes == []
        node = session.query(OfficialDrawNode).filter_by(topology_id=topology.id).one()
        match = Match(source_match_key="test:draw-match", match_date=date.today(), status="SCHEDULED", completion_basis="BWF_OFFICIAL_RESPONSE")
        session.add(match)
        session.flush()
        record_canonical_reconciliation(session, node_id=node.id, match_id=match.id, rationale="Reviewer matched the source node to the canonical official match ID.")
        publish_topology_after_full_reconciliation(session, topology_id=topology.id, review_note="All source nodes reviewed and reconciled.")
        availability, _, _, nodes = official_bracket(session, calendar_entry_id=entry.id, discipline="MS")

    assert availability.available is True
    assert len(nodes) == 1
    assert nodes[0].canonical_match_id == match.id


def test_model_contracts_are_withheld_without_real_evidence() -> None:
    factory = session_factory()
    with factory.begin() as session:
        contract = model_contract(session)

    assert contract["model"].available is False
    assert contract["predictions"].reason == "no_published_pre_match_forecast_snapshot"
    assert contract["head_to_head"].available is False
    assert contract["simulations"].available is False


def test_tournament_simulation_contract_requires_a_canonical_calendar_link_and_published_reconciled_snapshot() -> None:
    factory = session_factory()
    with factory.begin() as session:
        entry = eligible_calendar_entry(session)
        availability, snapshot = tournament_simulation_snapshot(session, entry.id)

    assert availability.available is False
    assert availability.reason == "canonical_tournament_link_not_available"
    assert snapshot is None


def test_public_match_route_accepts_typed_date_filters_without_database_errors() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        tournament = Tournament(name="Approved", source_name_raw="Approved", source_category_raw="BWF World Tour Super 500", status="ACTIVE")
        session.add(tournament)
        session.flush()
        event = Event(tournament_id=tournament.id, event_type="MS", category="BWF World Tour Super 500")
        session.add(event)
        session.flush()
        session.add(Match(source_match_key="test:filtered-date", match_date=date(2026, 8, 24), tournament_id=tournament.id, event_id=event.id, status="COMPLETED", completion_basis="BWF_OFFICIAL_RESPONSE"))

    def override_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    try:
        response = TestClient(app).get("/api/v1/website/matches?scope=completed&from_date=2026-08-01&to_date=2026-08-31")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["pagination"]["total"] == 1
    assert response.json()["data"][0]["id"]


def test_confirmed_player_history_route_returns_bounded_approved_match_records() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        tournament = Tournament(name="Approved", source_name_raw="Approved", source_category_raw="BWF World Tour Super 500", status="ACTIVE")
        session.add(tournament)
        session.flush()
        event = Event(tournament_id=tournament.id, event_type="WS", category="BWF World Tour Super 500")
        player = Player(full_name="Confirmed Player", identity_status="CONFIRMED", country_code="JPN")
        opponent = Player(full_name="Opponent", identity_status="CONFIRMED", country_code="KOR")
        session.add_all([event, player, opponent])
        session.flush()
        first = Participant(participant_kind="PLAYER", canonical_member_hash="confirmed-player", display_name="Confirmed Player", identity_resolution_status="CONFIRMED")
        second = Participant(participant_kind="PLAYER", canonical_member_hash="opponent", display_name="Opponent", identity_resolution_status="CONFIRMED")
        session.add_all([first, second])
        session.flush()
        session.add_all([ParticipantMember(participant_id=first.id, player_id=player.id, member_order=1), ParticipantMember(participant_id=second.id, player_id=opponent.id, member_order=1)])
        session.add(Match(source_match_key="test:confirmed-player-history", match_date=date(2026, 8, 24), tournament_id=tournament.id, event_id=event.id, status="COMPLETED", completion_basis="BWF_OFFICIAL_RESPONSE", participant_1_id=first.id, participant_2_id=second.id, winner_participant_id=first.id, score_raw="21-18 21-15"))
        session.flush()
        player_id = player.id

    def override_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    try:
        response = TestClient(app).get(f"/api/v1/website/players/{player_id}/matches?scope=completed&page=1&page_size=10")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["pagination"] == {"page": 1, "page_size": 10, "total": 1}
    assert response.json()["data"][0]["winner_participant_id"]
    assert response.json()["data"][0]["participant_1"]["members"][0]["id"] == player_id


def test_website_player_directory_includes_all_confirmed_identities_not_only_current_active_participants() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        confirmed = Player(full_name="Stored Confirmed Player", identity_status="CONFIRMED", country_code="JPN")
        unresolved = Player(full_name="Unresolved Player", identity_status="UNRESOLVED", country_code="JPN")
        session.add_all([confirmed, unresolved])

    def override_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    try:
        response = TestClient(app).get("/api/v1/website/players?page=1&page_size=10")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["pagination"]["total"] == 1
    assert response.json()["data"] == [{"id": confirmed.id, "full_name": "Stored Confirmed Player", "country_code": "JPN", "profile_url": None, "identity_status": "CONFIRMED"}]


def test_public_contract_routes_return_read_only_metadata_and_explicitly_withheld_future_capabilities() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        entry = eligible_calendar_entry(session)
        document = OfficialTournamentDocument(calendar_entry_id=entry.id, source_url="https://extranet.bwf.sport/docs/events/5645/docs/DRAWS-~1.PDF", document_label="DRAWS-~1.PDF", retrieved_at=datetime.now(timezone.utc), content_hash="http-contract-draw", content_type="application/pdf", byte_size=1024, parser_version="bwf-corporate-calendar-v1", parser_status="CAPTURED_REVIEW_REQUIRED", parser_issue="Awaiting validation")
        session.add(document)
        session.flush()
        entry_id = entry.id

    def override_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        calendar = client.get("/api/v1/website/calendar")
        documents = client.get(f"/api/v1/website/calendar/{entry_id}/draw-documents")
        brackets = client.get(f"/api/v1/website/calendar/{entry_id}/brackets/MS")
        participants = client.get("/api/v1/website/active-participants")
        readiness = client.get("/api/v1/website/model-contract")
        forecast = client.get("/api/v1/website/matches/not-a-match/forecast")
        simulation = client.get(f"/api/v1/website/calendar/{entry_id}/simulation")
    finally:
        app.dependency_overrides.clear()

    assert calendar.status_code == 200
    assert calendar.json()["data"][0]["eligibility_status"] == "ELIGIBLE"
    assert "raw_payload" not in calendar.json()["data"][0]
    assert documents.status_code == 200
    assert documents.json()["data"][0]["document_label"] == "DRAWS-~1.PDF"
    assert brackets.status_code == 200
    assert brackets.json()["availability"]["available"] is False
    assert brackets.json()["availability"]["reason"] == "official_document_captured_parser_not_validated"
    assert participants.status_code == 200
    assert participants.json()["data"] == []
    assert readiness.status_code == 200
    assert readiness.json()["data"]["predictions"]["available"] is False
    assert forecast.status_code == 200
    assert forecast.json()["availability"]["available"] is False
    assert forecast.json()["win_probability"]["reason"] == "win_probability_eligible_match_not_found"
    assert forecast.json()["uncertainty"]["reason"] == "uncertainty_eligible_match_not_found"
    assert simulation.status_code == 200
    assert simulation.json()["availability"]["available"] is False


def test_website_tournament_delivery_excludes_unrecognised_and_prohibited_senior_categories() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        allowed = Tournament(name="Approved", source_name_raw="Approved", source_category_raw="BWF World Tour Super 500", status="ACTIVE")
        excluded = Tournament(name="Challenge", source_name_raw="Challenge", source_category_raw="International Challenge", status="ACTIVE")
        unknown = Tournament(name="Unknown", source_name_raw="Unknown", source_category_raw="Senior Open", status="ACTIVE")
        session.add_all([allowed, excluded, unknown])

    def override_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    try:
        response = TestClient(app).get("/api/v1/website/tournaments")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert [row["name"] for row in response.json()["data"]] == ["Approved"]
