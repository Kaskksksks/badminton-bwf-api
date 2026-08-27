"""Add evidence-gated forecast, head-to-head, and simulation contract storage.

Revision ID: 0006_model_contracts
Revises: 0005_draw_topology
Create Date: 2026-08-28
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_model_contracts"
down_revision = "0005_draw_topology"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tournaments", sa.Column("source_category_raw", sa.String(length=255), nullable=True))
    op.create_table(
        "model_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_key", sa.String(length=128), nullable=False), sa.Column("model_version", sa.String(length=128), nullable=False), sa.Column("model_status", sa.String(length=32), nullable=False),
        sa.Column("training_cutoff", sa.DateTime(timezone=True), nullable=True), sa.Column("input_contract", sa.JSON(), nullable=False), sa.Column("calibration_status", sa.String(length=32), nullable=False),
        sa.Column("evaluation_summary", sa.JSON(), nullable=True), sa.Column("methodology_reference", sa.String(length=2048), nullable=True), sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("model_key", "model_version", name="model_snapshots_key_version"),
    )
    op.create_index("ix_model_snapshots_model_key", "model_snapshots", ["model_key"])
    op.create_index("ix_model_snapshots_model_status", "model_snapshots", ["model_status"])
    op.create_table(
        "match_forecast_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_snapshot_id", sa.String(length=36), nullable=False), sa.Column("match_id", sa.String(length=36), nullable=False), sa.Column("input_cutoff", sa.DateTime(timezone=True), nullable=False), sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False), sa.Column("forecast_status", sa.String(length=32), nullable=False),
        sa.Column("participant_1_win_probability_bps", sa.Integer(), nullable=False), sa.Column("participant_2_win_probability_bps", sa.Integer(), nullable=False), sa.Column("confidence_label", sa.String(length=32), nullable=False), sa.Column("uncertainty_summary", sa.Text(), nullable=False), sa.Column("evidence_contributors", sa.JSON(), nullable=False), sa.Column("provenance", sa.JSON(), nullable=False), sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True), sa.Column("official_winner_participant_id", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(["model_snapshot_id"], ["model_snapshots.id"]), sa.ForeignKeyConstraint(["match_id"], ["matches.id"]), sa.ForeignKeyConstraint(["official_winner_participant_id"], ["participants.id"]),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("model_snapshot_id", "match_id", "input_cutoff", name="match_forecasts_model_match_cutoff"),
    )
    op.create_index("ix_match_forecast_snapshots_model_snapshot_id", "match_forecast_snapshots", ["model_snapshot_id"])
    op.create_index("ix_match_forecast_snapshots_match_id", "match_forecast_snapshots", ["match_id"])
    op.create_index("ix_match_forecast_snapshots_forecast_status", "match_forecast_snapshots", ["forecast_status"])
    op.create_table(
        "head_to_head_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("participant_a_id", sa.String(length=36), nullable=False), sa.Column("participant_b_id", sa.String(length=36), nullable=False), sa.Column("input_cutoff", sa.DateTime(timezone=True), nullable=False), sa.Column("summary_status", sa.String(length=32), nullable=False), sa.Column("eligible_meetings", sa.Integer(), nullable=False), sa.Column("participant_a_wins", sa.Integer(), nullable=False), sa.Column("participant_b_wins", sa.Integer(), nullable=False), sa.Column("evidence", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["participant_a_id"], ["participants.id"]), sa.ForeignKeyConstraint(["participant_b_id"], ["participants.id"]), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("participant_a_id", "participant_b_id", "input_cutoff", name="head_to_head_pair_cutoff"),
    )
    op.create_index("ix_head_to_head_snapshots_participant_a_id", "head_to_head_snapshots", ["participant_a_id"])
    op.create_index("ix_head_to_head_snapshots_participant_b_id", "head_to_head_snapshots", ["participant_b_id"])
    op.create_index("ix_head_to_head_snapshots_summary_status", "head_to_head_snapshots", ["summary_status"])
    op.create_table(
        "tournament_simulation_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_snapshot_id", sa.String(length=36), nullable=False), sa.Column("tournament_id", sa.String(length=36), nullable=False), sa.Column("draw_topology_id", sa.String(length=36), nullable=False), sa.Column("input_cutoff", sa.DateTime(timezone=True), nullable=False), sa.Column("simulation_status", sa.String(length=32), nullable=False), sa.Column("simulation_count", sa.Integer(), nullable=False), sa.Column("probability_payload", sa.JSON(), nullable=False), sa.Column("provenance", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["model_snapshot_id"], ["model_snapshots.id"]), sa.ForeignKeyConstraint(["tournament_id"], ["tournaments.id"]), sa.ForeignKeyConstraint(["draw_topology_id"], ["official_draw_topologies.id"]), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("model_snapshot_id", "tournament_id", "input_cutoff", name="tournament_simulation_model_tournament_cutoff"),
    )
    op.create_index("ix_tournament_simulation_snapshots_model_snapshot_id", "tournament_simulation_snapshots", ["model_snapshot_id"])
    op.create_index("ix_tournament_simulation_snapshots_tournament_id", "tournament_simulation_snapshots", ["tournament_id"])
    op.create_index("ix_tournament_simulation_snapshots_draw_topology_id", "tournament_simulation_snapshots", ["draw_topology_id"])
    op.create_index("ix_tournament_simulation_snapshots_simulation_status", "tournament_simulation_snapshots", ["simulation_status"])


def downgrade() -> None:
    op.drop_table("tournament_simulation_snapshots")
    op.drop_table("head_to_head_snapshots")
    op.drop_table("match_forecast_snapshots")
    op.drop_table("model_snapshots")
    op.drop_column("tournaments", "source_category_raw")
