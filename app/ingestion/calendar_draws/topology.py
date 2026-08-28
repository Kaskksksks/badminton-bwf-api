"""Staged topology extraction for direct BWF draw PDFs.

This module accepts text extracted from an already captured direct BWF PDF. It never
retrieves documents, guesses endpoint URLs, resolves players by name, or changes a
public capability. Extraction can create only `PENDING_REVIEW` topology. A separate
explicit reconciliation step must map every source node to an existing canonical match
before a topology becomes `VALIDATED_RECONCILED` and therefore public.
"""

from __future__ import annotations

from io import BytesIO
import re

from pypdf import PdfReader
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Match,
    OfficialDrawNode,
    OfficialDrawNodeReconciliation,
    OfficialDrawTopology,
    OfficialTournamentDocument,
)
from app.ingestion.calendar_draws.client import is_allowed_draw_document_url

SUPPORTED_DISCIPLINES = {"MS", "WS", "MD", "WD", "XD"}
DISCIPLINE_HEADINGS = {
    "MS": {"MS", "MEN'S SINGLES", "MENS SINGLES", "MEN SINGLES"},
    "WS": {"WS", "WOMEN'S SINGLES", "WOMENS SINGLES", "WOMEN SINGLES"},
    "MD": {"MD", "MEN'S DOUBLES", "MENS DOUBLES", "MEN DOUBLES"},
    "WD": {"WD", "WOMEN'S DOUBLES", "WOMENS DOUBLES", "WOMEN DOUBLES"},
    "XD": {"XD", "MIXED DOUBLES"},
}
PARSER_VERSION = "bwf-direct-draw-topology-v1"
ROUND_PATTERN = re.compile(r"^(?:round\s+of\s+)?(?:128|64|32|16|8|4)|quarter[- ]?final|semi[- ]?final|final$", re.IGNORECASE)
PAIR_PATTERN = re.compile(r"^(?P<left>.+?)\s+(?:v(?:s\.?)?|–|—|-|\|)\s+(?P<right>.+?)$", re.IGNORECASE)
TABLE_ENTRY_PATTERN = re.compile(
    r"^\s*(?:(?P<position>\d+)\s+)?(?P<member_id>\d{4,})\s+(?P<country>[A-Z]{3})\s+(?P<label>.+?)\s*$"
)
PYPDF_POSITION_PATTERN = re.compile(r"^\s*(?P<position>\d+)\s+(?P<member_id>\d{4,})(?:\s+(?P<country>[A-Z]{3}))?\s*$")
PYPDF_POSITION_ONLY_PATTERN = re.compile(r"^\s*(?P<position>\d+)\s*$")
PYPDF_MEMBER_ID_PATTERN = re.compile(r"^\s*\d{4,}\s*$")
PYPDF_COUNTRY_PATTERN = re.compile(r"^\s*[A-Z]{3}\s*$")
PYPDF_LATER_ROUND_PATTERN = re.compile(r"^(?:Round\s+2|Quarterfinals|Semifinals|Final)$", re.IGNORECASE)
PYPDF_BYE_PATTERN = re.compile(r"^bye(?:\s+\d+)?$", re.IGNORECASE)


@dataclass(frozen=True)
class ExtractedDrawNode:
    source_node_key: str
    round_label: str
    display_order: int
    participant_1_label: str
    participant_2_label: str


def extract_direct_draw_text(pdf_bytes: bytes) -> str:
    """Extract text from captured PDF bytes; never fetches or accepts a remote target."""
    if not pdf_bytes.startswith(b"%PDF"):
        raise ValueError("Draw document is not a PDF")
    reader = PdfReader(BytesIO(pdf_bytes), strict=False)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def discipline_sections(extracted_text: str) -> dict[str, str]:
    """Split text only on explicit, standalone discipline headings."""
    heading_to_discipline = {heading: discipline for discipline, headings in DISCIPLINE_HEADINGS.items() for heading in headings}
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in extracted_text.splitlines():
        normalized = " ".join(raw_line.upper().replace("–", " ").split()).strip(" :.-")
        if normalized in heading_to_discipline:
            current = heading_to_discipline[normalized]
            sections.setdefault(current, [])
            continue
        if current:
            sections[current].append(raw_line)
    return {discipline: "\n".join(lines) for discipline, lines in sections.items()}


def parse_direct_draw_text(extracted_text: str, *, discipline: str) -> list[ExtractedDrawNode]:
    """Produce review-only candidate nodes from a direct-PDF text extraction.

    Text must already originate from one captured direct document. The method does not
    identify a winner, infer advancement, repair line breaks, or treat a visual layout
    as a definitive bracket. A zero-node result is a valid parser outcome and remains
    unavailable to the public contract.
    """

    if discipline not in SUPPORTED_DISCIPLINES:
        raise ValueError("Unsupported official draw discipline")
    nodes: list[ExtractedDrawNode] = []
    current_round = "Unlabelled source round"
    for raw_line in extracted_text.splitlines():
        line = " ".join(raw_line.split())
        if not line:
            continue
        if ROUND_PATTERN.fullmatch(line):
            current_round = line
            continue
        match = PAIR_PATTERN.fullmatch(line)
        if not match:
            continue
        left, right = match.group("left").strip(), match.group("right").strip()
        if len(left) < 2 or len(right) < 2 or left.casefold() == right.casefold() or not re.search(r"[A-Za-z]", left) or not re.search(r"[A-Za-z]", right):
            continue
        nodes.append(
            ExtractedDrawNode(
                source_node_key=f"{discipline}:{len(nodes) + 1}",
                round_label=current_round,
                display_order=len(nodes),
                participant_1_label=left,
                participant_2_label=right,
            )
        )
    if nodes:
        return nodes
    return parse_table_draw_text(extracted_text, discipline=discipline)


def _table_entries(extracted_text: str) -> list[tuple[int | None, str]]:
    entries: list[tuple[int | None, str]] = []
    for raw_line in extracted_text.splitlines():
        match = TABLE_ENTRY_PATTERN.fullmatch(raw_line)
        if not match:
            continue
        position = int(match.group("position")) if match.group("position") else None
        label = match.group("label").strip()
        if len(label) >= 2:
            entries.append((position, label))
    return entries


def parse_table_draw_text(extracted_text: str, *, discipline: str) -> list[ExtractedDrawNode]:
    """Stage Round 1 candidates from the explicit numbered roster table in a direct BWF PDF.

    This recognises only ordered source rows, retains the source labels, and creates no winner
    or advancement claims. It intentionally returns no candidates if the numbered positions are
    incomplete or ambiguous. The resulting nodes remain ``PENDING_REVIEW`` until each receives
    an explicit canonical-match reconciliation decision.
    """

    pypdf_participants = _pypdf_table_participants(extracted_text, discipline=discipline)
    if pypdf_participants:
        return _round_one_candidate_nodes(pypdf_participants, discipline=discipline)
    entries = _table_entries(extracted_text)
    participants: list[str] = []
    if discipline in {"MS", "WS"}:
        numbered = [(position, label) for position, label in entries if position is not None]
        if not numbered or [position for position, _ in numbered] != list(range(1, len(numbered) + 1)):
            return []
        participants = [label for _, label in numbered]
    else:
        current_members: list[str] = []
        expected_position = 1
        for position, label in entries:
            current_members.append(label)
            if position is None:
                continue
            if position != expected_position or len(current_members) != 2:
                return []
            participants.append(" / ".join(current_members))
            current_members = []
            expected_position += 1
        if current_members or not participants:
            return []
    return _round_one_candidate_nodes(participants, discipline=discipline)


def _round_one_candidate_nodes(participants: list[str], *, discipline: str) -> list[ExtractedDrawNode]:
    if len(participants) < 2 or len(participants) % 2:
        return []
    return [
        ExtractedDrawNode(
            source_node_key=f"{discipline}:table-round-1:{index // 2 + 1}",
            round_label="Round 1 (source table)",
            display_order=index // 2,
            participant_1_label=participants[index],
            participant_2_label=participants[index + 1],
        )
        for index in range(0, len(participants), 2)
    ]


def _pypdf_table_participants(extracted_text: str, *, discipline: str) -> list[str]:
    """Read the source roster structure emitted by pypdf for BWF’s visual draw tables.

    pypdf extracts visual columns as separate lines: a numbered member-id anchor, optional
    second member id and country lines, then the display name(s). No names are joined across
    positions. Candidates are rejected unless every source position is continuous from one.
    """

    expected_member_count = 1 if discipline in {"MS", "WS"} else 2
    blocks: list[tuple[int, list[str]]] = []
    current_position: int | None = None
    current_lines: list[str] = []
    for raw_line in extracted_text.splitlines():
        line = raw_line.strip()
        if current_position is not None and PYPDF_LATER_ROUND_PATTERN.fullmatch(line):
            break
        position_match = PYPDF_POSITION_PATTERN.fullmatch(line)
        if position_match:
            if current_position is not None:
                blocks.append((current_position, current_lines))
            current_position = int(position_match.group("position"))
            current_lines = []
            continue
        position_only_match = PYPDF_POSITION_ONLY_PATTERN.fullmatch(line)
        if position_only_match and int(position_only_match.group("position")) <= 128:
            if current_position is not None:
                blocks.append((current_position, current_lines))
            current_position = int(position_only_match.group("position"))
            current_lines = []
            continue
        if current_position is not None:
            current_lines.append(line)
    if current_position is not None:
        blocks.append((current_position, current_lines))
    if not blocks or [position for position, _ in blocks] != list(range(1, len(blocks) + 1)):
        return []
    participants: list[str] = []
    for _, lines in blocks:
        names = [
            line for line in lines
            if line and not PYPDF_MEMBER_ID_PATTERN.fullmatch(line) and not PYPDF_COUNTRY_PATTERN.fullmatch(line)
        ]
        if len(names) == 1 and PYPDF_BYE_PATTERN.fullmatch(names[0]):
            participants.append("BYE")
            continue
        if len(names) != expected_member_count:
            return []
        participants.append(" / ".join(names))
    return participants


def stage_topology_from_extracted_text(
    session: Session,
    *,
    document_id: str,
    discipline: str,
    source_content_hash: str,
    extracted_text: str,
) -> OfficialDrawTopology:
    """Persist a review-only candidate under a supplied source-content hash.

    The direct-PDF URL and immutable content hash are rechecked before any candidate
    node is staged. The caller must supply extraction from that exact content hash.
    """

    document = session.get(OfficialTournamentDocument, document_id)
    if document is None:
        raise ValueError("Official draw document not found")
    if not is_allowed_draw_document_url(document.source_url):
        raise ValueError("Document is outside the authorised direct BWF draw boundary")
    if document.content_hash != source_content_hash:
        raise ValueError("Extracted text does not match the captured official document hash")
    if discipline not in SUPPORTED_DISCIPLINES:
        raise ValueError("Unsupported official draw discipline")
    existing = session.scalar(
        select(OfficialDrawTopology).where(
            OfficialDrawTopology.document_id == document.id,
            OfficialDrawTopology.discipline == discipline,
            OfficialDrawTopology.parser_version == PARSER_VERSION,
        )
    )
    if existing:
        return existing
    topology = OfficialDrawTopology(
        document_id=document.id,
        discipline=discipline,
        topology_status="PENDING_REVIEW",
        source_content_hash=source_content_hash,
        parser_version=PARSER_VERSION,
        parsed_at=datetime.now(timezone.utc),
        parser_issue="Candidate extraction requires human review and canonical-match reconciliation before publication.",
    )
    session.add(topology)
    session.flush()
    for candidate in parse_direct_draw_text(extracted_text, discipline=discipline):
        session.add(
            OfficialDrawNode(
                topology_id=topology.id,
                source_node_key=candidate.source_node_key,
                round_label=candidate.round_label,
                display_order=candidate.display_order,
                participant_1_label=candidate.participant_1_label,
                participant_2_label=candidate.participant_2_label,
            )
        )
    session.flush()
    return topology


def record_canonical_reconciliation(
    session: Session,
    *,
    node_id: str,
    match_id: str,
    rationale: str,
) -> OfficialDrawNodeReconciliation:
    """Store an explicit review decision; no name-based automatic matching is permitted."""

    node = session.get(OfficialDrawNode, node_id)
    match = session.get(Match, match_id)
    if node is None or match is None:
        raise ValueError("A source node and canonical match are both required")
    if not rationale.strip():
        raise ValueError("An auditable reconciliation rationale is required")
    existing = session.scalar(
        select(OfficialDrawNodeReconciliation).where(
            OfficialDrawNodeReconciliation.node_id == node_id,
            OfficialDrawNodeReconciliation.match_id == match_id,
        )
    )
    if existing:
        return existing
    record = OfficialDrawNodeReconciliation(
        node_id=node_id,
        match_id=match_id,
        reconciliation_status="CANONICAL",
        confidence="REVIEWED_SOURCE_MATCH",
        rationale=rationale.strip(),
    )
    session.add(record)
    session.flush()
    return record


def publish_topology_after_full_reconciliation(session: Session, *, topology_id: str, review_note: str) -> OfficialDrawTopology:
    """Permit publication only when every candidate node has an explicit canonical match link."""

    topology = session.get(OfficialDrawTopology, topology_id)
    if topology is None:
        raise ValueError("Official draw topology not found")
    nodes = session.scalars(select(OfficialDrawNode).where(OfficialDrawNode.topology_id == topology_id)).all()
    reconciliations = session.scalars(select(OfficialDrawNodeReconciliation).where(OfficialDrawNodeReconciliation.node_id.in_([node.id for node in nodes]))).all() if nodes else []
    if not nodes or len({item.node_id for item in reconciliations}) != len(nodes) or any(item.reconciliation_status != "CANONICAL" for item in reconciliations):
        raise ValueError("All extracted official draw nodes require canonical reconciliation before publication")
    if not review_note.strip():
        raise ValueError("A reviewer note is required before publication")
    topology.topology_status = "VALIDATED_RECONCILED"
    topology.parser_issue = review_note.strip()
    session.flush()
    return topology
