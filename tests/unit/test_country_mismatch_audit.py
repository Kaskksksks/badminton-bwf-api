from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.v1.routes import _apply_country_mismatch_resolution, _country_mismatch_audit_rows
from app.db.base import Base
from app.db.models import (
    DataSource,
    Event,
    Match,
    MatchParticipantContext,
    Participant,
    ParticipantMember,
    Player,
    PlayerAlias,
    PlayerIdentityLink,
    PlayerProfileSnapshot,
    ReconciliationCase,
    Tournament,
)


def add_recent_senior_context(session: Session, alias: PlayerAlias, key: str) -> None:
    participant = Participant(
        participant_kind="SINGLES",
        canonical_member_hash=f"participant-{key}",
        display_name=alias.alias_text,
    )
    session.add(participant)
    session.flush()
    session.add(ParticipantMember(
        participant_id=participant.id,
        member_order=1,
        source_alias_id=alias.id,
        source_alias_text=alias.alias_text,
    ))
    tournament = Tournament(name="Senior Open", source_name_raw="Senior Open", status="COMPLETED")
    session.add(tournament)
    session.flush()
    event = Event(tournament_id=tournament.id, event_type="MS")
    session.add(event)
    session.flush()
    match = Match(
        source_match_key=f"mismatch-{key}",
        tournament_id=tournament.id,
        event_id=event.id,
        participant_1_id=participant.id,
        match_date=date.today(),
        status="COMPLETED",
        completion_basis="TEST_CONTEXT",
        source_completeness="COMPLETE",
        historical_seed_flag=True,
    )
    session.add(match)
    session.flush()
    session.add(MatchParticipantContext(match_id=match.id, participant_id=participant.id, side=1))
    session.flush()


def add_conflicted_link(
    session: Session,
    *,
    key: str,
    search_code: str,
    profile_code: str,
    exact_candidate_count: int = 1,
) -> tuple[PlayerAlias, PlayerIdentityLink]:
    source = session.scalar(select(DataSource).where(DataSource.code == "TEST_SOURCE"))
    if source is None:
        source = DataSource(
            code="TEST_SOURCE",
            source_kind="HISTORICAL_SEED",
            display_name="Test source",
            base_url=None,
        )
        session.add(source)
        session.flush()
    alias = PlayerAlias(
        source_id=source.id,
        alias_text=f"Player {key}",
        normalized_alias=f"PLAYER {key}",
        resolution_status="CONFLICTED",
    )
    player = Player(full_name=f"Player {key}", country_code="RUS")
    session.add_all([alias, player])
    session.flush()
    snapshot = PlayerProfileSnapshot(
        source_id=source.id,
        bwf_profile_id=f"profile-{key}",
        source_url=f"https://official.example.test/player/{key}",
        content_hash=f"snapshot-{key}",
        profile_name=player.full_name,
        country_code="RUS",
        payload={"nationality": profile_code},
        parser_version="test",
    )
    session.add(snapshot)
    session.flush()
    link = PlayerIdentityLink(
        alias_id=alias.id,
        player_id=player.id,
        profile_snapshot_id=snapshot.id,
        decision_status="CONFLICTED",
        decision_class="COUNTRY_MISMATCH",
        score=20,
        resolver_version="bwf-profile-auto-resolver-v2",
        evidence={
            "official_profile_id": f"profile-{key}",
            "profile_snapshot_id": snapshot.id,
            "search_country_code": search_code,
            "official_profile_bwf_nationality_code": profile_code,
            "exact_candidate_count": exact_candidate_count,
        },
        rationale="Official country codes disagree.",
    )
    session.add(link)
    session.flush()
    add_recent_senior_context(session, alias, key)
    return alias, link


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    active_session = Session(engine)
    try:
        yield active_session
    finally:
        active_session.close()
        Base.metadata.drop_all(engine)


def test_audit_is_database_only_and_distinguishes_standard_and_manual_policy_cases(session: Session) -> None:
    add_conflicted_link(session, key="equivalent", search_code="MYS", profile_code="MAS")
    add_conflicted_link(session, key="neutral", search_code="AIN", profile_code="RUS")
    add_conflicted_link(session, key="england", search_code="ENG", profile_code="GBR")
    add_conflicted_link(session, key="collision", search_code="AIN", profile_code="RUS", exact_candidate_count=2)

    rows = _country_mismatch_audit_rows(session)
    by_alias = {row["alias_text"]: row for row in rows}

    assert by_alias["Player equivalent"]["proposed_disposition"] == "AUTO_EQUIVALENT_ELIGIBLE"
    assert by_alias["Player neutral"]["proposed_disposition"] == "MANUAL_OVERRIDE_ELIGIBLE"
    assert by_alias["Player england"]["proposed_disposition"] == "MANUAL_OVERRIDE_ELIGIBLE"
    assert by_alias["Player collision"]["proposed_disposition"] == "REMAIN_CONFLICTED"
    assert by_alias["Player collision"]["blocker"] == "MULTIPLE_OR_NONUNIQUE_EXACT_CANDIDATES"
    assert all(row["recent_senior_eligible"] for row in rows)


def test_apply_manual_override_preserves_original_conflict_and_is_idempotent(session: Session) -> None:
    alias, original_link = add_conflicted_link(session, key="manual", search_code="AIN", profile_code="RUS")
    row = _country_mismatch_audit_rows(session)[0]

    assert row["proposed_disposition"] == "MANUAL_OVERRIDE_ELIGIBLE"
    assert _apply_country_mismatch_resolution(session, row, actor="TEST_ADMIN") is True
    assert _apply_country_mismatch_resolution(session, row, actor="TEST_ADMIN") is False

    session.flush()
    session.refresh(alias)
    links = session.scalars(select(PlayerIdentityLink).where(PlayerIdentityLink.alias_id == alias.id)).all()
    original = session.get(PlayerIdentityLink, original_link.id)
    override = next(link for link in links if link.id != original_link.id)
    resolution_case = session.scalar(select(ReconciliationCase).where(
        ReconciliationCase.case_type == "PLAYER_IDENTITY_COUNTRY_MISMATCH_RESOLUTION",
        ReconciliationCase.candidate_entity_id == alias.id,
    ))

    assert alias.resolution_status == "CONFIRMED"
    assert alias.player_id == original_link.player_id
    assert original is not None
    assert original.decision_status == "CONFLICTED"
    assert override.decision_status == "CONFIRMED_MANUAL_OVERRIDE"
    assert override.decision_class == "USER_DIRECTED_COUNTRY_OVERRIDE"
    assert override.evidence["country_mismatch_review"]["manual_override_pair"] == "AIN:RUS"
    assert resolution_case is not None
    assert resolution_case.status == "RESOLVED"


def test_apply_refuses_ineligible_or_ambiguous_country_mismatch_case(session: Session) -> None:
    alias, original_link = add_conflicted_link(
        session,
        key="ambiguous",
        search_code="ENG",
        profile_code="GBR",
        exact_candidate_count=2,
    )
    row = _country_mismatch_audit_rows(session)[0]

    assert row["proposed_disposition"] == "REMAIN_CONFLICTED"
    assert _apply_country_mismatch_resolution(session, row, actor="TEST_ADMIN") is False
    session.flush()
    session.refresh(alias)
    assert alias.player_id is None
    assert session.get(PlayerIdentityLink, original_link.id).decision_status == "CONFLICTED"


def test_protected_route_functions_report_and_apply_without_network(session: Session) -> None:
    from app.api.v1.routes import apply_country_mismatch_resolutions, country_mismatch_audit

    add_conflicted_link(session, key="route", search_code="AIN", profile_code="RUS")
    report = country_mismatch_audit(session, page=1, page_size=10)

    assert report["meta"]["source"] == "LOCAL_STORED_IDENTITY_EVIDENCE"
    assert report["summary"]["counts"]["MANUAL_OVERRIDE_ELIGIBLE"] == 1
    assert report["data"][0]["proposed_disposition"] == "MANUAL_OVERRIDE_ELIGIBLE"

    applied = apply_country_mismatch_resolutions(session, action="APPLY")
    assert applied["data"] == {
        "applied_auto_equivalent": 0,
        "applied_manual_override": 1,
        "skipped": 0,
    }
    assert applied["meta"]["source"] == "LOCAL_STORED_IDENTITY_EVIDENCE"
