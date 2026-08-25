"""Manual operator entry point for a bounded BWF player-profile identity batch."""
from __future__ import annotations

import json

from app.core.config import get_settings
from app.db.base import SessionLocal
from app.ingestion.player_profiles.service import run_full_queue


def main() -> None:
    settings = get_settings()
    with SessionLocal() as session:
        summary = run_full_queue(session, settings)
        session.commit()
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
