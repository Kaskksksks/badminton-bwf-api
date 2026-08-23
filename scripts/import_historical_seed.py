#!/usr/bin/env python3
"""Run the provenance-preserving historical seed import.

This command is intentionally explicit: it does not run automatically at API
startup and it refuses a malformed package root.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.config import get_settings
from app.db.base import Base, SessionLocal, engine
from app.db import models  # noqa: F401 - imports ORM metadata
from app.ingestion.seed_import.service import import_historical_seed


def main() -> None:
    parser = argparse.ArgumentParser(description="Import the approved historical badminton seed dataset")
    parser.add_argument("--dataset-root", type=Path, default=get_settings().seed_dataset_root)
    parser.add_argument("--create-tables", action="store_true", help="Create ORM tables for local development only")
    args = parser.parse_args()

    if args.create_tables:
        Base.metadata.create_all(bind=engine)
    with SessionLocal.begin() as session:
        batch = import_historical_seed(session, args.dataset_root)
        print(json.dumps({
            "batch_id": batch.id,
            "status": batch.status,
            "input_row_count": batch.input_row_count,
            "accepted_count": batch.accepted_count,
            "duplicate_count": batch.duplicate_count,
            "rejected_count": batch.rejected_count,
        }, indent=2))


if __name__ == "__main__":
    main()
