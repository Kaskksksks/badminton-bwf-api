from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models import Match, RecordLineage, StagedImportRecord
from app.ingestion.seed_import.service import import_historical_seed


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_seed(root: Path) -> None:
    rows = [
        "date,discipline,tournament,tier,round,host_location,team1,team2,winner,score,team1_at_home,team2_at_home",
        "2026-08-20,MS,Example Open,Super 300,R32,Example City,ALPHA ONE,BETA TWO,1,21-10 21-15,False,True",
        "2026-08-20,MS,Example Open,Super 300,R32,Example City,ALPHA ONE,BETA TWO,1,21-10 21-15,False,True",
        "2026-08-21,WD,Example Open,Super 300,R16,Example City,CHARLIE THREE / DELTA FOUR,ECHO FIVE / FOXTROT SIX,2,1-0,False,False",
    ]
    matches = root / "matches.csv"
    matches.write_text("\n".join(rows) + "\n", encoding="utf-8")
    manifest = {
        "dataset_name": "Test historical seed",
        "coverage_start": "2026-08-20",
        "coverage_end": "2026-08-22",
        "sha256": {"matches.csv": _digest(matches)},
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_seed_import_stages_every_row_and_preserves_exact_duplicate_lineage(tmp_path: Path) -> None:
    _build_seed(tmp_path)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    with session_factory.begin() as session:
        batch = import_historical_seed(session, tmp_path)
        assert batch.input_row_count == 3
        assert batch.accepted_count == 2
        assert batch.duplicate_count == 1
        assert batch.rejected_count == 0
        assert session.scalar(select(func.count()).select_from(StagedImportRecord)) == 3
        assert session.scalar(select(func.count()).select_from(Match)) == 2
        duplicate_links = session.scalars(select(RecordLineage).where(RecordLineage.relationship_type == "DUPLICATE_EXACT")).all()
        assert len(duplicate_links) == 1
        partial = session.scalar(select(Match).where(Match.score_raw == "1-0"))
        assert partial is not None
        assert partial.score_parse_status == "PARTIAL_OR_NONSTANDARD"
