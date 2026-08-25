"""Add authorised BWF player-profile identity evidence.

Revision ID: 0003_bwf_player_profile_identity
Revises: 0002_bwf_ranking_snapshots
Create Date: 2026-08-25
"""
from alembic import op
import sqlalchemy as sa


revision = "0003_bwf_player_profile_identity"
down_revision = "0002_bwf_ranking_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "player_profile_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("source_record_id", sa.String(length=36), nullable=True),
        sa.Column("bwf_profile_id", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("profile_name", sa.String(length=512), nullable=False),
        sa.Column("country_code", sa.String(length=8), nullable=True),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("profile_type", sa.String(length=64), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["data_sources.id"]),
        sa.ForeignKeyConstraint(["source_record_id"], ["raw_ingestion_records.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "bwf_profile_id", "content_hash", name="player_profile_snapshots_unique"),
    )
    op.create_index("ix_player_profile_snapshots_source_id", "player_profile_snapshots", ["source_id"])
    op.create_index("ix_player_profile_snapshots_source_record_id", "player_profile_snapshots", ["source_record_id"])
    op.create_index("ix_player_profile_snapshots_bwf_profile_id", "player_profile_snapshots", ["bwf_profile_id"])
    op.create_index("ix_player_profile_snapshots_profile_retrieved", "player_profile_snapshots", ["bwf_profile_id", "retrieved_at"])

    op.create_table(
        "player_identity_links",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("alias_id", sa.String(length=36), nullable=False),
        sa.Column("player_id", sa.String(length=36), nullable=False),
        sa.Column("profile_snapshot_id", sa.String(length=36), nullable=True),
        sa.Column("decision_status", sa.String(length=32), nullable=False),
        sa.Column("decision_class", sa.String(length=32), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("resolver_version", sa.String(length=64), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_by", sa.String(length=255), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["alias_id"], ["player_aliases.id"]),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"]),
        sa.ForeignKeyConstraint(["profile_snapshot_id"], ["player_profile_snapshots.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("alias_id", "player_id", "resolver_version", name="player_identity_links_unique"),
    )
    op.create_index("ix_player_identity_links_alias_id", "player_identity_links", ["alias_id"])
    op.create_index("ix_player_identity_links_player_id", "player_identity_links", ["player_id"])
    op.create_index("ix_player_identity_links_profile_snapshot_id", "player_identity_links", ["profile_snapshot_id"])
    op.create_index("ix_player_identity_links_decision_status", "player_identity_links", ["decision_status"])
    op.create_index("ix_player_identity_links_status", "player_identity_links", ["decision_status", "decision_class"])


def downgrade() -> None:
    op.drop_table("player_identity_links")
    op.drop_table("player_profile_snapshots")
