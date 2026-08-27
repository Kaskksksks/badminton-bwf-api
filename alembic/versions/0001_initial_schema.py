"""initial provenance-aware badminton schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-08-23
"""

from alembic import op

from app.db import models  # noqa: F401 - load every model into Base.metadata
from app.db.base import Base

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


# This migration originally relied on the current model registry. Keep the
# initial-schema behavior stable for fresh installs by excluding tables created
# by later revisions; already-deployed databases do not re-run this revision.
LATER_REVISION_TABLES = {
    "ranking_snapshots",
    "ranking_entries",
    "player_profile_snapshots",
    "player_identity_links",
    "official_tournament_calendar_snapshots",
    "official_tournament_calendar_entries",
    "official_tournament_documents",
}


def upgrade() -> None:
    initial_tables = [table for name, table in Base.metadata.tables.items() if name not in LATER_REVISION_TABLES]
    Base.metadata.create_all(bind=op.get_bind(), tables=initial_tables)


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
