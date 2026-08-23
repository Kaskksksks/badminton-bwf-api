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


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
