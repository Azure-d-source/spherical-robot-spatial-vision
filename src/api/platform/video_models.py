from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field
from sqlalchemy import BigInteger, DateTime, ForeignKey, ForeignKeyConstraint, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ...workers.extract_frames import WEB_MAX_EDGE
from .database import Base

MAX_VIDEO_BYTES = 200 * 1024 * 1024
MAX_VIDEO_FRAMES = 120
VideoID = Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]


class ExtractionParameters(BaseModel):
    start_seconds: float = Field(default=0, ge=0, le=86400)
    duration_seconds: float | None = Field(default=None, gt=0, le=600)
    fps: float = Field(default=2, ge=0.1, le=30)
    max_frames: int = Field(default=MAX_VIDEO_FRAMES, ge=1, le=MAX_VIDEO_FRAMES)


class StoredParameters(ExtractionParameters):
    max_edge: int = WEB_MAX_EDGE


class VideoImport(Base):
    __tablename__ = "video_imports"
    __table_args__ = (
        UniqueConstraint("scene_id", "video_id", name="uq_video_imports_scene_video"),
        Index("ix_video_imports_scene_created", "scene_id", "created_at"),
    )

    video_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.scene_id"))
    uploader_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"))
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    parameters: Mapped[dict] = mapped_column(JSONB)
    ffmpeg_version: Mapped[str] = mapped_column(String)

    @property
    def original_url(self) -> str:
        return f"/api/scenes/{self.scene_id}/videos/{self.video_id}/original"


class VideoCandidate(Base):
    __tablename__ = "video_candidates"
    __table_args__ = (
        ForeignKeyConstraint(["scene_id", "video_id"], ["video_imports.scene_id", "video_imports.video_id"],
                             name="fk_video_candidates_scene_video"),
        UniqueConstraint("video_id", "position", name="uq_video_candidates_position"),
        UniqueConstraint("scene_id", "candidate_id", name="uq_video_candidates_scene_candidate"),
    )

    candidate_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    scene_id: Mapped[str] = mapped_column(String(32))
    video_id: Mapped[str] = mapped_column(String(32))
    position: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    width: Mapped[int]
    height: Mapped[int]

    @property
    def filename(self) -> str:
        return f"frame_{self.position:06d}.png"

    @property
    def image_url(self) -> str:
        return f"/api/scenes/{self.scene_id}/videos/{self.video_id}/candidates/{self.candidate_id}/image"


class VideoSource(BaseModel):
    video_id: str
    sha256: str
    filename: str
    size_bytes: int
    original_url: str
    parameters: StoredParameters
    ffmpeg_version: str
    candidate_id: str
    position: int


def video_source(video: VideoImport, candidate: VideoCandidate) -> VideoSource:
    return VideoSource(
        video_id=video.video_id, sha256=video.sha256, filename=video.filename, size_bytes=video.size_bytes,
        original_url=video.original_url, parameters=video.parameters, ffmpeg_version=video.ffmpeg_version,
        candidate_id=candidate.candidate_id, position=candidate.position,
    )
