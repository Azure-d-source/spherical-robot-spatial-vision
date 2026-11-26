"""Freeze ordered photo batches and retain withdrawn photos."""

import sqlalchemy as sa
from alembic import op

revision = "20261126_03"
down_revision = "20261126_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("frames", sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("frames", sa.Column("withdrawn_by", sa.String(32), nullable=True))
    op.create_foreign_key("fk_frames_withdrawn_by", "frames", "accounts", ["withdrawn_by"], ["account_id"])
    op.create_check_constraint("ck_frames_withdrawal", "frames", "(withdrawn_at IS NULL) = (withdrawn_by IS NULL)")
    op.drop_constraint("uq_frames_scene_hash", "frames", type_="unique")
    op.create_index("uq_frames_scene_active_hash", "frames", ["scene_id", "sha256"], unique=True,
                    postgresql_where=sa.text("withdrawn_at IS NULL"))

    op.create_table(
        "revisions",
        sa.Column("revision_id", sa.String(32), primary_key=True),
        sa.Column("scene_id", sa.String(32), sa.ForeignKey("scenes.scene_id"), nullable=False),
        sa.Column("creator_id", sa.String(32), sa.ForeignKey("accounts.account_id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("scene_id", "revision_id", name="uq_revisions_scene_revision"),
        sa.UniqueConstraint("scene_id", "version", name="uq_revisions_scene_version"),
        sa.UniqueConstraint("scene_id", "fingerprint", name="uq_revisions_scene_fingerprint"),
    )
    op.create_table(
        "revision_frames",
        sa.Column("revision_id", sa.String(32), primary_key=True),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column("scene_id", sa.String(32), nullable=False),
        sa.Column("frame_id", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["scene_id", "revision_id"], ["revisions.scene_id", "revisions.revision_id"],
                                name="fk_revision_frames_revision"),
        sa.ForeignKeyConstraint(["scene_id", "frame_id"], ["frames.scene_id", "frames.frame_id"],
                                name="fk_revision_frames_frame"),
        sa.UniqueConstraint("revision_id", "frame_id", name="uq_revision_frames_revision_frame"),
        sa.CheckConstraint("position >= 0", name="ck_revision_frames_position"),
    )
    op.create_index("ix_revision_frames_frame_id", "revision_frames", ["frame_id"])


def downgrade() -> None:
    op.drop_table("revision_frames")
    op.drop_table("revisions")
    op.create_unique_constraint("uq_frames_scene_hash", "frames", ["scene_id", "sha256"])
    op.drop_index("uq_frames_scene_active_hash", table_name="frames")
    op.drop_constraint("ck_frames_withdrawal", "frames", type_="check")
    op.drop_constraint("fk_frames_withdrawn_by", "frames", type_="foreignkey")
    op.drop_column("frames", "withdrawn_by")
    op.drop_column("frames", "withdrawn_at")
