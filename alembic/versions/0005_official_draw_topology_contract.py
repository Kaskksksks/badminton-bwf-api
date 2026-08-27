"""Add parser-validated official draw topology and reconciliation schema.

Revision ID: 0005_draw_topology
Revises: 0004_bwf_calendar_draws
Create Date: 2026-08-28
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_draw_topology"
down_revision = "0004_bwf_calendar_draws"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "official_draw_topologies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("discipline", sa.String(length=8), nullable=False),
        sa.Column("topology_status", sa.String(length=32), nullable=False),
        sa.Column("source_content_hash", sa.String(length=128), nullable=False),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column("parsed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("parser_issue", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["official_tournament_documents.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "discipline", "parser_version", name="official_draw_topology_document_discipline_parser"),
    )
    op.create_index("ix_official_draw_topologies_document_id", "official_draw_topologies", ["document_id"])
    op.create_index("ix_official_draw_topologies_discipline", "official_draw_topologies", ["discipline"])
    op.create_index("ix_official_draw_topologies_topology_status", "official_draw_topologies", ["topology_status"])
    op.create_table(
        "official_draw_nodes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("topology_id", sa.String(length=36), nullable=False),
        sa.Column("source_node_key", sa.String(length=128), nullable=False),
        sa.Column("round_label", sa.String(length=255), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("participant_1_label", sa.String(length=1024), nullable=True),
        sa.Column("participant_2_label", sa.String(length=1024), nullable=True),
        sa.Column("winner_label", sa.String(length=1024), nullable=True),
        sa.Column("score_text", sa.String(length=1024), nullable=True),
        sa.ForeignKeyConstraint(["topology_id"], ["official_draw_topologies.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("topology_id", "source_node_key", name="official_draw_nodes_topology_key"),
    )
    op.create_index("ix_official_draw_nodes_topology_id", "official_draw_nodes", ["topology_id"])
    op.create_table(
        "official_draw_node_reconciliations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("node_id", sa.String(length=36), nullable=False),
        sa.Column("match_id", sa.String(length=36), nullable=True),
        sa.Column("reconciliation_status", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.String(length=32), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["node_id"], ["official_draw_nodes.id"]),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("node_id", "match_id", name="official_draw_node_match_link"),
    )
    op.create_index("ix_official_draw_node_reconciliations_node_id", "official_draw_node_reconciliations", ["node_id"])
    op.create_index("ix_official_draw_node_reconciliations_match_id", "official_draw_node_reconciliations", ["match_id"])
    op.create_index("ix_official_draw_node_reconciliations_reconciliation_status", "official_draw_node_reconciliations", ["reconciliation_status"])


def downgrade() -> None:
    op.drop_table("official_draw_node_reconciliations")
    op.drop_table("official_draw_nodes")
    op.drop_table("official_draw_topologies")
