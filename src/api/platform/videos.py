import logging
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from tempfile import TemporaryDirectory
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_serializer
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.requests import ClientDisconnect

from ...workers.extract_frames import extract_frames
from ..images import photo_path, read_image, save_image
from .accounts import CurrentAccount
from .database import Database
from .errors import ApiError
from .frames import PHOTO_ACCESS_ERRORS, Frame, FrameUpload, TeamFrame, lock_photo_file, record_frame_upload, rollback_photo
from .scenes import require_active, require_scene, require_writable_scene
from .video_models import (
    MAX_VIDEO_BYTES, MAX_VIDEO_FRAMES, ExtractionParameters, StoredParameters, VideoCandidate, VideoID, VideoImport,
)

router = APIRouter(prefix="/api/scenes/{scene_id}/videos", tags=["视频"], responses=PHOTO_ACCESS_ERRORS)
logger = logging.getLogger(__name__)
LIMIT_MESSAGE = "单个 MP4 视频最大为 200 MiB。"
SAFE_HEADERS = {"X-Content-Type-Options": "nosniff"}


class VideoRequest(ExtractionParameters):
    filename: str = Field(min_length=1, max_length=255)


class CandidatePreview(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    candidate_id: str
    position: int
    image_url: str
    width: int
    height: int


class VideoSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    video_id: str
    filename: str
    sha256: str
    size_bytes: int
    created_at: datetime
    original_url: str
    parameters: StoredParameters
    ffmpeg_version: str

    @field_serializer("created_at")
    def serialize_time(self, value: datetime) -> datetime:
        return value.astimezone(timezone.utc)


class VideoPreview(VideoSummary):
    candidates: list[CandidatePreview]


class Selection(BaseModel):
    candidate_ids: list[VideoID] = Field(min_length=1, max_length=MAX_VIDEO_FRAMES)


def require_video(db: Session, scene_id: str, video_id: str) -> VideoImport:
    video = db.scalar(select(VideoImport).where(VideoImport.scene_id == scene_id, VideoImport.video_id == video_id))
    if video is None:
        raise ApiError(404, "VIDEO_NOT_FOUND", "未找到该视频。")
    return video


def preview(video: VideoImport, candidates: list[VideoCandidate]) -> VideoPreview:
    return VideoPreview(
        **VideoSummary.model_validate(video).model_dump(),
        candidates=[CandidatePreview.model_validate(candidate) for candidate in candidates],
    )


def get_candidates(db: Session, video_id: str):
    return select(VideoCandidate).where(VideoCandidate.video_id == video_id).order_by(VideoCandidate.position)


async def store_request(request: Request, path: Path) -> int:
    size = 0
    try:
        with path.open("xb") as output:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_VIDEO_BYTES:
                    raise ApiError(413, "VIDEO_LIMIT_EXCEEDED", LIMIT_MESSAGE)
                if chunk:
                    await run_in_threadpool(output.write, chunk)
    except ClientDisconnect as exc:
        raise ApiError(400, "VIDEO_UPLOAD_INTERRUPTED", "视频上传中断，请重试。") from exc
    if not size:
        raise ApiError(422, "INVALID_VIDEO", "请上传可播放的 MP4 视频。")
    return size


def extract_video(video: VideoImport, directory: Path, ffmpeg: str) -> list[VideoCandidate]:
    parameters = video.parameters
    try:
        manifest = extract_frames(
            directory / "source.mp4", directory / "frames", ffmpeg=ffmpeg,
            start=parameters["start_seconds"], duration=parameters["duration_seconds"],
            fps=parameters["fps"], max_frames=parameters["max_frames"], bounded=True,
        )
    except FileNotFoundError as exc:
        raise ApiError(503, "FFMPEG_UNAVAILABLE", "视频抽帧服务暂不可用。") from exc
    except subprocess.TimeoutExpired as exc:
        raise ApiError(422, "VIDEO_EXTRACTION_TIMEOUT", "抽帧超时，请缩短抽帧区间或降低帧数。") from exc
    except (ValueError, RuntimeError) as exc:
        logger.info("Video extraction failed: %s", exc)
        raise ApiError(422, "VIDEO_EXTRACTION_FAILED", "无法抽出候选帧，请检查 MP4 文件、区间和帧率。") from exc
    except subprocess.CalledProcessError as exc:
        raise ApiError(503, "FFMPEG_UNAVAILABLE", "视频抽帧服务暂不可用。") from exc

    video.sha256 = manifest["source"]["sha256"]
    video.ffmpeg_version = manifest["tool"]["version"]
    candidates = []
    for position, filename in enumerate(manifest["frames"], start=1):
        with (directory / "frames" / filename).open("rb") as source:
            try:
                data, digest, _media_type, width, height = read_image(UploadFile(source))
            except HTTPException as exc:
                raise ApiError(422, "INVALID_VIDEO_FRAME", "抽出的候选帧无法作为场景照片导入。") from exc
        candidates.append(VideoCandidate(
            candidate_id=uuid4().hex, scene_id=video.scene_id, video_id=video.video_id, position=position,
            sha256=digest, size_bytes=len(data), width=width, height=height,
        ))
    (directory / "frames" / "manifest.json").unlink()
    return candidates


def publish_video(
    db: Session, team_id: str, video: VideoImport, candidates: list[VideoCandidate],
    directory: Path, destination: Path,
) -> VideoPreview:
    require_writable_scene(db, team_id, video.scene_id)
    db.add(video)
    db.flush()
    db.add_all(candidates)
    db.flush()
    directory.rename(destination)
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        try:
            if db.get(VideoImport, video.video_id) is None:
                shutil.rmtree(destination)
        except (OSError, SQLAlchemyError):
            logger.exception("Could not reconcile video publication: %s", destination.name)
        raise
    return preview(video, candidates)


def check_upload_access(db: Session, team_id: str, scene_id: str) -> None:
    require_active(require_scene(db, team_id, scene_id))
    db.rollback()


@router.post("", response_model=VideoPreview, status_code=201, openapi_extra={"requestBody": {
    "required": True, "content": {"video/mp4": {"schema": {"type": "string", "format": "binary"}}},
}})
async def upload_video(
    scene_id: str, request: Request, account: CurrentAccount, db: Database,
    options: Annotated[VideoRequest, Query()],
) -> VideoPreview:
    team_id, uploader_id = account.team_id, account.account_id
    await run_in_threadpool(check_upload_access, db, team_id, scene_id)
    if request.headers.get("content-type", "").partition(";")[0].strip().lower() != "video/mp4":
        raise ApiError(415, "INVALID_VIDEO_TYPE", "请上传 MP4 视频。")
    filename = PureWindowsPath(options.filename).name
    if not filename.lower().endswith(".mp4") or any(ord(char) < 32 for char in filename):
        raise ApiError(422, "INVALID_VIDEO_FILENAME", "请选择扩展名为 .mp4 的文件。")
    length = request.headers.get("content-length", "").lstrip("0")
    if length.isascii() and length.isdecimal() and (
        len(length) > len(str(MAX_VIDEO_BYTES)) or int(length) > MAX_VIDEO_BYTES
    ):
        raise ApiError(413, "VIDEO_LIMIT_EXCEEDED", LIMIT_MESSAGE)

    slots = request.app.state.video_slots
    if not slots.acquire(blocking=False):
        raise ApiError(503, "VIDEO_IMPORT_BUSY", "正在处理另一个视频，请稍后重试。")
    root = request.app.state.videos
    try:
        with TemporaryDirectory(prefix=".upload-", dir=root) as temporary:
            directory = Path(temporary) / "video"
            directory.mkdir()
            size = await store_request(request, directory / "source.mp4")
            video = VideoImport(
                video_id=uuid4().hex, scene_id=scene_id, uploader_id=uploader_id, filename=filename,
                size_bytes=size, created_at=datetime.now(timezone.utc),
                parameters=StoredParameters(**options.model_dump(exclude={"filename"})).model_dump(),
            )
            candidates = await run_in_threadpool(extract_video, video, directory, request.app.state.ffmpeg)
            return await run_in_threadpool(publish_video, db, team_id, video, candidates, directory, root / video.video_id)
    finally:
        slots.release()


@router.get("", response_model=list[VideoSummary])
def list_videos(scene_id: str, account: CurrentAccount, db: Database) -> list[VideoImport]:
    require_scene(db, account.team_id, scene_id)
    return list(db.scalars(select(VideoImport).where(VideoImport.scene_id == scene_id)
                           .order_by(VideoImport.created_at.desc(), VideoImport.video_id)))


@router.get("/{video_id}", response_model=VideoPreview)
def get_video(scene_id: str, video_id: str, account: CurrentAccount, db: Database) -> VideoPreview:
    require_scene(db, account.team_id, scene_id)
    video = require_video(db, scene_id, video_id)
    return preview(video, list(db.scalars(get_candidates(db, video_id))))


@router.get("/{video_id}/original", response_class=FileResponse)
def get_original(scene_id: str, video_id: str, request: Request, account: CurrentAccount, db: Database) -> FileResponse:
    require_scene(db, account.team_id, scene_id)
    video = require_video(db, scene_id, video_id)
    path, filename = request.app.state.videos / video.video_id / "source.mp4", video.filename
    db.rollback()
    if not path.is_file():
        raise ApiError(404, "VIDEO_MISSING", "原始视频文件缺失。")
    return FileResponse(path, media_type="video/mp4", filename=filename, headers=SAFE_HEADERS)


@router.get("/{video_id}/candidates/{candidate_id}/image", response_class=FileResponse)
def get_candidate(
    scene_id: str, video_id: str, candidate_id: str, request: Request, account: CurrentAccount, db: Database,
) -> FileResponse:
    require_scene(db, account.team_id, scene_id)
    require_video(db, scene_id, video_id)
    candidate = db.scalar(get_candidates(db, video_id).where(VideoCandidate.candidate_id == candidate_id))
    if candidate is None:
        raise ApiError(404, "CANDIDATE_NOT_FOUND", "未找到该候选帧。")
    path = request.app.state.videos / candidate.video_id / "frames" / candidate.filename
    db.rollback()
    if not path.is_file():
        raise ApiError(404, "CANDIDATE_MISSING", "候选帧文件缺失。")
    return FileResponse(path, media_type="image/png", headers=SAFE_HEADERS)


@router.post("/{video_id}/import", response_model=list[TeamFrame])
def import_candidates(
    scene_id: str, video_id: str, selection: Selection, request: Request, account: CurrentAccount, db: Database,
) -> list[Frame]:
    require_scene(db, account.team_id, scene_id)
    video = require_video(db, scene_id, video_id)
    ids = selection.candidate_ids
    if len(set(ids)) != len(ids):
        raise ApiError(422, "DUPLICATE_CANDIDATES", "请选择不同的候选帧。")
    candidates = list(db.scalars(get_candidates(db, video_id).where(VideoCandidate.candidate_id.in_(ids))))
    if len(candidates) != len(ids):
        raise ApiError(404, "CANDIDATE_NOT_FOUND", "未找到该候选帧。")

    require_writable_scene(db, account.team_id, scene_id)
    imported = dict(db.execute(
        select(FrameUpload.video_candidate_id, Frame).select_from(FrameUpload)
        .join(Frame, Frame.frame_id == FrameUpload.frame_id)
        .where(FrameUpload.video_candidate_id.in_(ids), FrameUpload.uploader_id == account.account_id,
               Frame.withdrawn_at.is_(None))
    ).tuples().all())
    now = datetime.now(timezone.utc)
    images = request.app.state.videos / video.video_id / "frames"
    published = []
    new_photos = {}
    try:
        for candidate in candidates:
            if candidate.candidate_id in imported:
                continue
            path = images / candidate.filename
            if not path.is_file():
                raise ApiError(404, "CANDIDATE_MISSING", "候选帧文件缺失。")
            frame, new_frame = record_frame_upload(
                db, FrameUpload(
                    upload_id=uuid4().hex, scene_id=scene_id, uploader_id=account.account_id,
                    capture_id=uuid4().hex, view_label=f"视频帧 {candidate.position}",
                    captured_at=video.created_at, created_at=now, video_candidate_id=candidate.candidate_id,
                ),
                filename=candidate.filename, digest=candidate.sha256, media_type="image/png",
                size_bytes=candidate.size_bytes, width=candidate.width, height=candidate.height,
            )
            imported[candidate.candidate_id] = frame
            if new_frame:
                new_photos[frame.sha256] = path

        db.flush()
        # Acquire cross-scene photo locks in the same order for concurrent imports.
        for digest, path in sorted(new_photos.items()):
            lock_photo_file(db, digest)
            destination = photo_path(request.app.state.photos, digest, "image/png")
            if save_image(path.read_bytes(), destination):
                published.append((digest, destination))
        db.commit()
    except (ApiError, OSError, SQLAlchemyError):
        db.rollback()
        for digest, destination in published:
            rollback_photo(db, digest, destination)
        raise
    unique = {imported[candidate_id].frame_id: imported[candidate_id] for candidate_id in ids}
    return list(unique.values())
