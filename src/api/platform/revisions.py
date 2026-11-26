import re
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

from fastapi import APIRouter, Response
from pydantic import ConfigDict, field_serializer
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from ...workers.simulation_camera import LAYOUT_PATTERN
from ..models import Revision as RevisionResponse
from ..models import RevisionInput
from .accounts import CurrentAccount, UNAUTHENTICATED
from .database import Database
from .errors import ApiError, ErrorResponse, InvalidRequest
from .frames import Frame
from .revision_models import Revision, RevisionFrame
from .scenes import require_scene, require_writable_scene

router = APIRouter(prefix="/api/scenes/{scene_id}/revisions", tags=["批次"])
ACCESS_ERRORS = {**UNAUTHENTICATED, 404: {"model": ErrorResponse}}
FRAME_ID = re.compile(r"[0-9a-f]{32}")


class TeamRevision(RevisionResponse):
    model_config = ConfigDict(from_attributes=True)
    creator_id: str

    @field_serializer("created_at")
    def serialize_time(self, value: datetime) -> datetime:
        return value.astimezone(timezone.utc)


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
    fingerprint = sha256("".join(ids).encode("ascii")).hexdigest()
    existing = db.scalar(
        select(Revision).where(Revision.scene_id == scene_id, Revision.fingerprint == fingerprint)
        .options(selectinload(Revision.frames))
    )
    if existing is not None:
        if existing.frame_ids != ids:
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
        frames=[RevisionFrame(frame_id=frame_id, position=position)
                for position, frame_id in enumerate(ids)],
    )
    db.add(revision)
    db.commit()
    return revision
