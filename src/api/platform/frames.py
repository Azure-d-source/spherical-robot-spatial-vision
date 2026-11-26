import logging
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, field_serializer
from sqlalchemy import BigInteger, DateTime, ForeignKey, ForeignKeyConstraint, Index, String, UniqueConstraint, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Mapped, Session, mapped_column

from ..images import MAX_REQUEST, photo_path, read_image, save_image
from ..models import Frame as FrameResponse
from .accounts import CurrentAccount, UNAUTHENTICATED
from .database import Base, Database
from .errors import ApiError, ErrorResponse, InvalidRequest
from .scenes import Scene, require_scene

router = APIRouter(prefix="/api", tags=["照片"])
logger = logging.getLogger(__name__)
PHOTO_ACCESS_ERRORS = {**UNAUTHENTICATED, 404: {"model": ErrorResponse}}


class Frame(Base):
    __tablename__ = "frames"
    __table_args__ = (
        UniqueConstraint("scene_id", "sha256", name="uq_frames_scene_hash"),
        UniqueConstraint("scene_id", "frame_id", name="uq_frames_scene_frame"),
        Index("ix_frames_scene_created", "scene_id", "created_at", "frame_id"),
    )

    frame_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.scene_id"))
    uploader_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"))
    capture_id: Mapped[str] = mapped_column(String(128))
    filename: Mapped[str] = mapped_column(String(255))
    view_label: Mapped[str] = mapped_column(String(120))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    media_type: Mapped[str] = mapped_column(String(32))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    width: Mapped[int]
    height: Mapped[int]

    @property
    def image_url(self) -> str:
        return f"/api/frames/{self.frame_id}/image"


class FrameUpload(Base):
    __tablename__ = "frame_uploads"
    __table_args__ = (
        ForeignKeyConstraint(["scene_id", "frame_id"], ["frames.scene_id", "frames.frame_id"],
                             name="fk_frame_uploads_scene_frame"),
        UniqueConstraint("scene_id", "uploader_id", "capture_id", name="uq_frame_uploads_capture"),
        Index("ix_frame_uploads_frame_created", "frame_id", "created_at", "upload_id"),
    )

    upload_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    scene_id: Mapped[str] = mapped_column(String(32))
    frame_id: Mapped[str] = mapped_column(String(32))
    uploader_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"))
    capture_id: Mapped[str] = mapped_column(String(128))
    view_label: Mapped[str] = mapped_column(String(120))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TeamFrame(FrameResponse):
    model_config = ConfigDict(from_attributes=True)
    uploader_id: str

    @field_serializer("captured_at", "created_at")
    def serialize_times(self, value: datetime) -> datetime:
        return value.astimezone(timezone.utc)


class UploadRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    upload_id: str
    frame_id: str
    uploader_id: str
    capture_id: str
    view_label: str
    captured_at: datetime
    created_at: datetime

    @field_serializer("captured_at", "created_at")
    def serialize_times(self, value: datetime) -> datetime:
        return value.astimezone(timezone.utc)


def lock_photo_file(db: Session, digest: str) -> None:
    # Content-addressed files can be shared by scenes in the same database.
    key = int.from_bytes(bytes.fromhex(digest[:16]), "big", signed=True)
    db.execute(select(func.pg_advisory_xact_lock(key)))


def rollback_photo(db: Session, digest: str, destination: Path) -> None:
    try:
        with db.begin():
            lock_photo_file(db, digest)
            if db.scalar(select(Frame.frame_id).where(Frame.sha256 == digest).limit(1)) is None:
                destination.unlink(missing_ok=True)
    except (SQLAlchemyError, OSError):
        logger.exception("Could not remove an unreferenced photo after upload rollback: %s", digest)


@router.get("/scenes/{scene_id}/frames", response_model=list[TeamFrame], responses=PHOTO_ACCESS_ERRORS)
def list_frames(scene_id: str, account: CurrentAccount, db: Database) -> list[Frame]:
    require_scene(db, account.team_id, scene_id)
    return list(db.scalars(
        select(Frame).where(Frame.scene_id == scene_id).order_by(Frame.created_at, Frame.frame_id)
    ))


@router.post("/scenes/{scene_id}/frames", response_model=TeamFrame, status_code=201,
             max_body_size=MAX_REQUEST, responses={
                 **PHOTO_ACCESS_ERRORS,
                 200: {"model": TeamFrame, "description": "复用同一张照片"},
                 409: {"model": ErrorResponse},
                 413: {"model": ErrorResponse},
                 422: {"model": ErrorResponse | InvalidRequest},
             })
def upload_frame(
    scene_id: str, request: Request, response: Response, account: CurrentAccount, db: Database,
    image: Annotated[UploadFile, File()],
    capture_id: Annotated[str, Form(min_length=1, max_length=128)],
    view_label: Annotated[str, Form(max_length=120)] = "",
    captured_at: Annotated[AwareDatetime | None, Form()] = None,
) -> Frame:
    require_scene(db, account.team_id, scene_id)
    capture_id = capture_id.strip()
    view_label = view_label.strip() or "未标注"
    if not capture_id:
        raise ApiError(422, "INVALID_CAPTURE_ID", "采集编号须包含有效字符。")
    try:
        data, digest, media_type, width, height = read_image(image)
    except HTTPException as exc:
        code = "PHOTO_LIMIT_EXCEEDED" if exc.status_code == 413 else "INVALID_IMAGE"
        raise ApiError(exc.status_code, code, str(exc.detail)) from exc

    # Serialize deduplication and idempotency within one scene.
    require_scene(db, account.team_id, scene_id, for_update=True)
    captured_frame = db.scalar(
        select(Frame).join(FrameUpload, FrameUpload.frame_id == Frame.frame_id).where(
            FrameUpload.scene_id == scene_id, FrameUpload.uploader_id == account.account_id,
            FrameUpload.capture_id == capture_id,
        )
    )
    if captured_frame is not None:
        if captured_frame.sha256 != digest:
            raise ApiError(409, "CAPTURE_CONFLICT", "该采集编号已关联另一张照片。")
        response.status_code = 200
        return captured_frame

    frame = db.scalar(select(Frame).where(Frame.scene_id == scene_id, Frame.sha256 == digest))
    new_frame = frame is None
    now = datetime.now(timezone.utc)
    observed = captured_at or now
    if new_frame:
        frame = Frame(
            frame_id=uuid4().hex, scene_id=scene_id, uploader_id=account.account_id,
            capture_id=capture_id, filename=PureWindowsPath(image.filename or "").name[:255] or "photo",
            view_label=view_label, captured_at=observed, created_at=now, sha256=digest,
            media_type=media_type, size_bytes=len(data), width=width, height=height,
        )
        db.add(frame)
        db.flush()
    else:
        response.status_code = 200

    db.add(FrameUpload(
        upload_id=uuid4().hex, frame_id=frame.frame_id, scene_id=scene_id, uploader_id=account.account_id,
        capture_id=capture_id, view_label=view_label, captured_at=observed, created_at=now,
    ))
    destination = photo_path(request.app.state.photos, digest, media_type)
    published = False
    try:
        db.flush()
        if new_frame:
            lock_photo_file(db, digest)
            published = save_image(data, destination)
        db.commit()
    except (SQLAlchemyError, OSError):
        db.rollback()
        if published:
            rollback_photo(db, digest, destination)
        raise
    return frame


@router.get("/scenes/{scene_id}/frames/{frame_id}/uploads", response_model=list[UploadRecord],
            responses=PHOTO_ACCESS_ERRORS)
def frame_uploads(scene_id: str, frame_id: str, account: CurrentAccount, db: Database) -> list[FrameUpload]:
    require_scene(db, account.team_id, scene_id)
    if db.scalar(select(Frame.frame_id).where(Frame.frame_id == frame_id, Frame.scene_id == scene_id)) is None:
        raise ApiError(404, "FRAME_NOT_FOUND", "未找到该照片。")
    query = select(FrameUpload).where(FrameUpload.frame_id == frame_id)
    return list(db.scalars(query.order_by(FrameUpload.created_at, FrameUpload.upload_id)))


@router.get("/frames/{frame_id}/image", response_class=FileResponse, responses=PHOTO_ACCESS_ERRORS)
def get_image(frame_id: str, request: Request, account: CurrentAccount, db: Database) -> FileResponse:
    frame = db.scalar(select(Frame).join(Scene).where(Frame.frame_id == frame_id, Scene.team_id == account.team_id))
    if frame is None:
        raise ApiError(404, "FRAME_NOT_FOUND", "未找到该照片。")
    media_type = frame.media_type
    path = photo_path(request.app.state.photos, frame.sha256, media_type)
    db.rollback()
    if not path.is_file():
        raise ApiError(404, "PHOTO_MISSING", "原图文件缺失。")
    return FileResponse(path, media_type=media_type, headers={"X-Content-Type-Options": "nosniff"})
