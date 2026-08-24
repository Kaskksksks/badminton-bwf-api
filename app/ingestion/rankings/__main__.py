from __future__ import annotations

import argparse
import json

from app.core.config import get_settings
from app.db.base import SessionLocal
from app.ingestion.rankings.service import synchronize_rankings


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the authorised BWF rankings synchronisation once.")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and validate only; roll back all database writes.")
    args = parser.parse_args()
    settings = get_settings()
    with SessionLocal() as session:
        try:
            result = synchronize_rankings(session, settings=settings)
            if args.dry_run:
                session.rollback()
                result = {**result, "dry_run": True, "persisted": False}
            else:
                session.commit()
                result = {**result, "dry_run": False, "persisted": True}
            print(json.dumps(result, sort_keys=True))
            return 0
        except Exception:
            session.rollback()
            raise


if __name__ == "__main__":
    raise SystemExit(main())
