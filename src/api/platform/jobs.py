from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Header, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, field_serializer
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from ...workers.registration import SPLAT_RECIPES
from ..job_artifacts import ARTIFACT_TYPES
from ..models import Job, JobInput, JobKind
from .accounts import CurrentAccount, UNAUTHENTICATED
from .database import Base, Database
from .errors import ApiError, ErrorResponse, InvalidRequest
from .revision_models import Revision, RevisionFrame
from .scenes import Scene, require_scene

router = APIRouter(prefix="/api", tags=["作业"])
ACCESS_ERRORS = {**UNAUTHENTICATED, 404: {"model": ErrorResponse}}
TERMINAL = {"failed", "succeeded"}
JobStatus = Literal["queued", "running", "failed", "succeeded"]
RerunKey = Annotated[str, Header(alias="Idempotency-Key", max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]


class JobRun(Base):
    __tablename__ = "job_runs"
    __table_args__ = (
        UniqueConstraint("revision_id", "kind", "run_number", name="uq_job_runs_run_number"),
        UniqueConstraint("revision_id", "kind", "recipe_version", "request_key", name="uq_job_runs_request"),
        CheckConstraint("kind IN ('depth', 'fusion', 'splat')", name="ck_job_runs_kind"),
        CheckConstraint("status IN ('queued', 'running', 'failed', 'succeeded')", name="ck_job_runs_status"),
        Index("ix_job_runs_queue", "status", "lease_until", "created_at"),
    )

    job_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    revision_id: Mapped[str] = mapped_column(ForeignKey("revisions.revision_id"))
    submitter_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"))
    kind: Mapped[JobKind] = mapped_column(String(12))
    recipe_version: Mapped[str] = mapped_column(String(128))
    run_number: Mapped[int]
    request_key: Mapped[str] = mapped_column(String(134))
    rerun_of_id: Mapped[str | None] = mapped_column(ForeignKey("job_runs.job_id"))
    status: Mapped[JobStatus] = mapped_column(String(12))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt: Mapped[int]
    lease_token_hash: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(500))
    result: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    artifact_directory: Mapped[str | None] = mapped_column(String(32))

    @property
    def registration(self):
        return (self.result or {}).get("registration")

    @property
    def artifacts(self):
        return (self.result or {}).get("artifacts", [])


class TeamJob(Job):
    model_config = ConfigDict(from_attributes=True)
    submitter_id: str
    run_number: int
    rerun_of_id: str | None
    finished_at: datetime | None

    @field_serializer("created_at", "finished_at")
    def serialize_times(self, value: datetime | None) -> datetime | None:
        return value.astimezone(timezone.utc) if value is not None else None


class CurrentResults(BaseModel):
    revision_id: str
    depth: TeamJob | None = None
    fusion: TeamJob | None = None
    splat: TeamJob | None = None


def find_revision(db: Session, team_id: str, revision_id: str, *, lock: bool = False) -> Revision:
    query = select(Revision).join(Scene).where(Revision.revision_id == revision_id, Scene.team_id == team_id)
    revision = db.scalar(query.with_for_update(of=Revision) if lock else query)
    if revision is None:
        raise ApiError(404, "REVISION_NOT_FOUND", "未找到批次。")
    return revision


def find_team_job(db: Session, team_id: str, job_id: str) -> JobRun:
    job = db.scalar(select(JobRun).join(Revision).join(Scene).where(
        JobRun.job_id == job_id, Scene.team_id == team_id,
    ))
    if job is None:
        raise ApiError(404, "JOB_NOT_FOUND", "未找到作业。")
    return job


def validate_recipe(db: Session, job: JobInput) -> None:
    recipe = SPLAT_RECIPES.get(job.recipe_version) if job.kind == "splat" else None
    if (job.kind == "splat" and recipe is None) or (job.kind != "splat" and job.recipe_version != "v1"):
        raise ApiError(422, "UNKNOWN_RECIPE", "未知的作业配方。")
    count = db.scalar(select(func.count()).select_from(RevisionFrame).where(
        RevisionFrame.revision_id == job.revision_id,
    ))
    exact = 1 if job.kind == "depth" else recipe.required_frames if recipe else None
    if exact is not None and count != exact:
        raise ApiError(422, "FRAME_COUNT_MISMATCH", f"此作业需要 {exact} 张照片。")
    minimum = {"depth": 1, "fusion": 2, "splat": 3}[job.kind]
    if count < minimum:
        raise ApiError(422, "FRAME_COUNT_MISMATCH", f"此作业至少需要 {minimum} 张照片。")


def submit_run(
    db: Session, submitter_id: str, payload: JobInput, request_key: str, rerun_of_id: str | None = None,
) -> JobRun:
    variants = (
        JobRun.revision_id == payload.revision_id, JobRun.kind == payload.kind,
    )
    existing = db.scalar(select(JobRun).where(
        *variants, JobRun.recipe_version == payload.recipe_version, JobRun.request_key == request_key,
    ))
    if existing is not None:
        if existing.rerun_of_id != rerun_of_id:
            raise ApiError(409, "RERUN_KEY_CONFLICT", "该重跑编号已关联另一条运行记录。")
        return existing
    validate_recipe(db, payload)
    number = db.scalar(select(func.coalesce(func.max(JobRun.run_number), 0) + 1).where(*variants))
    job = JobRun(
        job_id=uuid4().hex, submitter_id=submitter_id, run_number=number, request_key=request_key,
        rerun_of_id=rerun_of_id, status="queued", attempt=0, created_at=datetime.now(timezone.utc),
        **payload.model_dump(),
    )
    db.add(job)
    db.commit()
    return job


@router.post("/jobs", status_code=202, response_model=TeamJob,
             responses={**ACCESS_ERRORS, 422: {"model": ErrorResponse | InvalidRequest}})
def create_job(payload: JobInput, account: CurrentAccount, db: Database) -> JobRun:
    find_revision(db, account.team_id, payload.revision_id, lock=True)
    return submit_run(db, account.account_id, payload, "initial")


@router.post("/jobs/{job_id}/rerun", status_code=202, response_model=TeamJob,
             responses={**ACCESS_ERRORS, 409: {"model": ErrorResponse},
                        422: {"model": ErrorResponse | InvalidRequest}})
def rerun(job_id: str, idempotency_key: RerunKey, account: CurrentAccount, db: Database) -> JobRun:
    original = find_team_job(db, account.team_id, job_id)
    find_revision(db, account.team_id, original.revision_id, lock=True)
    payload = JobInput(revision_id=original.revision_id, kind=original.kind, recipe_version=original.recipe_version)
    return submit_run(db, account.account_id, payload, "rerun:" + idempotency_key, original.job_id)


@router.get("/jobs/{job_id}", response_model=TeamJob, responses=ACCESS_ERRORS)
def get_job(job_id: str, account: CurrentAccount, db: Database) -> JobRun:
    return find_team_job(db, account.team_id, job_id)


@router.get("/scenes/{scene_id}/jobs", response_model=list[TeamJob], responses=ACCESS_ERRORS)
def list_jobs(scene_id: str, account: CurrentAccount, db: Database) -> list[JobRun]:
    require_scene(db, account.team_id, scene_id)
    query = select(JobRun).join(Revision).where(Revision.scene_id == scene_id)
    return list(db.scalars(query.order_by(JobRun.created_at.desc(), JobRun.job_id.desc())))


@router.get("/scenes/{scene_id}/revisions/{revision_id}/results", response_model=CurrentResults,
            responses=ACCESS_ERRORS)
def current_results(scene_id: str, revision_id: str, account: CurrentAccount, db: Database) -> CurrentResults:
    revision = find_revision(db, account.team_id, revision_id)
    if revision.scene_id != scene_id:
        raise ApiError(404, "REVISION_NOT_FOUND", "未找到批次。")
    successful = select(JobRun).where(JobRun.revision_id == revision_id, JobRun.status == "succeeded")
    rows = db.scalars(successful.distinct(JobRun.kind).order_by(JobRun.kind, JobRun.run_number.desc()))
    return CurrentResults(revision_id=revision_id, **{row.kind: TeamJob.model_validate(row) for row in rows})


@router.get("/artifacts/{job_id}/{filename}", response_class=FileResponse, responses=ACCESS_ERRORS)
def download(job_id: str, filename: str, request: Request, account: CurrentAccount, db: Database) -> FileResponse:
    job = find_team_job(db, account.team_id, job_id)
    if job.status != "succeeded" or filename not in {item["filename"] for item in job.artifacts}:
        raise ApiError(404, "ARTIFACT_NOT_FOUND", "未找到该产物。")
    path = request.app.state.artifacts / job.artifact_directory / filename
    db.rollback()
    if path.resolve() != path or not path.is_file():
        raise ApiError(404, "ARTIFACT_NOT_FOUND", "产物文件缺失。")
    return FileResponse(path, media_type=ARTIFACT_TYPES.get(filename, "image/jpeg"), filename=filename,
                        headers={"X-Content-Type-Options": "nosniff"})
