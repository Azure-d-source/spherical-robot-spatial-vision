import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

from fastapi import APIRouter, Response
from pydantic import ConfigDict, field_serializer
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ...workers.simulation_camera import LAYOUT_PATTERN
from ..models import Revision as RevisionResponse
from ..models import RevisionInput
from .accounts import CurrentAccount, UNAUTHENTICATED
from .database import Database
from .errors import ApiError, ErrorResponse, InvalidRequest
from .frames import Frame, FrameUpload
from .revision_models import Revision, RevisionFrame
from .scenes import require_scene, require_writable_scene
from .video_models import VideoCandidate, VideoImport, VideoSource, video_source

router = APIRouter(prefix="/api/scenes/{scene_id}/revisions", tags=["批次"])
ACCESS_ERRORS = {**UNAUTHENTICATED, 404: {"model": ErrorResponse}}
FRAME_ID = re.compile(r"[0-9a-f]{32}")


class TeamRevision(RevisionResponse):
    model_config = ConfigDict(from_attributes=True)
    creator_id: str
    video_sources: dict[str, list[VideoSource]]

    @field_serializer("created_at")
    def serialize_time(self, value: datetime) -> datetime:
        return value.astimezone(timezone.utc)


def snapshot_video_sources(db: Session, scene_id: str, ids: list[str]) -> dict[str, list[dict]]:
    query = (
        select(FrameUpload.frame_id, VideoImport, VideoCandidate).select_from(FrameUpload)
        .join(VideoCandidate, VideoCandidate.candidate_id == FrameUpload.video_candidate_id)
        .join(VideoImport, VideoImport.video_id == VideoCandidate.video_id)
        .where(FrameUpload.scene_id == scene_id, FrameUpload.frame_id.in_(ids))
        .order_by(FrameUpload.frame_id, VideoImport.video_id, VideoCandidate.position)
    )
    sources = defaultdict(dict)
    for frame_id, video, candidate in db.execute(query):
        sources[frame_id][candidate.candidate_id] = video_source(video, candidate).model_dump()
    return {frame_id: list(items.values()) for frame_id, items in sources.items()}


@router.get("", response_model=list[TeamRevision], responses=ACCESS_ERRORS)
def list_revisions(scene_id: str, account: CurrentAccount, db: Database) -> list[Revision]:
    require_scene(db, account.team_id, scene_id)
    query = select(Revision).where(Revision.scene_id == scene_id).options(selectinload(Revision.frames))
    return list(db.scalars(query.order_by(Revision.version.desc())))


@router.get("/{revision_id}", response_model=TeamRevision, responses=ACCESS_ERRORS)
def get_revision(scene_id: str, revision_id: str, account: CurrentAccount, db: Database) -> Revision:
    require_scene(db, account.team_id, scene_id)
    revision = db.scalar(
        select(Revision).where(Revision.scene_id == scene_id, Revision.revision_id == revision_id)
        .options(selectinload(Revision.frames))
    )
    if revision is None:
        raise ApiError(404, "REVISION_NOT_FOUND", "未找到批次。")
    return revision


@router.post("", response_model=TeamRevision, status_code=201, responses={
    **ACCESS_ERRORS, 200: {"model": TeamRevision, "description": "复用已有批次"},
    409: {"model": ErrorResponse}, 422: {"model": ErrorResponse | InvalidRequest},
})
def create_revision(
    scene_id: str, payload: RevisionInput, response: Response, account: CurrentAccount, db: Database,
) -> Revision:
    ids = payload.frame_ids
    if len(ids) != len(set(ids)) or not all(FRAME_ID.fullmatch(frame_id) for frame_id in ids):
        raise ApiError(422, "INVALID_FRAME_IDS", "请提交有效且不重复的照片编号。")

    # Keep numbering and identical-list retries consistent with concurrent writes.
    require_writable_scene(db, account.team_id, scene_id)
    sources = snapshot_video_sources(db, scene_id, ids)
    # Preserve fingerprints for old photo-only batches. New links produce a new immutable snapshot.
    identity = json.dumps([ids, sources], sort_keys=True) if sources else "".join(ids)
    fingerprint = sha256(identity.encode("ascii")).hexdigest()
    existing = db.scalar(
        select(Revision).where(Revision.scene_id == scene_id, Revision.fingerprint == fingerprint)
        .options(selectinload(Revision.frames))
    )
    if existing is not None:
        if existing.frame_ids != ids or existing.video_sources != sources:
            raise ApiError(409, "REVISION_FINGERPRINT_CONFLICT", "批次标识冲突。")
        response.status_code = 200
        return existing

    photos = list(db.scalars(
        select(Frame).where(Frame.scene_id == scene_id, Frame.frame_id.in_(ids))
        .order_by(Frame.frame_id).with_for_update()
    ))
    if len(photos) != len(ids):
        raise ApiError(422, "FRAME_OUTSIDE_SCENE", "所选照片须全部来自当前场景。")
    if any(frame.withdrawn_at is not None for frame in photos):
        raise ApiError(409, "FRAME_WITHDRAWN", "有照片已被撤下，请重新选图。")
    layouts = {match[1] if (match := LAYOUT_PATTERN.match(frame.view_label)) else None for frame in photos}
    if len(layouts) > 1:
        raise ApiError(422, "MIXED_LAYOUTS", "请按仿真布局分别确认批次。")

    next_version = db.scalar(select(func.coalesce(func.max(Revision.version), 0) + 1)
                             .where(Revision.scene_id == scene_id))
    revision = Revision(
        revision_id=uuid4().hex, scene_id=scene_id, creator_id=account.account_id,
        version=next_version, fingerprint=fingerprint, created_at=datetime.now(timezone.utc),
        frames=[RevisionFrame(frame_id=frame_id, position=position, video_sources=sources.get(frame_id))
                for position, frame_id in enumerate(ids)],
    )
    db.add(revision)
    db.commit()
    return revision
