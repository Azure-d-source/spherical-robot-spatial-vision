"""Add video imports, candidate links, and frozen provenance."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261127_06"
down_revision = "20261126_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "video_imports",
        sa.Column("video_id", sa.String(32), primary_key=True),
        sa.Column("scene_id", sa.String(32), sa.ForeignKey("scenes.scene_id"), nullable=False),
        sa.Column("uploader_id", sa.String(32), sa.ForeignKey("accounts.account_id"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("parameters", JSONB, nullable=False),
        sa.Column("ffmpeg_version", sa.String, nullable=False),
        sa.UniqueConstraint("scene_id", "video_id", name="uq_video_imports_scene_video"),
    )
    op.create_index("ix_video_imports_scene_created", "video_imports", ["scene_id", "created_at"])
    op.create_table(
        "video_candidates",
        sa.Column("candidate_id", sa.String(32), primary_key=True),
        sa.Column("scene_id", sa.String(32), nullable=False),
        sa.Column("video_id", sa.String(32), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("width", sa.Integer, nullable=False),
        sa.Column("height", sa.Integer, nullable=False),
        sa.ForeignKeyConstraint(["scene_id", "video_id"], ["video_imports.scene_id", "video_imports.video_id"],
                                name="fk_video_candidates_scene_video"),
        sa.UniqueConstraint("video_id", "position", name="uq_video_candidates_position"),
        sa.UniqueConstraint("scene_id", "candidate_id", name="uq_video_candidates_scene_candidate"),
    )
    op.add_column("frame_uploads", sa.Column("video_candidate_id", sa.String(32), nullable=True))
    op.create_foreign_key(
        "fk_frame_uploads_scene_candidate", "frame_uploads", "video_candidates",
        ["scene_id", "video_candidate_id"], ["scene_id", "candidate_id"],
    )
    op.create_index("ix_frame_uploads_video_candidate", "frame_uploads", ["video_candidate_id"])
    op.add_column("revision_frames", sa.Column("video_sources", JSONB(none_as_null=True), nullable=True))


def downgrade() -> None:
    op.drop_column("revision_frames", "video_sources")
    op.drop_index("ix_frame_uploads_video_candidate", table_name="frame_uploads")
    op.drop_constraint("fk_frame_uploads_scene_candidate", "frame_uploads", type_="foreignkey")
    op.drop_column("frame_uploads", "video_candidate_id")
    op.drop_table("video_candidates")
    op.drop_table("video_imports")
