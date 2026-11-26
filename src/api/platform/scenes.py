from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter
from pydantic import ConfigDict, field_serializer
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, String, select
from sqlalchemy.orm import Mapped, mapped_column

from ..models import Scene as SceneResponse
from ..models import SceneInput, SceneSource
from .accounts import CurrentAccount, UNAUTHENTICATED
from .database import Base, Database
from .errors import ApiError, ErrorResponse, InvalidRequest

router = APIRouter(prefix="/api/scenes", tags=["场景"])


class Scene(Base):
    __tablename__ = "scenes"
    __table_args__ = (
        CheckConstraint("source IN ('sample', 'robot', 'simulation')", name="ck_scenes_source"),
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


class TeamScene(SceneResponse):
    model_config = ConfigDict(from_attributes=True)
    team_id: str
    owner_id: str

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime) -> datetime:
        return value.astimezone(timezone.utc)


@router.get("", response_model=list[TeamScene], responses=UNAUTHENTICATED)
def list_scenes(account: CurrentAccount, db: Database) -> list[Scene]:
    query = select(Scene).where(Scene.team_id == account.team_id).order_by(Scene.created_at.desc(), Scene.scene_id.desc())
    return list(db.scalars(query))


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
    scene = db.scalar(select(Scene).where(Scene.scene_id == scene_id, Scene.team_id == account.team_id))
    if scene is None:
        raise ApiError(404, "SCENE_NOT_FOUND", "未找到场景。")
    return scene
