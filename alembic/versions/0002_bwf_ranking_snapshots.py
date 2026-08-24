"""add BWF official ranking snapshots

Revision ID: 0002_bwf_ranking_snapshots
Revises: 0001_initial_schema
Create Date: 2026-08-25
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_bwf_ranking_snapshots"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ranking_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("import_batch_id", sa.String(length=36), nullable=False),
        sa.Column("source_record_id", sa.String(length=36), nullable=True),
        sa.Column("ranking_system", sa.String(length=32), nullable=False),
        sa.Column("population", sa.String(length=32), nullable=False),
        sa.Column("discipline", sa.String(length=8), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("published_week", sa.String(length=64), nullable=True),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column("snapshot_status", sa.String(length=32), nullable=False),
        sa.Column("entry_count", sa.Integer(), nullable=False),
        sa.Column("issue_summary", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["import_batch_id"], ["import_batches.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["data_sources.id"]),
        sa.ForeignKeyConstraint(["source_record_id"], ["raw_ingestion_records.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ranking_system", "discipline", "effective_date", "content_hash", name="ranking_snapshots_scope_hash"),
    )
    op.create_index("ix_ranking_snapshots_source_id", "ranking_snapshots", ["source_id"])
    op.create_index("ix_ranking_snapshots_import_batch_id", "ranking_snapshots", ["import_batch_id"])
    op.create_index("ix_ranking_snapshots_source_record_id", "ranking_snapshots", ["source_record_id"])
    op.create_index("ix_ranking_snapshots_ranking_system", "ranking_snapshots", ["ranking_system"])
    op.create_index("ix_ranking_snapshots_population", "ranking_snapshots", ["population"])
    op.create_index("ix_ranking_snapshots_discipline", "ranking_snapshots", ["discipline"])
    op.create_index("ix_ranking_snapshots_effective_date", "ranking_snapshots", ["effective_date"])
    op.create_index("ix_ranking_snapshots_scope_date", "ranking_snapshots", ["ranking_system", "discipline", "effective_date"])

    op.create_table(
        "ranking_entries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("ranking_position", sa.Integer(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=True),
        sa.Column("tournament_count", sa.Integer(), nullable=True),
        sa.Column("rank_change", sa.Integer(), nullable=True),
        sa.Column("subject_kind", sa.String(length=16), nullable=False),
        sa.Column("subject_key", sa.String(length=512), nullable=False),
        sa.Column("subject_display_name", sa.String(length=1024), nullable=False),
        sa.Column("official_subject_id", sa.String(length=512), nullable=True),
        sa.Column("country_code", sa.String(length=8), nullable=True),
        sa.Column("platform_player_id", sa.String(length=36), nullable=True),
        sa.Column("identity_status", sa.String(length=32), nullable=False),
        sa.Column("source_payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["platform_player_id"], ["players.id"]),
        sa.ForeignKeyConstraint(["snapshot_id"], ["ranking_snapshots.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "ranking_position", "subject_key", name="ranking_entries_snapshot_position_subject"),
    )
    op.create_index("ix_ranking_entries_snapshot_id", "ranking_entries", ["snapshot_id"])
    op.create_index("ix_ranking_entries_platform_player_id", "ranking_entries", ["platform_player_id"])
    op.create_index("ix_ranking_entries_snapshot_position", "ranking_entries", ["snapshot_id", "ranking_position"])
    op.create_index("ix_ranking_entries_official_id", "ranking_entries", ["official_subject_id"])


def downgrade() -> None:
    op.drop_table("ranking_entries")
    op.drop_table("ranking_snapshots")
