"""Add authorised BWF Corporate calendar and draw document metadata.

Revision ID: 0004_bwf_corporate_calendar_draws
Revises: 0003_bwf_player_profile_identity
Create Date: 2026-08-27
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_bwf_corporate_calendar_draws"
down_revision = "0003_bwf_player_profile_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "official_tournament_calendar_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column("snapshot_status", sa.String(length=32), nullable=False),
        sa.Column("entry_count", sa.Integer(), nullable=False),
        sa.Column("issue_summary", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["source_id"], ["data_sources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "content_hash", name="official_calendar_snapshots_source_hash"),
    )
    op.create_index(
        "ix_official_calendar_snapshots_retrieved",
        "official_tournament_calendar_snapshots",
        ["source_id", "retrieved_at"],
    )

    op.create_table(
        "official_tournament_calendar_entries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("source_tournament_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("country_code", sa.String(length=8), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("category", sa.String(length=255), nullable=True),
        sa.Column("city", sa.String(length=255), nullable=True),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("draw_date_text", sa.String(length=255), nullable=True),
        sa.Column("eligibility_status", sa.String(length=32), nullable=False),
        sa.Column("eligibility_rationale", sa.Text(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id"], ["official_tournament_calendar_snapshots.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "source_tournament_id", name="official_calendar_entries_snapshot_source"),
    )
    op.create_index(
        "ix_official_calendar_entries_dates", "official_tournament_calendar_entries", ["start_date", "end_date"]
    )

    op.create_table(
        "official_tournament_documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("calendar_entry_id", sa.String(length=36), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("document_label", sa.String(length=1024), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column("parser_status", sa.String(length=32), nullable=False),
        sa.Column("parser_issue", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["calendar_entry_id"], ["official_tournament_calendar_entries.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("calendar_entry_id", "content_hash", name="official_tournament_documents_entry_hash"),
    )
    op.create_index(
        "ix_official_tournament_documents_entry_retrieved",
        "official_tournament_documents",
        ["calendar_entry_id", "retrieved_at"],
    )


def downgrade() -> None:
    op.drop_table("official_tournament_documents")
    op.drop_table("official_tournament_calendar_entries")
    op.drop_table("official_tournament_calendar_snapshots")
