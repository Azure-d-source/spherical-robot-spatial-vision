"""Add deduplicated scene photos and individual upload records."""

import sqlalchemy as sa
from alembic import op

revision = "20261126_02"
down_revision = "20261126_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "frames",
        sa.Column("frame_id", sa.String(32), primary_key=True),
        sa.Column("scene_id", sa.String(32), sa.ForeignKey("scenes.scene_id"), nullable=False),
        sa.Column("uploader_id", sa.String(32), sa.ForeignKey("accounts.account_id"), nullable=False),
        sa.Column("capture_id", sa.String(128), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("view_label", sa.String(120), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("media_type", sa.String(32), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.UniqueConstraint("scene_id", "sha256", name="uq_frames_scene_hash"),
        sa.UniqueConstraint("scene_id", "frame_id", name="uq_frames_scene_frame"),
    )
    op.create_index("ix_frames_sha256", "frames", ["sha256"])
    op.create_index("ix_frames_scene_created", "frames", ["scene_id", "created_at", "frame_id"])
    op.create_table(
        "frame_uploads",
        sa.Column("upload_id", sa.String(32), primary_key=True),
        sa.Column("scene_id", sa.String(32), nullable=False),
        sa.Column("frame_id", sa.String(32), nullable=False),
        sa.Column("uploader_id", sa.String(32), sa.ForeignKey("accounts.account_id"), nullable=False),
        sa.Column("capture_id", sa.String(128), nullable=False),
        sa.Column("view_label", sa.String(120), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["scene_id", "frame_id"], ["frames.scene_id", "frames.frame_id"],
                                name="fk_frame_uploads_scene_frame"),
        sa.UniqueConstraint("scene_id", "uploader_id", "capture_id", name="uq_frame_uploads_capture"),
    )
    op.create_index("ix_frame_uploads_frame_created", "frame_uploads", ["frame_id", "created_at", "upload_id"])


def downgrade() -> None:
    op.drop_table("frame_uploads")
    op.drop_table("frames")
