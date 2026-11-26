from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, field_serializer
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from ..models import Scene as SceneResponse
from ..models import SceneInput, SceneSource, Title
from .accounts import Account, CurrentAccount, UNAUTHENTICATED
from .database import Base, Database
from .errors import ApiError, ErrorResponse, InvalidRequest

router = APIRouter(prefix="/api/scenes", tags=["场景"])
SceneStatus = Literal["active", "archived"]
MANAGEMENT_ERRORS = {
    **UNAUTHENTICATED,
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
}


class Scene(Base):
    __tablename__ = "scenes"
    __table_args__ = (
        CheckConstraint("source IN ('sample', 'robot', 'simulation')", name="ck_scenes_source"),
        CheckConstraint("(archived_at IS NULL) = (archived_by IS NULL)", name="ck_scenes_archive"),
        ForeignKeyConstraint(["team_id", "owner_id"], ["accounts.team_id", "accounts.account_id"],
                             name="fk_scenes_team_owner"),
        Index("ix_scenes_team_created", "team_id", "created_at", "scene_id"),
    )

    scene_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.team_id"))
    owner_id: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(120))
    source: Mapped[SceneSource] = mapped_column(String(12))
    target: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_by: Mapped[str | None] = mapped_column(ForeignKey("accounts.account_id", name="fk_scenes_archived_by"))

    @property
    def status(self) -> SceneStatus:
        return "archived" if self.archived_at is not None else "active"


class TeamScene(SceneResponse):
    model_config = ConfigDict(from_attributes=True)
    team_id: str
    owner_id: str
    status: SceneStatus
    archived_at: datetime | None
    archived_by: str | None

    @field_serializer("created_at", "archived_at")
    def serialize_times(self, value: datetime | None) -> datetime | None:
        return value.astimezone(timezone.utc) if value is not None else None


class RenameScene(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Title


def require_scene(db: Session, team_id: str, scene_id: str, *, for_update: bool = False) -> Scene:
    query = select(Scene).where(Scene.scene_id == scene_id, Scene.team_id == team_id)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    scene = db.scalar(query)
    if scene is None:
        raise ApiError(404, "SCENE_NOT_FOUND", "未找到场景。")
    return scene


def require_active(scene: Scene) -> None:
    if scene.archived_at is not None:
        raise ApiError(409, "SCENE_ARCHIVED", "场景已归档，恢复后才能修改。")


def require_writable_scene(db: Session, team_id: str, scene_id: str) -> Scene:
    scene = require_scene(db, team_id, scene_id, for_update=True)
    require_active(scene)
    return scene


def manageable_scene(db: Session, account: Account, scene_id: str) -> Scene:
    scene = require_scene(db, account.team_id, scene_id, for_update=True)
    if account.role != "admin" and scene.owner_id != account.account_id:
        raise ApiError(403, "SCENE_MANAGE_FORBIDDEN", "只有场景创建者或管理员可以管理场景。")
    return scene


@router.get("", response_model=list[TeamScene], responses={**UNAUTHENTICATED, 422: {"model": InvalidRequest}})
def list_scenes(account: CurrentAccount, db: Database, status: Literal["all", "active", "archived"] = "all") -> list[Scene]:
    query = select(Scene).where(Scene.team_id == account.team_id)
    if status == "active":
        query = query.where(Scene.archived_at.is_(None))
    elif status == "archived":
        query = query.where(Scene.archived_at.is_not(None))
    return list(db.scalars(query.order_by(Scene.created_at.desc(), Scene.scene_id.desc())))


@router.post("", response_model=TeamScene, status_code=201,
             responses={**UNAUTHENTICATED, 422: {"model": InvalidRequest}})
def create_scene(payload: SceneInput, account: CurrentAccount, db: Database) -> Scene:
    scene = Scene(
        scene_id=uuid4().hex, team_id=account.team_id, owner_id=account.account_id,
        created_at=datetime.now(timezone.utc), **payload.model_dump(),
    )
    db.add(scene)
    db.commit()
    return scene


@router.get("/{scene_id}", response_model=TeamScene,
            responses={**UNAUTHENTICATED, 404: {"model": ErrorResponse}})
def get_scene(scene_id: str, account: CurrentAccount, db: Database) -> Scene:
    return require_scene(db, account.team_id, scene_id)


@router.patch("/{scene_id}", response_model=TeamScene, responses={
    **MANAGEMENT_ERRORS, 409: {"model": ErrorResponse}, 422: {"model": InvalidRequest},
})
def rename_scene(scene_id: str, payload: RenameScene, account: CurrentAccount, db: Database) -> Scene:
    scene = manageable_scene(db, account, scene_id)
    require_active(scene)
    scene.title = payload.title
    db.commit()
    return scene


@router.post("/{scene_id}/archive", response_model=TeamScene, responses=MANAGEMENT_ERRORS)
def archive_scene(scene_id: str, account: CurrentAccount, db: Database) -> Scene:
    scene = manageable_scene(db, account, scene_id)
    if scene.archived_at is None:
        scene.archived_at = datetime.now(timezone.utc)
        scene.archived_by = account.account_id
    db.commit()
    return scene


@router.post("/{scene_id}/restore", response_model=TeamScene, responses=MANAGEMENT_ERRORS)
def restore_scene(scene_id: str, account: CurrentAccount, db: Database) -> Scene:
    scene = manageable_scene(db, account, scene_id)
    scene.archived_at = None
    scene.archived_by = None
    db.commit()
    return scene
