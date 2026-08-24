from __future__ import annotations

import argparse
import logging
import json
from pathlib import Path
import pandas as pd
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.base import SessionLocal
# Make sure this matches your service ingestion function or model insertion logic
from app.ingestion.adapters.bwf.service import process_and_store_matches

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def chunked_iterable(iterable, size):
    """Yield successive chunks from an iterable of a given size."""
    iterator = iter(iterable)
    while True:
        chunk = []
        try:
            for _ in range(size):
                chunk.append(next(iterator))
        except StopIteration:
            if chunk:
                yield chunk
            break
        if chunk:
            yield chunk


def import_historical_dataset(dataset_root: Path, batch_size: int = 2000) -> None:
    settings = get_settings()
    manifest_file = dataset_root / "manifest.json"
    matches_file = dataset_root / "matches.csv"

    if not manifest_file.exists():
        raise FileNotFoundError(f"Manifest file not found at {manifest_file}")
    if not matches_file.exists():
        raise FileNotFoundError(f"Matches CSV file not found at {matches_file}")

    logger.info(f"Loading manifest from {manifest_file}")
    with open(manifest_file, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    logger.info(f"Dataset: {manifest.get('dataset_name')}")
    logger.info(f"Total rows to import: {manifest.get('rows_total')}")

    logger.info(f"Reading matches from {matches_file}...")
    # Read CSV using pandas for fast streaming/parsing
    df = pd.read_csv(matches_file, low_memory=False)
    records = df.to_dict(orient="records")
    total_records = len(records)
    logger.info(f"Successfully loaded {total_records} match records into memory.")

    imported_count = 0
    chunk_num = 1
    total_chunks = (total_records + batch_size - 1) // batch_size

    logger.info(f"Beginning chunked import into Neon database (Batch size: {batch_size}, Total chunks: {total_chunks})...")

    for chunk in chunked_iterable(records, batch_size):
        try:
            with SessionLocal() as session:
                with session.begin():
                    # Process and store this specific batch chunk
                    process_and_store_matches(session, chunk, settings=settings)
            
            imported_count += len(chunk)
            logger.info(f"[{chunk_num}/{total_chunks}] Committed batch of {len(chunk)} matches. Total imported: {imported_count}/{total_records}")
        
        except Exception as e:
            logger.error(f"Error occurred on chunk {chunk_num}: {e}")
            logger.error("Rolling back current chunk and aborting to protect database state.")
            raise
        
        chunk_num += 1

    logger.info("=" * 50)
    logger.info(f"HISTORICAL SEED IMPORT COMPLETE! Successfully stored {imported_count} matches.")
    logger.info("=" * 50)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import BWF historical seed dataset in safe chunks.")
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=Path("~/Desktop").expanduser(),
        help="Path to directory containing manifest.json and matches.csv",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=2000,
        help="Number of records to commit per database transaction chunk.",
    )
    args = parser.parse_args()
    
    import_historical_dataset(dataset_root=args.dataset_root, batch_size=args.batch_size)
