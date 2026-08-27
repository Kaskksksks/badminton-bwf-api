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
        if len(left) < 2 or len(right) < 2 or left.casefold() == right.casefold():
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
    return nodes


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
