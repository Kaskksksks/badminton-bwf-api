from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from uuid import uuid4

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def uuid_str() -> str:
    return str(uuid4())


class SourceKind(str, Enum):
    HISTORICAL_SEED = "HISTORICAL_SEED"
    BWF_LIVE = "BWF_LIVE"
    BWF_RANKINGS = "BWF_RANKINGS"
    MANUAL = "MANUAL"


class BatchStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ValidationStatus(str, Enum):
    PENDING = "PENDING"
    VALID = "VALID"
    WARNING = "WARNING"
    INVALID = "INVALID"


class ReconciliationStatus(str, Enum):
    PENDING = "PENDING"
    CANONICAL = "CANONICAL"
    DUPLICATE_EXACT = "DUPLICATE_EXACT"
    CANDIDATE_DUPLICATE = "CANDIDATE_DUPLICATE"
    EXCLUDED = "EXCLUDED"
    CONFLICT = "CONFLICT"


class MatchStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    LIVE = "LIVE"
    COMPLETED = "COMPLETED"
    RETIRED = "RETIRED"
    WALKOVER = "WALKOVER"
    HISTORICAL_PARTIAL = "HISTORICAL_PARTIAL"
    POSTPONED = "POSTPONED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class ParticipantKind(str, Enum):
    SINGLES = "SINGLES"
    PAIR = "PAIR"


class IdentityStatus(str, Enum):
    UNRESOLVED = "UNRESOLVED"
    CONFIRMED = "CONFIRMED"
    CONFLICTED = "CONFLICTED"


class TimingBasis(str, Enum):
    SOURCE_EXACT = "SOURCE_EXACT"
    OBSERVATION_BOUND = "OBSERVATION_BOUND"
    DERIVED_APPROXIMATE = "DERIVED_APPROXIMATE"
    UNKNOWN = "UNKNOWN"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class UUIDMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)


class DataSource(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "data_sources"
    __table_args__ = (UniqueConstraint("code", name="data_sources_code"),)

    code: Mapped[str] = mapped_column(String(64), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(2048))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class DatasetVersion(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "dataset_versions"
    __table_args__ = (UniqueConstraint("source_id", "dataset_name", "dataset_version", name="dataset_versions_release"),)

    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), nullable=False, index=True)
    dataset_name: Mapped[str] = mapped_column(String(255), nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(128), nullable=False)
    coverage_start: Mapped[date | None] = mapped_column(Date)
    coverage_end: Mapped[date | None] = mapped_column(Date)
    manifest_hash: Mapped[str | None] = mapped_column(String(128))
    license_note: Mapped[str | None] = mapped_column(Text)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ImportBatch(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "import_batches"

    dataset_version_id: Mapped[str | None] = mapped_column(ForeignKey("dataset_versions.id"), index=True)
    batch_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=BatchStatus.PENDING.value, nullable=False, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    accepted_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    importer_version: Mapped[str] = mapped_column(String(64), nullable=False)
    error_summary: Mapped[str | None] = mapped_column(Text)


class SourceArtifact(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "source_artifacts"
    __table_args__ = (UniqueConstraint("import_batch_id", "logical_role", "sha256", name="source_artifacts_unique"),)

    dataset_version_id: Mapped[str | None] = mapped_column(ForeignKey("dataset_versions.id"), index=True)
    import_batch_id: Mapped[str | None] = mapped_column(ForeignKey("import_batches.id"), index=True)
    logical_role: Mapped[str] = mapped_column(String(128), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(1024), nullable=False)
    sha256: Mapped[str] = mapped_column(String(128), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    media_type: Mapped[str | None] = mapped_column(String(255))
    storage_uri: Mapped[str] = mapped_column(String(4096), nullable=False)
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StagedImportRecord(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "staged_import_records"
    __table_args__ = (UniqueConstraint("import_batch_id", "source_artifact_id", "source_row_number", name="staged_import_row"),)

    import_batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.id"), nullable=False, index=True)
    source_artifact_id: Mapped[str] = mapped_column(ForeignKey("source_artifacts.id"), nullable=False, index=True)
    source_row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_record_key: Mapped[str | None] = mapped_column(String(512), index=True)
    original_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    row_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    validation_status: Mapped[str] = mapped_column(String(32), default=ValidationStatus.PENDING.value, nullable=False, index=True)
    reconciliation_status: Mapped[str] = mapped_column(String(32), default=ReconciliationStatus.PENDING.value, nullable=False, index=True)
    validation_messages: Mapped[list] = mapped_column(JSON, default=list, nullable=False)


class RawIngestionRecord(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "raw_ingestion_records"

    import_batch_id: Mapped[str | None] = mapped_column(ForeignKey("import_batches.id"), index=True)
    source_artifact_id: Mapped[str | None] = mapped_column(ForeignKey("source_artifacts.id"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), nullable=False, index=True)
    endpoint_key: Mapped[str | None] = mapped_column(String(128))
    request_fingerprint: Mapped[str | None] = mapped_column(String(256))
    source_record_key: Mapped[str | None] = mapped_column(String(512), index=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    raw_payload: Mapped[dict | list | None] = mapped_column(JSON)
    payload_uri: Mapped[str | None] = mapped_column(String(4096))
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    reliability: Mapped[str | None] = mapped_column(String(64))
    processing_status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)


class ReconciliationCase(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "reconciliation_cases"

    import_batch_id: Mapped[str | None] = mapped_column(ForeignKey("import_batches.id"), index=True)
    case_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_record_id: Mapped[str | None] = mapped_column(ForeignKey("staged_import_records.id"), index=True)
    candidate_entity_type: Mapped[str | None] = mapped_column(String(64))
    candidate_entity_id: Mapped[str | None] = mapped_column(String(36), index=True)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[str | None] = mapped_column(String(255))


class RankingSnapshot(UUIDMixin, TimestampMixin, Base):
    """Immutable, source-versioned official ranking scope."""

    __tablename__ = "ranking_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "ranking_system", "discipline", "effective_date", "content_hash", name="ranking_snapshots_scope_hash"
        ),
        Index("ix_ranking_snapshots_scope_date", "ranking_system", "discipline", "effective_date"),
    )

    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), nullable=False, index=True)
    import_batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.id"), nullable=False, index=True)
    source_record_id: Mapped[str | None] = mapped_column(ForeignKey("raw_ingestion_records.id"), index=True)
    ranking_system: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    population: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    discipline: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    published_week: Mapped[str | None] = mapped_column(String(64))
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_status: Mapped[str] = mapped_column(String(32), nullable=False, default="COMPLETE")
    entry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    issue_summary: Mapped[str | None] = mapped_column(Text)


class RankingEntry(UUIDMixin, TimestampMixin, Base):
    """An official player or pair row as published inside one ranking snapshot."""

    __tablename__ = "ranking_entries"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "ranking_position", "subject_key", name="ranking_entries_snapshot_position_subject"),
        Index("ix_ranking_entries_snapshot_position", "snapshot_id", "ranking_position"),
        Index("ix_ranking_entries_official_id", "official_subject_id"),
    )

    snapshot_id: Mapped[str] = mapped_column(ForeignKey("ranking_snapshots.id"), nullable=False, index=True)
    ranking_position: Mapped[int] = mapped_column(Integer, nullable=False)
    points: Mapped[int | None] = mapped_column(Integer)
    tournament_count: Mapped[int | None] = mapped_column(Integer)
    rank_change: Mapped[int | None] = mapped_column(Integer)
    subject_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(512), nullable=False)
    subject_display_name: Mapped[str] = mapped_column(String(1024), nullable=False)
    official_subject_id: Mapped[str | None] = mapped_column(String(512))
    country_code: Mapped[str | None] = mapped_column(String(8))
    platform_player_id: Mapped[str | None] = mapped_column(ForeignKey("players.id"), index=True)
    identity_status: Mapped[str] = mapped_column(String(32), nullable=False, default=IdentityStatus.UNRESOLVED.value)
    source_payload: Mapped[dict] = mapped_column(JSON, nullable=False)


class Player(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "players"

    full_name: Mapped[str] = mapped_column(String(512), nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(255))
    last_name: Mapped[str | None] = mapped_column(String(255))
    country_code: Mapped[str | None] = mapped_column(String(8))
    country_name: Mapped[str | None] = mapped_column(String(255))
    gender: Mapped[str | None] = mapped_column(String(32))
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    profile_url: Mapped[str | None] = mapped_column(String(2048))
    identity_status: Mapped[str] = mapped_column(String(32), default=IdentityStatus.UNRESOLVED.value, nullable=False)
    last_identity_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourceEntityIdentifier(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "source_entity_identifiers"
    __table_args__ = (UniqueConstraint("source_id", "entity_type", "identifier_kind", "identifier_value", name="source_identifier"),)

    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    identifier_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    identifier_value: Mapped[str] = mapped_column(String(512), nullable=False)
    confidence: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_record_id: Mapped[str | None] = mapped_column(ForeignKey("raw_ingestion_records.id"))


class PlayerAlias(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "player_aliases"
    __table_args__ = (UniqueConstraint("source_id", "normalized_alias", "player_id", name="player_aliases_unique"),)

    player_id: Mapped[str | None] = mapped_column(ForeignKey("players.id"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), nullable=False, index=True)
    alias_text: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    evidence_record_id: Mapped[str | None] = mapped_column(ForeignKey("staged_import_records.id"))
    resolution_status: Mapped[str] = mapped_column(String(32), default=IdentityStatus.UNRESOLVED.value, nullable=False)


class Tournament(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "tournaments"

    name: Mapped[str] = mapped_column(String(512), nullable=False)
    source_name_raw: Mapped[str | None] = mapped_column(String(512))
    location_raw: Mapped[str | None] = mapped_column(String(512))
    country_code: Mapped[str | None] = mapped_column(String(8))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32), default="UNKNOWN", nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2048))


class TournamentAlias(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "tournament_aliases"
    __table_args__ = (UniqueConstraint("source_id", "normalized_title", "tournament_id", name="tournament_aliases_unique"),)

    tournament_id: Mapped[str | None] = mapped_column(ForeignKey("tournaments.id"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), nullable=False, index=True)
    raw_title: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    evidence_record_id: Mapped[str | None] = mapped_column(ForeignKey("staged_import_records.id"))
    resolution_status: Mapped[str] = mapped_column(String(32), default=IdentityStatus.UNRESOLVED.value, nullable=False)


class TournamentClassification(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "tournament_classifications"

    tournament_id: Mapped[str] = mapped_column(ForeignKey("tournaments.id"), nullable=False, index=True)
    raw_label: Mapped[str] = mapped_column(String(255), nullable=False)
    classification_system: Mapped[str] = mapped_column(String(128), nullable=False)
    normalized_class: Mapped[str | None] = mapped_column(String(255))
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    evidence_record_id: Mapped[str | None] = mapped_column(ForeignKey("staged_import_records.id"))


class Event(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("tournament_id", "event_type", name="events_tournament_type"),)

    tournament_id: Mapped[str] = mapped_column(ForeignKey("tournaments.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    category: Mapped[str | None] = mapped_column(String(255))
    source_event_id: Mapped[str | None] = mapped_column(String(255))


class Participant(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "participants"
    __table_args__ = (UniqueConstraint("participant_kind", "canonical_member_hash", name="participants_member_hash"),)

    participant_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    canonical_member_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(1024), nullable=False)
    identity_resolution_status: Mapped[str] = mapped_column(String(32), default=IdentityStatus.UNRESOLVED.value, nullable=False)


class ParticipantMember(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "participant_members"
    __table_args__ = (UniqueConstraint("participant_id", "member_order", name="participant_members_order"),)

    participant_id: Mapped[str] = mapped_column(ForeignKey("participants.id"), nullable=False, index=True)
    player_id: Mapped[str | None] = mapped_column(ForeignKey("players.id"), index=True)
    member_order: Mapped[int] = mapped_column(Integer, nullable=False)
    source_alias_text: Mapped[str | None] = mapped_column(String(512))
    source_alias_id: Mapped[str | None] = mapped_column(ForeignKey("player_aliases.id"))


class Match(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "matches"
    __table_args__ = (
        UniqueConstraint("source_match_key", name="matches_source_match_key"),
        Index("ix_matches_date_status", "match_date", "status"),
    )

    source_match_key: Mapped[str] = mapped_column(String(512), nullable=False)
    match_date: Mapped[date | None] = mapped_column(Date, index=True)
    tournament_id: Mapped[str | None] = mapped_column(ForeignKey("tournaments.id"), index=True)
    event_id: Mapped[str | None] = mapped_column(ForeignKey("events.id"), index=True)
    round_raw: Mapped[str | None] = mapped_column(String(255))
    court_code: Mapped[str | None] = mapped_column(String(64))
    court_name: Mapped[str | None] = mapped_column(String(255))
    scheduled_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default=MatchStatus.UNKNOWN.value, nullable=False, index=True)
    participant_1_id: Mapped[str | None] = mapped_column(ForeignKey("participants.id"), index=True)
    participant_2_id: Mapped[str | None] = mapped_column(ForeignKey("participants.id"), index=True)
    winner_participant_id: Mapped[str | None] = mapped_column(ForeignKey("participants.id"), index=True)
    winner_side_raw: Mapped[str | None] = mapped_column(String(8))
    best_of: Mapped[int | None] = mapped_column(Integer)
    match_duration_seconds: Mapped[int | None] = mapped_column(Integer)
    score_raw: Mapped[str | None] = mapped_column(String(1024))
    score_parse_status: Mapped[str] = mapped_column(String(64), default="UNKNOWN", nullable=False)
    score_validation_status: Mapped[str] = mapped_column(String(64), default="PENDING", nullable=False)
    completion_basis: Mapped[str] = mapped_column(String(64), nullable=False)
    source_completeness: Mapped[str] = mapped_column(String(64), default="UNKNOWN", nullable=False)
    historical_seed_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2048))


class MatchParticipantContext(UUIDMixin, Base):
    __tablename__ = "match_participant_context"
    __table_args__ = (UniqueConstraint("match_id", "side", name="match_participant_context_side"),)

    match_id: Mapped[str] = mapped_column(ForeignKey("matches.id"), nullable=False, index=True)
    participant_id: Mapped[str] = mapped_column(ForeignKey("participants.id"), nullable=False, index=True)
    side: Mapped[int] = mapped_column(Integer, nullable=False)
    is_home: Mapped[bool | None] = mapped_column(Boolean)
    source_record_id: Mapped[str | None] = mapped_column(ForeignKey("staged_import_records.id"))


class MatchGame(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "match_games"
    __table_args__ = (UniqueConstraint("match_id", "game_number", name="match_games_number"),)

    match_id: Mapped[str] = mapped_column(ForeignKey("matches.id"), nullable=False, index=True)
    game_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_game_number: Mapped[int | None] = mapped_column(Integer)
    participant_1_score: Mapped[int | None] = mapped_column(Integer)
    participant_2_score: Mapped[int | None] = mapped_column(Integer)
    winner_participant_id: Mapped[str | None] = mapped_column(ForeignKey("participants.id"))
    status: Mapped[str] = mapped_column(String(32), default=MatchStatus.UNKNOWN.value, nullable=False)
    parse_confidence: Mapped[str] = mapped_column(String(32), nullable=False)
    source_record_id: Mapped[str | None] = mapped_column(ForeignKey("staged_import_records.id"))


class ExcludedSourceRecord(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "excluded_source_records"

    source_record_id: Mapped[str | None] = mapped_column(ForeignKey("raw_ingestion_records.id"), index=True)
    source_artifact_id: Mapped[str | None] = mapped_column(ForeignKey("source_artifacts.id"), index=True)
    source_record_key: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    exclusion_code: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2048))


class RecordLineage(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "record_lineage"
    __table_args__ = (UniqueConstraint("source_record_id", "entity_type", "entity_id", "relationship_type", name="record_lineage_unique"),)

    source_record_id: Mapped[str] = mapped_column(ForeignKey("staged_import_records.id"), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    relationship_type: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class GameStateObservation(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "game_state_observations"
    __table_args__ = (UniqueConstraint("match_id", "game_number", "state_hash", name="game_state_observations_unique"),)

    match_id: Mapped[str] = mapped_column(ForeignKey("matches.id"), nullable=False, index=True)
    game_number: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    source_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    participant_1_score: Mapped[int] = mapped_column(Integer, nullable=False)
    participant_2_score: Mapped[int] = mapped_column(Integer, nullable=False)
    match_status: Mapped[str] = mapped_column(String(32), nullable=False)
    court_code: Mapped[str | None] = mapped_column(String(64))
    service_side: Mapped[int | None] = mapped_column(Integer)
    raw_record_id: Mapped[str] = mapped_column(ForeignKey("raw_ingestion_records.id"), nullable=False, index=True)
    state_hash: Mapped[str] = mapped_column(String(128), nullable=False)


class GameTimingFact(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "game_timing_facts"
    __table_args__ = (UniqueConstraint("game_id", name="game_timing_facts_game"),)

    game_id: Mapped[str] = mapped_column(ForeignKey("match_games.id"), nullable=False, index=True)
    game_start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    game_end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    per_game_time_seconds: Mapped[int | None] = mapped_column(Integer)
    timing_basis: Mapped[str] = mapped_column(String(32), default=TimingBasis.UNKNOWN.value, nullable=False)
    first_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evidence_record_id: Mapped[str | None] = mapped_column(ForeignKey("raw_ingestion_records.id"))


class GameIntervalAssessment(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "game_interval_assessments"
    __table_args__ = (UniqueConstraint("game_id", "interval_type", "derivation_version", name="game_interval_assessments_version"),)

    game_id: Mapped[str] = mapped_column(ForeignKey("match_games.id"), nullable=False, index=True)
    interval_type: Mapped[str] = mapped_column(String(64), nullable=False)
    interval_player_participant_id: Mapped[str | None] = mapped_column(ForeignKey("participants.id"))
    participant_1_score: Mapped[int | None] = mapped_column(Integer)
    participant_2_score: Mapped[int | None] = mapped_column(Integer)
    interval_source_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    interval_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    interval_exact: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    detection_method: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_observation_id: Mapped[str | None] = mapped_column(ForeignKey("game_state_observations.id"))
    derivation_version: Mapped[str] = mapped_column(String(64), nullable=False)


class GameStateDerivation(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "game_state_derivations"
    __table_args__ = (UniqueConstraint("game_id", "state_key", "derivation_name", "derivation_version", name="game_state_derivations_version"),)

    game_id: Mapped[str] = mapped_column(ForeignKey("match_games.id"), nullable=False, index=True)
    state_key: Mapped[str] = mapped_column(String(256), nullable=False)
    derivation_name: Mapped[str] = mapped_column(String(128), nullable=False)
    value_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    method: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[str] = mapped_column(String(32), nullable=False)
    source_observation_from_id: Mapped[str | None] = mapped_column(ForeignKey("game_state_observations.id"))
    source_observation_to_id: Mapped[str | None] = mapped_column(ForeignKey("game_state_observations.id"))
    derivation_version: Mapped[str] = mapped_column(String(64), nullable=False)


class StatisticRun(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "statistic_runs"

    scope: Mapped[str] = mapped_column(String(128), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    derivation_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    input_row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


# Relationships intentionally remain query-service based at v0.1. The schema is
# normalized while avoiding eager relationship graphs during high-volume ingestion.
