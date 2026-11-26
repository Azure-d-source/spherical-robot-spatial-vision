"""Persist independent worker runs and their published artifacts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261126_04"
down_revision = "20261126_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_runs",
        sa.Column("job_id", sa.String(32), primary_key=True),
        sa.Column("revision_id", sa.String(32), sa.ForeignKey("revisions.revision_id"), nullable=False),
        sa.Column("submitter_id", sa.String(32), sa.ForeignKey("accounts.account_id"), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("recipe_version", sa.String(128), nullable=False),
        sa.Column("run_number", sa.Integer(), nullable=False),
        sa.Column("request_key", sa.String(134), nullable=False),
        sa.Column("rerun_of_id", sa.String(32), sa.ForeignKey("job_runs.job_id"), nullable=True),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("lease_token_hash", sa.String(64), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.String(500), nullable=True),
        sa.Column("result", JSONB(none_as_null=True), nullable=True),
        sa.Column("artifact_directory", sa.String(32), nullable=True),
        sa.UniqueConstraint("revision_id", "kind", "run_number", name="uq_job_runs_run_number"),
        sa.UniqueConstraint("revision_id", "kind", "recipe_version", "request_key", name="uq_job_runs_request"),
        sa.CheckConstraint("kind IN ('depth', 'fusion', 'splat')", name="ck_job_runs_kind"),
        sa.CheckConstraint("status IN ('queued', 'running', 'failed', 'succeeded')", name="ck_job_runs_status"),
    )
    op.create_index("ix_job_runs_queue", "job_runs", ["status", "lease_until", "created_at"])


def downgrade() -> None:
    op.drop_table("job_runs")
