from __future__ import annotations

from datetime import date, datetime, timezone
import re
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models import (
    DataSource,
    OfficialTournamentCalendarEntry,
    OfficialTournamentCalendarSnapshot,
    OfficialTournamentDocument,
    SourceKind,
)
from app.ingestion.approved_scope import classify_approved_senior_scope
from app.ingestion.calendar_draws.topology import discipline_sections, extract_direct_draw_text, parse_direct_draw_text, stage_topology_from_extracted_text
from app.ingestion.calendar_draws.client import (
    BWFCorporateCalendarClient,
    CalendarDocumentLink,
    CorporateCalendarEntry,
    parse_corporate_calendar_html,
)

PARSER_VERSION = "bwf-corporate-calendar-v1"
SOURCE_CODE = "BWF_CORPORATE_CALENDAR"
WORLD_TOUR_CATEGORY_PATTERN = re.compile(
    r"\bbwf\s+(?:world\s+tour|tour\s+super\s+100)\b", re.IGNORECASE
)
INDIVIDUAL_WORLD_CHAMPIONSHIPS_NAME_PATTERN = re.compile(
    r"\bbwf\s+world\s+championships\b", re.IGNORECASE
)
CONTINENTAL_INDIVIDUAL_CHAMPIONSHIPS_CATEGORY_PATTERN = re.compile(
    r"\bcontinental\s+individual\s+championships\b", re.IGNORECASE
)
MULTI_SPORT_GAMES_CATEGORY_PATTERN = re.compile(r"\bmulti-sport\s+games\b", re.IGNORECASE)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_calendar_source(session: Session, settings: Settings) -> DataSource:
    source = session.scalar(select(DataSource).where(DataSource.code == SOURCE_CODE))
    if source:
        return source
    source = DataSource(
        code=SOURCE_CODE,
        source_kind=SourceKind.BWF_CORPORATE_CALENDAR.value,
        display_name="BWF Corporate authorised calendar and direct draw documents",
        base_url="https://corporate.bwfbadminton.com/events/calendar/",
    )
    session.add(source)
    session.flush()
    return source


def is_allowed_target_competition(entry: CorporateCalendarEntry) -> bool:
    """Allow only the four user-approved senior calendar scopes.

    BWF Corporate labels Super 100 as ``BWF Tour Super 100`` while higher tiers
    carry the ``BWF World Tour`` label. The World Championships match is title-based
    and deliberately excludes team championships whose title is not the individual
    ``BWF World Championships`` title. The category matches admit the calendar's
    published Continental Individual Championships and Multi-Sport Games groups,
    which cover entries such as continental championships, the Olympics, and SEA Games.
    """
    category = entry.category or ""
    return bool(
        WORLD_TOUR_CATEGORY_PATTERN.search(category)
        or INDIVIDUAL_WORLD_CHAMPIONSHIPS_NAME_PATTERN.search(entry.name)
        or CONTINENTAL_INDIVIDUAL_CHAMPIONSHIPS_CATEGORY_PATTERN.search(category)
        or MULTI_SPORT_GAMES_CATEGORY_PATTERN.search(category)
    )


def eligibility_for_entry(entry: CorporateCalendarEntry) -> tuple[str, str]:
    payload = {"name": entry.name, "category": entry.category or ""}
    scope_status, scope_reason = classify_approved_senior_scope(payload)
    if scope_status != "ELIGIBLE":
        return scope_status, scope_reason
    if entry.start_date is None or entry.end_date is None:
        return "EXCLUDED_DATE_UNPARSEABLE", "Official calendar date range could not be parsed without guessing"
    return "ELIGIBLE", "Approved calendar category with a parseable official date range"


def in_draw_horizon(entry: CorporateCalendarEntry, *, today: date, horizon_days: int) -> bool:
    if entry.start_date is None:
        return False
    return 0 <= (entry.start_date - today).days <= horizon_days


def get_or_create_snapshot(
    session: Session,
    *,
    source: DataSource,
    source_url: str,
    content_hash: str,
    content_type: str | None,
    byte_size: int,
    retrieved_at: datetime,
) -> tuple[OfficialTournamentCalendarSnapshot, bool]:
    existing = session.scalar(
        select(OfficialTournamentCalendarSnapshot).where(
            OfficialTournamentCalendarSnapshot.source_id == source.id,
            OfficialTournamentCalendarSnapshot.content_hash == content_hash,
        )
    )
    if existing:
        return existing, False
    snapshot = OfficialTournamentCalendarSnapshot(
        source_id=source.id,
        source_url=source_url,
        retrieved_at=retrieved_at,
        content_hash=content_hash,
        content_type=content_type,
        byte_size=byte_size,
        parser_version=PARSER_VERSION,
        snapshot_status="CAPTURED",
        entry_count=0,
    )
    session.add(snapshot)
    session.flush()
    return snapshot, True


def get_or_create_entry(
    session: Session,
    *,
    snapshot: OfficialTournamentCalendarSnapshot,
    entry: CorporateCalendarEntry,
    eligibility_status: str,
    eligibility_rationale: str,
) -> OfficialTournamentCalendarEntry:
    existing = session.scalar(
        select(OfficialTournamentCalendarEntry).where(
            OfficialTournamentCalendarEntry.snapshot_id == snapshot.id,
            OfficialTournamentCalendarEntry.source_tournament_id == entry.source_tournament_id,
        )
    )
    if existing:
        return existing
    calendar_entry = OfficialTournamentCalendarEntry(
        snapshot_id=snapshot.id,
        source_tournament_id=entry.source_tournament_id,
        name=entry.name,
        country_code=entry.country_code,
        start_date=entry.start_date,
        end_date=entry.end_date,
        category=entry.category,
        city=entry.city,
        source_url=entry.source_url,
        draw_date_text=entry.draw_date_text,
        eligibility_status=eligibility_status,
        eligibility_rationale=eligibility_rationale,
        raw_payload=entry.raw_row,
    )
    session.add(calendar_entry)
    session.flush()
    return calendar_entry


def draw_was_already_captured(
    session: Session, *, source_url: str
) -> bool:
    return session.scalar(
        select(OfficialTournamentDocument.id).where(OfficialTournamentDocument.source_url == source_url).limit(1)
    ) is not None


def capture_draw_document(
    session: Session,
    *,
    calendar_entry: OfficialTournamentCalendarEntry,
    document: CalendarDocumentLink,
    client: BWFCorporateCalendarClient,
    settings: Settings | None = None,
) -> bool:
    """Retrieve one direct official draw PDF and store immutable metadata.

    When explicitly enabled, PDF text is extracted and discipline-specific candidate
    topologies are staged as review-required records. No automatic identity or canonical
    match reconciliation is performed here.
    """
    settings = settings or get_settings()
    response = client.fetch_draw_document(document.url)
    existing = session.scalar(
        select(OfficialTournamentDocument).where(
            OfficialTournamentDocument.calendar_entry_id == calendar_entry.id,
            OfficialTournamentDocument.content_hash == response.content_hash,
        )
    )
    if existing:
        return False
    stored = OfficialTournamentDocument(
        calendar_entry_id=calendar_entry.id,
        source_url=response.url,
        document_label=document.label,
        retrieved_at=response.retrieved_at,
        content_hash=response.content_hash,
        content_type=response.content_type,
        byte_size=len(response.content),
        parser_version=PARSER_VERSION,
        parser_status="CAPTURED_REVIEW_REQUIRED",
        parser_issue="Draw topology is not materialised until verified against authorised real-document fixtures.",
    )
    session.add(stored)
    session.flush()
    if settings.bwf_draw_parser_enabled:
        try:
            extracted_text = extract_direct_draw_text(response.content)
            sections = discipline_sections(extracted_text)
            staged = []
            for discipline, section_text in sections.items():
                if parse_direct_draw_text(section_text, discipline=discipline):
                    staged.append(stage_topology_from_extracted_text(
                        session,
                        document_id=stored.id,
                        discipline=discipline,
                        source_content_hash=response.content_hash,
                        extracted_text=section_text,
                    ))
            if staged:
                stored.parser_status = "PARSED_REVIEW_REQUIRED"
                stored.parser_issue = f"Staged {len(staged)} discipline topology candidate(s); explicit canonical reconciliation is still required."
            else:
                stored.parser_status = "PARSE_EMPTY"
                stored.parser_issue = "PDF text extraction produced no explicit discipline draw nodes."
        except Exception as exc:
            stored.parser_status = "PARSE_FAILED"
            stored.parser_issue = f"Direct-PDF parser failed safely: {exc}"
        session.flush()
    return True


def synchronize_corporate_calendar(
    session: Session,
    *,
    client: BWFCorporateCalendarClient | None = None,
    settings: Settings | None = None,
    today: date | None = None,
) -> dict[str, int | str]:
    """Synchronise one fixed authorised calendar page with bounded optional draw retrieval.

    This function persists only eligible senior/non-Para calendar entries. It does not
    create players, participant records, events, matches, or bracket topology.
    """
    settings = settings or get_settings()
    if not settings.bwf_calendar_enabled:
        return {"status": "disabled", "calendar_requests": 0, "draw_requests": 0}
    if settings.bwf_calendar_permission_required and not settings.bwf_calendar_permission_reference:
        raise ValueError("BWF Corporate calendar collection requires a configured permission reference")

    owns_client = client is None
    client = client or BWFCorporateCalendarClient(settings)
    today = today or date.today()
    try:
        response = client.fetch_calendar()
        source = get_calendar_source(session, settings)
        snapshot, snapshot_created = get_or_create_snapshot(
            session,
            source=source,
            source_url=response.url,
            content_hash=response.content_hash,
            content_type=response.content_type,
            byte_size=len(response.content),
            retrieved_at=response.retrieved_at,
        )
        entries = parse_corporate_calendar_html(response.content, expected_year=today.year)
        eligible_entries: list[tuple[CorporateCalendarEntry, OfficialTournamentCalendarEntry]] = []
        skipped_unparseable = 0
        skipped_non_target_senior = 0
        for entry in entries:
            eligibility_status, rationale = eligibility_for_entry(entry)
            if eligibility_status != "ELIGIBLE":
                if eligibility_status == "EXCLUDED_DATE_UNPARSEABLE":
                    skipped_unparseable += 1
                elif eligibility_status == "EXCLUDED_NON_TARGET_SENIOR":
                    skipped_non_target_senior += 1
                continue
            calendar_entry = get_or_create_entry(
                session,
                snapshot=snapshot,
                entry=entry,
                eligibility_status=eligibility_status,
                eligibility_rationale=rationale,
            )
            eligible_entries.append((entry, calendar_entry))
        if snapshot_created:
            snapshot.entry_count = len(eligible_entries)
            snapshot.snapshot_status = "PARSED"
            session.flush()

        draw_requests = 0
        draw_captured = 0
        for entry, calendar_entry in eligible_entries:
            if draw_requests >= settings.bwf_draw_document_max_per_run:
                break
            if not in_draw_horizon(entry, today=today, horizon_days=settings.bwf_draw_document_horizon_days):
                continue
            for document in entry.draw_documents:
                if draw_requests >= settings.bwf_draw_document_max_per_run:
                    break
                # Treat a direct official URL as the Phase 1 document identity. This
                # prevents unrelated calendar-page changes from repeatedly downloading
                # the same PDF; a newly published direct URL is captured as a new immutable
                # document version. Same-URL PDF revision detection is intentionally out
                # of scope until real-document parser validation is separately approved.
                if draw_was_already_captured(session, source_url=document.url):
                    continue
                draw_requests += 1
                if capture_draw_document(session, calendar_entry=calendar_entry, document=document, client=client, settings=settings):
                    draw_captured += 1

        return {
            "status": "ok",
            "calendar_requests": 1,
            "calendar_snapshot_created": int(snapshot_created),
            "calendar_entries_seen": len(entries),
            "calendar_entries_eligible": len(eligible_entries),
            "skipped_non_target_senior_calendar_entries": skipped_non_target_senior,
            "skipped_unparseable_target_calendar_entries": skipped_unparseable,
            "draw_requests": draw_requests,
            "draw_documents_captured": draw_captured,
        }
    finally:
        if owns_client:
            client.close()
