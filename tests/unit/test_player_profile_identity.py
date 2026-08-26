from __future__ import annotations

from datetime import date, timedelta

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.v1.routes import identity_coverage
from app.core.config import Settings
from app.db.base import Base
from app.db.models import (
    DataSource,
    Event,
    ImportBatch,
    Match,
    MatchParticipantContext,
    Participant,
    ParticipantMember,
    Player,
    PlayerAlias,
    PlayerProfileSnapshot,
    ReconciliationCase,
    Tournament,
)
from app.ingestion.player_profiles.service import (
    BWFPlayerProfileClient,
    Candidate,
    NO_EXACT_CANDIDATE_CASE_TYPE,
    NO_RECENT_SENIOR_ACTIVITY_CASE_TYPE,
    NO_SENIOR_CONTEXT_CASE_TYPE,
    RECENT_SENIOR_ELIGIBLE_CASE_TYPE,
    SourceAccessStopped,
    SourceResponse,
    context_summary_for_alias,
    context_summary_for_player,
    decide_alias,
    ensure_collection_allowed,
    extract_candidates,
    extract_profile,
    normalize_name,
    run_full_queue,
    run_local_classification_sweep,
)


def enabled_settings(**changes: object) -> Settings:
    values: dict[str, object] = {
        "bwf_player_profiles_enabled": True,
        "bwf_player_profiles_allow_live_source": True,
        "bwf_player_profiles_permission_reference": "authorised-test-reference",
        "bwf_player_profiles_min_request_interval_seconds": 1,
    }
    values.update(changes)
    return Settings(**values)


def profile_snapshot(
    profile_id: str = "58240", name: str = "Yuta Watanabe", country: str = "JPN", nationality: str | None = None
) -> PlayerProfileSnapshot:
    return PlayerProfileSnapshot(
        id="snapshot-1", source_id="source-1", bwf_profile_id=profile_id, source_url=f"https://bwfbadminton.com/player/{profile_id}",
        content_hash="hash", profile_name=name, country_code=country,
        payload={"nationality": nationality or country}, parser_version="test",
    )


def test_normalises_aliases_without_diacritics() -> None:
    assert normalize_name("  José  Pérez-Smith ") == "JOSE PEREZ SMITH"


def test_extracts_observed_search_candidates() -> None:
    candidates = extract_candidates([{"id": 58240, "name_display": "YUTA WATANABE", "nationality_item": {"code_iso3": "JPN"}}])
    assert candidates == [Candidate("58240", "YUTA WATANABE", "JPN")]


def test_extracts_observed_bold_search_name_and_flag_country_code() -> None:
    candidates = extract_candidates([{
        "id": 54360,
        "name_display_bold": '<span class="name-2">JOO</span> <span class="name-1">Eun Ae</span>',
        "nationality_item": {"name": "Korea", "flag_url_thumbnail": "https://img.bwfbadminton.com/image/upload/v2/assets/flag-circle-svg-custom/KOR.png"},
    }])
    assert candidates == [Candidate("54360", "JOO Eun Ae", "KOR")]


def test_extracts_official_profile_summary() -> None:
    profile = extract_profile({"results": {"id": 58240, "name_display": "Yuta Watanabe", "date_of_birth": "1997-06-13", "nationality": "JPN", "country_model": {"code_iso3": "JPN", "name": "Japan"}, "profile_type": "PLAYER"}})
    assert profile["bwf_profile_id"] == "58240"
    assert profile["country_code"] == "JPN"
    assert profile["bwf_nationality_code"] == "JPN"
    assert str(profile["date_of_birth"]) == "1997-06-13"


def test_unique_exact_profile_is_automatic_confirmation() -> None:
    alias = PlayerAlias(id="alias-1", source_id="historical", alias_text="YUTA WATANABE", normalized_alias="YUTA WATANABE")
    player = Player(id="player-1", full_name="Yuta Watanabe", country_code="JPN")
    decision = decide_alias(alias, player, profile_snapshot(), exact_candidate_count=1)
    assert decision[0] == "CONFIRMED_AUTO"
    assert decision[1] == "UNIQUE_EXACT_NAME"
    assert decision[2] == 80


def test_observed_bold_search_candidate_can_pass_country_consistency() -> None:
    alias = PlayerAlias(id="alias-1", source_id="historical", alias_text="JOO Eun Ae", normalized_alias="JOO EUN AE")
    player = Player(id="player-1", full_name="JOO Eun Ae", country_code="KOR")
    decision = decide_alias(alias, player, profile_snapshot(name="JOO Eun Ae", country="KOR"), exact_candidate_count=1, search_country_code="KOR")
    assert decision[0] == "CONFIRMED_AUTO"


def test_bwf_malaysia_nationality_matches_search_while_iso_metadata_differs() -> None:
    alias = PlayerAlias(id="alias-1", source_id="historical", alias_text="LIEW Daren", normalized_alias="LIEW DAREN")
    player = Player(id="player-1", full_name="LIEW Daren", country_code="MYS")
    decision = decide_alias(
        alias, player, profile_snapshot(name="LIEW Daren", country="MYS", nationality="MAS"),
        exact_candidate_count=1, search_country_code="MAS",
    )
    assert decision[0] == "CONFIRMED_AUTO"
    assert decision[3]["official_profile_bwf_nationality_code"] == "MAS"
    assert decision[3]["official_country_iso3_code"] == "MYS"


def test_bwf_chinese_taipei_nationality_matches_search_while_iso_metadata_differs() -> None:
    alias = PlayerAlias(id="alias-1", source_id="historical", alias_text="CHOU Tien Chen", normalized_alias="CHOU TIEN CHEN")
    player = Player(id="player-1", full_name="CHOU Tien Chen", country_code="TWN")
    decision = decide_alias(
        alias, player, profile_snapshot(name="CHOU Tien Chen", country="TWN", nationality="TPE"),
        exact_candidate_count=1, search_country_code="TPE",
    )
    assert decision[0] == "CONFIRMED_AUTO"
    assert decision[3]["official_profile_bwf_nationality_code"] == "TPE"
    assert decision[3]["official_country_iso3_code"] == "TWN"


def test_country_mismatch_is_conflicted_and_not_confirmed() -> None:
    alias = PlayerAlias(id="alias-1", source_id="historical", alias_text="YUTA WATANABE", normalized_alias="YUTA WATANABE")
    player = Player(id="player-1", full_name="Yuta Watanabe", country_code="JPN")
    decision = decide_alias(alias, player, profile_snapshot(nationality="JPN"), exact_candidate_count=1, search_country_code="THA")
    assert decision[0] == "CONFLICTED"
    assert decision[1] == "COUNTRY_MISMATCH"


def test_collision_is_conflicted_and_not_confirmed() -> None:
    alias = PlayerAlias(id="alias-1", source_id="historical", alias_text="YUTA WATANABE", normalized_alias="YUTA WATANABE")
    player = Player(id="player-1", full_name="Yuta Watanabe", country_code="JPN")
    decision = decide_alias(alias, player, profile_snapshot(), exact_candidate_count=2)
    assert decision[0] == "CONFLICTED"
    assert decision[1] == "MULTIPLE_CANDIDATES"


def test_name_mismatch_cannot_be_linked() -> None:
    alias = PlayerAlias(id="alias-1", source_id="historical", alias_text="YUTA WATANABE", normalized_alias="YUTA WATANABE")
    player = Player(id="player-1", full_name="Kento Momota", country_code="JPN")
    assert decide_alias(alias, player, profile_snapshot(name="Kento Momota"), 1)[0] == "UNRESOLVED"


def test_disabled_profile_source_gate_fails_before_network() -> None:
    with pytest.raises(RuntimeError, match="disabled"):
        ensure_collection_allowed(Settings())


def test_permission_gate_requires_reference_when_enabled() -> None:
    with pytest.raises(ValueError, match="PERMISSION_REFERENCE"):
        Settings(bwf_player_profiles_enabled=True, bwf_player_profiles_allow_live_source=True)


def test_access_denial_stops_without_retrying() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(403, request=request, json={"detail": "denied"}))
    client = BWFPlayerProfileClient(enabled_settings(), httpx.Client(base_url="https://example.test", transport=transport))
    with pytest.raises(SourceAccessStopped, match="HTTP 403"):
        client.search("YUTA WATANABE")


def test_only_two_fixed_endpoint_methods_are_exposed() -> None:
    assert not hasattr(BWFPlayerProfileClient, "get_url")
    assert set(name for name in dir(BWFPlayerProfileClient) if not name.startswith("_")) >= {"search", "summary", "close"}


def test_identity_selector_reads_context_without_historical_import_or_match_mutation_symbols() -> None:
    import app.ingestion.player_profiles.service as service
    assert hasattr(service, "Match")
    assert not hasattr(service, "MatchGame")
    assert not hasattr(service, "import_historical_seed")


def test_youth_profile_type_is_preserved() -> None:
    profile = extract_profile({"results": {"id": 1, "name_display": "Junior Player", "country_model": {"code_iso3": "MAS"}, "profile_type": "JUNIOR"}})
    assert profile["profile_type"] == "JUNIOR"


def test_upstream_server_error_stops_collection_without_retrying() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(500, request=request, json={"detail": "upstream error"}))
    client = BWFPlayerProfileClient(enabled_settings(), httpx.Client(base_url="https://example.test", transport=transport))
    with pytest.raises(SourceAccessStopped, match="HTTP 500") as captured:
        client.search("YU Yang (F)")
    assert captured.value.endpoint_key == "h2h-player-search"
    assert captured.value.status_code == 500


def test_unresolved_queue_checkpoints_and_releases_session_state(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.ingestion.player_profiles.service as player_profile_service

    class NoMatchClient:
        def search(self, alias_text: str) -> SourceResponse:
            return SourceResponse("h2h-player-search", f"https://example.test/search?query={alias_text}", 200, [])

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            historical = DataSource(code="HISTORICAL_CHUNK_TEST", source_kind="HISTORICAL_SEED", display_name="Historical chunk test", base_url=None)
            session.add(historical)
            session.flush()
            aliases = []
            for index in range(3):
                alias = PlayerAlias(source_id=historical.id, alias_text=f"No Match {index}", normalized_alias=f"NO MATCH {index}")
                session.add(alias)
                session.flush()
                add_source_context(
                    session,
                    alias,
                    context_key=f"checkpoint-{index}",
                    tournament_name="Senior Continental Championships",
                    event_type="MS",
                )
                aliases.append(alias)
            session.commit()
            checkpoints: list[tuple[int, str]] = []

            def fake_checkpoint(active_session: Session, summary: dict[str, int], *, reason: str) -> None:
                checkpoints.append((summary["selected"], reason))
                active_session.commit()
                active_session.expire_all()

            monkeypatch.setattr(player_profile_service, "checkpoint_batch_memory", fake_checkpoint)
            summary = run_full_queue(
                session,
                enabled_settings(bwf_player_profiles_batch_size=3, bwf_player_profiles_transaction_chunk_size=2),
                NoMatchClient(),
            )
            assert summary["selected"] == 3
            assert summary["unresolved"] == 3
            assert checkpoints == [(2, "chunk_complete"), (3, "batch_complete")]
            assert session.scalar(select(ReconciliationCase).where(
                ReconciliationCase.case_type == NO_EXACT_CANDIDATE_CASE_TYPE,
                ReconciliationCase.status == "OPEN",
            )) is not None

            repeat_summary = run_full_queue(
                session,
                enabled_settings(bwf_player_profiles_batch_size=3, bwf_player_profiles_transaction_chunk_size=2),
                NoMatchClient(),
            )
            assert repeat_summary["selected"] == 0
            assert repeat_summary["unresolved"] == 0
    finally:
        Base.metadata.drop_all(engine)


def test_coverage_separates_terminal_no_candidate_cases_from_eligible_queue() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            historical = DataSource(code="HISTORICAL_COVERAGE_TEST", source_kind="HISTORICAL_SEED", display_name="Historical coverage test", base_url=None)
            session.add(historical)
            session.flush()
            no_candidate = PlayerAlias(source_id=historical.id, alias_text="No Candidate", normalized_alias="NO CANDIDATE")
            still_eligible = PlayerAlias(source_id=historical.id, alias_text="Still Eligible", normalized_alias="STILL ELIGIBLE")
            session.add_all((no_candidate, still_eligible))
            session.flush()
            session.add(ReconciliationCase(
                case_type=NO_EXACT_CANDIDATE_CASE_TYPE,
                status="OPEN",
                candidate_entity_type="PLAYER_ALIAS",
                candidate_entity_id=no_candidate.id,
                rationale="Official search returned no exact candidate.",
            ))
            session.commit()

            coverage = identity_coverage(session)["data"]
            assert coverage["aliases_no_exact_candidate"] == 1
            assert coverage["eligible_queue_remaining"] == 1
            assert coverage["queue_complete"] is False
    finally:
        Base.metadata.drop_all(engine)


def test_server_error_is_persisted_as_skipped_exception_without_raising() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            historical = DataSource(code="HISTORICAL_TEST", source_kind="HISTORICAL_SEED", display_name="Historical test", base_url=None)
            session.add(historical)
            session.flush()
            alias = PlayerAlias(source_id=historical.id, alias_text="YU Yang (F)", normalized_alias="YU YANG F")
            session.add(alias)
            session.flush()
            add_source_context(
                session,
                alias,
                context_key="source-error",
                tournament_name="Senior Continental Championships",
                event_type="MS",
            )
            session.commit()
            transport = httpx.MockTransport(lambda request: httpx.Response(500, request=request, json={"detail": "upstream error"}))
            client = BWFPlayerProfileClient(enabled_settings(), httpx.Client(base_url="https://example.test", transport=transport))
            summary = run_full_queue(session, enabled_settings(), client)
            session.commit()
            assert summary["selected"] == 1
            assert summary["errors"] == 1
            assert summary["source_stopped"] == 1
            assert session.scalar(select(ImportBatch.status)) == "FAILED"
            case = session.scalar(select(ReconciliationCase).where(ReconciliationCase.case_type == "PLAYER_IDENTITY_SOURCE_ERROR"))
            assert case is not None
            assert case.candidate_entity_type == "PLAYER_ALIAS"
    finally:
        Base.metadata.drop_all(engine)


def add_source_context(
    session: Session,
    alias: PlayerAlias,
    *,
    context_key: str,
    tournament_name: str,
    event_type: str,
    match_date: date | None = None,
    match_status: str = "COMPLETED",
) -> None:
    """Create one stored context using the historical importer relationship shape."""
    participant = Participant(
        participant_kind="SINGLES",
        canonical_member_hash=f"participant-{context_key}",
        display_name=alias.alias_text,
    )
    session.add(participant)
    session.flush()
    session.add(
        ParticipantMember(
            participant_id=participant.id,
            member_order=1,
            source_alias_id=alias.id,
            source_alias_text=alias.alias_text,
        )
    )
    tournament = Tournament(name=tournament_name, source_name_raw=tournament_name, status="COMPLETED")
    session.add(tournament)
    session.flush()
    event = Event(tournament_id=tournament.id, event_type=event_type)
    session.add(event)
    session.flush()
    match = Match(
        source_match_key=f"context-{context_key}",
        tournament_id=tournament.id,
        event_id=event.id,
        participant_1_id=participant.id,
        match_date=match_date or date.today(),
        status=match_status,
        completion_basis="TEST_CONTEXT",
        source_completeness="COMPLETE",
        historical_seed_flag=True,
    )
    session.add(match)
    session.flush()
    session.add(MatchParticipantContext(match_id=match.id, participant_id=participant.id, side=1))
    session.flush()


def test_identity_queue_requires_a_recoverable_senior_non_para_source_context() -> None:
    class RecordingNoMatchClient:
        def __init__(self) -> None:
            self.search_calls: list[str] = []

        def search(self, alias_text: str) -> SourceResponse:
            self.search_calls.append(alias_text)
            return SourceResponse("h2h-player-search", f"https://example.test/search?query={alias_text}", 200, [])

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            historical = DataSource(
                code="HISTORICAL_CONTEXT_TEST",
                source_kind="HISTORICAL_SEED",
                display_name="Historical context test",
                base_url=None,
            )
            session.add(historical)
            session.flush()
            senior = PlayerAlias(source_id=historical.id, alias_text="Senior Alias", normalized_alias="SENIOR ALIAS")
            mixed = PlayerAlias(source_id=historical.id, alias_text="Mixed Alias", normalized_alias="MIXED ALIAS")
            junior = PlayerAlias(source_id=historical.id, alias_text="Junior Alias", normalized_alias="JUNIOR ALIAS")
            para = PlayerAlias(source_id=historical.id, alias_text="Para Alias", normalized_alias="PARA ALIAS")
            contextless = PlayerAlias(source_id=historical.id, alias_text="Contextless Alias", normalized_alias="CONTEXTLESS ALIAS")
            session.add_all((senior, mixed, junior, para, contextless))
            session.flush()
            add_source_context(session, senior, context_key="senior", tournament_name="Senior Continental Championships", event_type="MS")
            add_source_context(session, mixed, context_key="mixed-junior", tournament_name="European Junior Championships", event_type="WD-U19")
            add_source_context(session, mixed, context_key="mixed-senior", tournament_name="Senior Continental Championships", event_type="MS")
            add_source_context(session, junior, context_key="junior", tournament_name="European Junior Championships", event_type="WD-U19")
            add_source_context(session, para, context_key="para", tournament_name="Para Badminton International", event_type="WH1")
            session.commit()

            assert context_summary_for_alias(session, senior).eligible_for_profile_search is True
            mixed_context = context_summary_for_alias(session, mixed)
            assert mixed_context.senior_contexts == 1
            assert mixed_context.recent_senior_participations == 1
            assert mixed_context.junior_contexts == 1
            assert mixed_context.para_contexts == 0
            assert mixed_context.unclassified_contexts == 0
            assert context_summary_for_alias(session, junior).eligible_for_profile_search is False
            assert context_summary_for_alias(session, para).eligible_for_profile_search is False
            assert context_summary_for_alias(session, contextless).eligible_for_profile_search is False

            client = RecordingNoMatchClient()
            summary = run_full_queue(
                session,
                enabled_settings(bwf_player_profiles_batch_size=5, bwf_player_profiles_transaction_chunk_size=1),
                client,
            )
            assert client.search_calls == ["Senior Alias", "Mixed Alias"]
            assert summary["selected"] == 5
            assert summary["unresolved"] == 2
            assert summary["no_senior_context"] == 3
            assert len(session.scalars(select(ReconciliationCase).where(
                ReconciliationCase.case_type == NO_SENIOR_CONTEXT_CASE_TYPE,
                ReconciliationCase.status == "OPEN",
            )).all()) == 3
            coverage = identity_coverage(session)["data"]
            assert coverage["aliases_no_senior_context"] == 3
            assert coverage["aliases_no_exact_candidate"] == 2
            assert coverage["eligible_queue_remaining"] == 0
            assert coverage["queue_complete"] is True
    finally:
        Base.metadata.drop_all(engine)


def test_identity_queue_requires_recent_completed_or_retired_senior_participation() -> None:
    class RecordingNoMatchClient:
        def __init__(self) -> None:
            self.search_calls: list[str] = []

        def search(self, alias_text: str) -> SourceResponse:
            self.search_calls.append(alias_text)
            return SourceResponse("h2h-player-search", f"https://example.test/search?query={alias_text}", 200, [])

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            historical = DataSource(
                code="HISTORICAL_ACTIVITY_TEST",
                source_kind="HISTORICAL_SEED",
                display_name="Historical activity test",
                base_url=None,
            )
            session.add(historical)
            session.flush()
            recent = PlayerAlias(source_id=historical.id, alias_text="Recent Completed", normalized_alias="RECENT COMPLETED")
            retired = PlayerAlias(source_id=historical.id, alias_text="Recent Retired", normalized_alias="RECENT RETIRED")
            stale = PlayerAlias(source_id=historical.id, alias_text="Stale Senior", normalized_alias="STALE SENIOR")
            scheduled = PlayerAlias(source_id=historical.id, alias_text="Scheduled Senior", normalized_alias="SCHEDULED SENIOR")
            session.add_all((recent, retired, stale, scheduled))
            session.flush()
            add_source_context(session, recent, context_key="recent-completed", tournament_name="Senior Continental Championships", event_type="MS", match_date=date.today())
            add_source_context(session, retired, context_key="recent-retired", tournament_name="Senior Continental Championships", event_type="WS", match_date=date.today() - timedelta(days=7), match_status="RETIRED")
            add_source_context(session, stale, context_key="stale", tournament_name="Senior Continental Championships", event_type="MS", match_date=date.today() - timedelta(weeks=52, days=1))
            add_source_context(session, scheduled, context_key="scheduled", tournament_name="Senior Continental Championships", event_type="MS", match_date=date.today(), match_status="SCHEDULED")
            session.commit()

            assert context_summary_for_alias(session, recent).activity_status == "ACTIVE_RECENT_OFFICIAL_PARTICIPATION"
            assert context_summary_for_alias(session, retired).eligible_for_profile_search is True
            assert context_summary_for_alias(session, stale).activity_status == "NOT_RECENTLY_ACTIVE"
            assert context_summary_for_alias(session, scheduled).activity_status == "NOT_RECENTLY_ACTIVE"

            client = RecordingNoMatchClient()
            summary = run_full_queue(
                session,
                enabled_settings(bwf_player_profiles_batch_size=4, bwf_player_profiles_transaction_chunk_size=1),
                client,
            )
            assert client.search_calls == ["Recent Completed", "Recent Retired"]
            assert summary["selected"] == 4
            assert summary["unresolved"] == 2
            assert summary["no_recent_senior_activity"] == 2
            assert len(session.scalars(select(ReconciliationCase).where(
                ReconciliationCase.case_type == NO_RECENT_SENIOR_ACTIVITY_CASE_TYPE,
                ReconciliationCase.status == "OPEN",
            )).all()) == 2
            coverage = identity_coverage(session)["data"]
            assert coverage["aliases_no_recent_senior_activity"] == 2
            assert coverage["eligible_queue_remaining"] == 0
    finally:
        Base.metadata.drop_all(engine)


def test_confirmed_player_activity_summary_requires_recent_senior_participation() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            historical = DataSource(
                code="HISTORICAL_PLAYER_ACTIVITY_TEST",
                source_kind="HISTORICAL_SEED",
                display_name="Historical player activity test",
                base_url=None,
            )
            active_player = Player(full_name="Active Player", identity_status="CONFIRMED")
            inactive_player = Player(full_name="Inactive Player", identity_status="CONFIRMED")
            session.add_all((historical, active_player, inactive_player))
            session.flush()
            active_alias = PlayerAlias(source_id=historical.id, player_id=active_player.id, alias_text="Active Player", normalized_alias="ACTIVE PLAYER", resolution_status="CONFIRMED")
            inactive_alias = PlayerAlias(source_id=historical.id, player_id=inactive_player.id, alias_text="Inactive Player", normalized_alias="INACTIVE PLAYER", resolution_status="CONFIRMED")
            session.add_all((active_alias, inactive_alias))
            session.flush()
            add_source_context(session, active_alias, context_key="active-player", tournament_name="Senior Continental Championships", event_type="MS", match_date=date.today())
            add_source_context(session, inactive_alias, context_key="inactive-player", tournament_name="Senior Continental Championships", event_type="MS", match_date=date.today() - timedelta(weeks=53))
            session.commit()

            assert context_summary_for_player(session, active_player).eligible_for_profile_search is True
            assert context_summary_for_player(session, inactive_player).activity_status == "NOT_RECENTLY_ACTIVE"
    finally:
        Base.metadata.drop_all(engine)


def test_local_classification_sweep_makes_no_bwf_requests_and_is_idempotent() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            historical = DataSource(
                code="HISTORICAL_LOCAL_SWEEP_TEST",
                source_kind="HISTORICAL_SEED",
                display_name="Historical local sweep test",
                base_url=None,
            )
            session.add(historical)
            session.flush()
            recent = PlayerAlias(source_id=historical.id, alias_text="Recent Eligible", normalized_alias="RECENT ELIGIBLE")
            stale = PlayerAlias(source_id=historical.id, alias_text="Stale Alias", normalized_alias="STALE ALIAS")
            junior = PlayerAlias(source_id=historical.id, alias_text="Junior Alias", normalized_alias="JUNIOR ALIAS")
            contextless = PlayerAlias(source_id=historical.id, alias_text="Contextless Alias", normalized_alias="CONTEXTLESS ALIAS")
            session.add_all((recent, stale, junior, contextless))
            session.flush()
            add_source_context(session, recent, context_key="sweep-recent", tournament_name="Senior Continental Championships", event_type="MS", match_date=date.today())
            add_source_context(session, stale, context_key="sweep-stale", tournament_name="Senior Continental Championships", event_type="WS", match_date=date.today() - timedelta(weeks=53))
            add_source_context(session, junior, context_key="sweep-junior", tournament_name="European Junior Championships", event_type="WD-U19", match_date=date.today())
            session.commit()

            summary = run_local_classification_sweep(session, batch_size=4)
            assert summary == {
                "selected": 4,
                "confirmed_auto": 0,
                "provisional": 0,
                "conflicted": 0,
                "unresolved": 0,
                "no_senior_context": 2,
                "no_recent_senior_activity": 1,
                "retained_recent_senior_candidates": 1,
                "skipped_terminal": 0,
                "bwf_requests_made": 0,
                "errors": 0,
                "source_stopped": 0,
            }
            assert len(session.scalars(select(ReconciliationCase).where(
                ReconciliationCase.case_type == RECENT_SENIOR_ELIGIBLE_CASE_TYPE,
            )).all()) == 1
            coverage = identity_coverage(session)["data"]
            assert coverage["aliases_no_senior_context"] == 2
            assert coverage["aliases_no_recent_senior_activity"] == 1
            assert coverage["aliases_recent_senior_eligible"] == 1
            assert coverage["local_classification_remaining"] == 0
            assert coverage["eligible_queue_remaining"] == 1

            repeat = run_local_classification_sweep(session, batch_size=4)
            assert repeat["selected"] == 0
            assert repeat["bwf_requests_made"] == 0
    finally:
        Base.metadata.drop_all(engine)
