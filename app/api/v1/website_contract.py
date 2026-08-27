"""Typed, read-only contract for a first-party website integration.

This contract is intentionally separate from the generic v1 payloads.  It provides the
related participant, tournament, event, score, and provenance context needed by a
website without forcing browser clients to fan out across internal UUID endpoints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApiMeta(ContractModel):
    api_version: Literal["v1"] = "v1"
    contract_version: Literal["website-2026-08"] = "website-2026-08"
    timestamp: datetime
    source: str


class MemberSummary(ContractModel):
    id: str
    name: str
    country_code: str | None = None
    identity_status: str
    resolved_player_id: str | None = None


class ParticipantSummary(ContractModel):
    id: str
    kind: Literal["player", "pair"]
    display_name: str
    identity_status: str
    members: list[MemberSummary] = Field(max_length=2)


class TournamentSummary(ContractModel):
    id: str
    name: str
    location_raw: str | None = None
    country_code: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    status: str
    classification: str | None = None
    available_disciplines: list[str] = Field(default_factory=list)


class EventSummary(ContractModel):
    id: str
    tournament_id: str
    raw_type: str
    discipline: Literal["MS", "WS", "MD", "WD", "XD", "UNKNOWN"]
    competition_level: Literal["senior", "youth", "other"]
    category: str | None = None


class GameSummary(ContractModel):
    game_number: int = Field(ge=1, le=5)
    participant_1_score: int | None = Field(default=None, ge=0, le=30)
    participant_2_score: int | None = Field(default=None, ge=0, le=30)
    winner_participant_id: str | None = None
    status: str
    parse_confidence: str


class LiveStateSummary(ContractModel):
    game_number: int = Field(ge=1, le=5)
    participant_1_score: int = Field(ge=0, le=30)
    participant_2_score: int = Field(ge=0, le=30)
    observed_at: datetime
    source_observed_at: datetime | None = None
    match_status: str
    source_precision: Literal["SOURCE_TIME", "COLLECTION_TIME"]


class WebsiteMatch(ContractModel):
    id: str
    source_match_key: str
    match_date: str | None = None
    scheduled_time: datetime | None = None
    actual_start_time: datetime | None = None
    status: str
    normalized_status: Literal["scheduled", "live", "completed", "cancelled", "retired", "walkover", "unknown"]
    source_completeness: str
    historical_seed: bool
    tournament: TournamentSummary | None = None
    event: EventSummary | None = None
    round: str | None = None
    court: str | None = None
    participant_1: ParticipantSummary | None = None
    participant_2: ParticipantSummary | None = None
    winner_participant_id: str | None = None
    score_raw: str | None = None
    score_parse_status: str
    score_validation_status: str
    games: list[GameSummary] = Field(default_factory=list)
    latest_live_state: LiveStateSummary | None = None
    source_url: str | None = None


class PageInfo(ContractModel):
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)


class WebsiteMatchListResponse(ContractModel):
    data: list[WebsiteMatch]
    pagination: PageInfo
    meta: ApiMeta


class WebsiteMatchResponse(ContractModel):
    data: WebsiteMatch
    meta: ApiMeta


class WebsiteTournamentListResponse(ContractModel):
    data: list[TournamentSummary]
    pagination: PageInfo
    meta: ApiMeta


class WebsiteEventListResponse(ContractModel):
    data: list[EventSummary]
    meta: ApiMeta


class WebsitePlayer(ContractModel):
    id: str
    full_name: str
    country_code: str | None = None
    profile_url: str | None = None
    identity_status: str


class WebsitePlayerListResponse(ContractModel):
    data: list[WebsitePlayer]
    pagination: PageInfo
    meta: ApiMeta


class WebsiteRankingEntry(ContractModel):
    ranking_position: int = Field(ge=1)
    points: int | None = Field(default=None, ge=0)
    tournament_count: int | None = Field(default=None, ge=0)
    rank_change: int | None = None
    subject_kind: Literal["PLAYER", "PAIR"]
    subject_display_name: str
    official_subject_id: str | None = None
    country_code: str | None = None
    platform_player_id: str | None = None
    identity_status: str


class RankingSnapshotMeta(ContractModel):
    ranking_system: Literal["WORLD", "WORLD_TOUR", "WORLD_JUNIOR"]
    population: Literal["SENIOR", "JUNIOR_YOUTH"]
    discipline: Literal["MS", "WS", "MD", "WD", "XD"]
    effective_date: str
    published_week: str | None = None
    retrieved_at: datetime
    source_url: str
    content_hash: str
    snapshot_status: Literal["COMPLETE"]
    issue_summary: str | None = None


class WebsiteRankingListResponse(ContractModel):
    data: list[WebsiteRankingEntry]
    pagination: PageInfo
    snapshot: RankingSnapshotMeta | None = None
    issues: list[str] = Field(default_factory=list)
    meta: ApiMeta


class CapabilityResponse(ContractModel):
    data: dict[str, object]
    meta: ApiMeta


class CalendarProvenance(ContractModel):
    source_code: Literal["BWF_CORPORATE_CALENDAR"]
    snapshot_id: str
    source_url: str
    retrieved_at: datetime
    content_hash: str
    parser_version: str
    snapshot_status: str


class WebsiteCalendarEntry(ContractModel):
    id: str
    source_tournament_id: str
    name: str
    country_code: str | None = None
    city: str | None = None
    start_date: str
    end_date: str
    category: str | None = None
    event_url: str | None = None
    draw_date_text: str | None = None
    eligibility_status: Literal["ELIGIBLE"]
    eligibility_rationale: str
    provenance: CalendarProvenance


class WebsiteCalendarListResponse(ContractModel):
    data: list[WebsiteCalendarEntry]
    pagination: PageInfo
    meta: ApiMeta


class WebsiteDrawDocument(ContractModel):
    id: str
    calendar_entry_id: str
    source_url: str
    document_label: str
    retrieved_at: datetime
    content_hash: str
    content_type: str | None = None
    byte_size: int = Field(ge=0)
    parser_version: str
    parser_status: str
    parser_issue: str | None = None


class WebsiteDrawDocumentListResponse(ContractModel):
    data: list[WebsiteDrawDocument]
    meta: ApiMeta


class SeniorParticipantContract(ContractModel):
    id: str
    kind: Literal["player", "pair"]
    display_name: str
    member_ids: list[str] = Field(min_length=1, max_length=2)
    identity_status: Literal["CONFIRMED"]
    activity_status: Literal["ACTIVE_RECENT_OFFICIAL_PARTICIPATION"]
    recent_eligible_match_count: int = Field(ge=1)
    latest_eligible_match_date: str
    eligibility_rationale: str


class SeniorParticipantListResponse(ContractModel):
    data: list[SeniorParticipantContract]
    pagination: PageInfo
    meta: ApiMeta


class ContractAvailability(ContractModel):
    available: bool
    reason: str
    prerequisites: list[str]
    eligible_record_count: int = Field(ge=0)


class OfficialBracketNode(ContractModel):
    source_node_key: str
    round_label: str | None = None
    display_order: int = Field(ge=0)
    participant_1_label: str | None = None
    participant_2_label: str | None = None
    winner_label: str | None = None
    score_text: str | None = None
    reconciliation_status: str
    canonical_match_id: str | None = None


class OfficialBracketResponse(ContractModel):
    availability: ContractAvailability
    discipline: Literal["MS", "WS", "MD", "WD", "XD"]
    calendar_entry_id: str
    document_id: str | None = None
    topology_id: str | None = None
    data: list[OfficialBracketNode] = Field(default_factory=list)
    meta: ApiMeta


class ModelContractResponse(ContractModel):
    data: dict[str, ContractAvailability]
    meta: ApiMeta
