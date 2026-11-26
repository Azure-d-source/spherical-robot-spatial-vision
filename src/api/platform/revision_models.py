from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Revision(Base):
    __tablename__ = "revisions"
    __table_args__ = (
        UniqueConstraint("scene_id", "revision_id", name="uq_revisions_scene_revision"),
        UniqueConstraint("scene_id", "version", name="uq_revisions_scene_version"),
        UniqueConstraint("scene_id", "fingerprint", name="uq_revisions_scene_fingerprint"),
    )

    revision_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.scene_id"))
    creator_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"))
    version: Mapped[int]
    fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    frames: Mapped[list["RevisionFrame"]] = relationship(order_by="RevisionFrame.position", lazy="raise")

    @property
    def frame_ids(self) -> list[str]:
        return [frame.frame_id for frame in self.frames]


class RevisionFrame(Base):
    __tablename__ = "revision_frames"
    __table_args__ = (
        ForeignKeyConstraint(["scene_id", "revision_id"], ["revisions.scene_id", "revisions.revision_id"],
                             name="fk_revision_frames_revision"),
        ForeignKeyConstraint(["scene_id", "frame_id"], ["frames.scene_id", "frames.frame_id"],
                             name="fk_revision_frames_frame"),
        UniqueConstraint("revision_id", "frame_id", name="uq_revision_frames_revision_frame"),
        CheckConstraint("position >= 0", name="ck_revision_frames_position"),
        Index("ix_revision_frames_frame_id", "frame_id"),
    )

    revision_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    position: Mapped[int] = mapped_column(primary_key=True)
    scene_id: Mapped[str] = mapped_column(String(32))
    frame_id: Mapped[str] = mapped_column(String(32))
