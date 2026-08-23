#!/usr/bin/env python3
from __future__ import annotations

import json

from sqlalchemy import func, select

from app.db.base import SessionLocal
from app.db.models import ExcludedSourceRecord, ImportBatch, Match, RecordLineage, StagedImportRecord

with SessionLocal() as session:
    latest = session.scalar(select(ImportBatch).order_by(ImportBatch.completed_at.desc()))
    output = {
        "latest_batch": {
            "id": latest.id if latest else None,
            "status": latest.status if latest else None,
            "input_row_count": latest.input_row_count if latest else None,
            "accepted_count": latest.accepted_count if latest else None,
            "duplicate_count": latest.duplicate_count if latest else None,
            "rejected_count": latest.rejected_count if latest else None,
        },
        "staged_rows": session.scalar(select(func.count()).select_from(StagedImportRecord)),
        "canonical_matches": session.scalar(select(func.count()).select_from(Match)),
        "duplicate_lineage": session.scalar(select(func.count()).select_from(RecordLineage).where(RecordLineage.relationship_type == "DUPLICATE_EXACT")),
        "excluded_source_records": session.scalar(select(func.count()).select_from(ExcludedSourceRecord)),
    }
print(json.dumps(output, indent=2))
