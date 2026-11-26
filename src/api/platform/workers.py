import logging
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ...workers.registration import ExecutionError
from ..images import photo_path
from ..job_artifacts import prepare_result
from ..models import JobKind
from ..worker_protocol import ERRORS, LEASE, MAX_ATTEMPTS, ClaimInput, FailureInput, LeaseInput, token_hash
from .database import Database
from .errors import ApiError
from .frames import Frame
from .jobs import TERMINAL, JobRun, TeamJob
from .revision_models import RevisionFrame

router = APIRouter(prefix="/api/internal", tags=["Worker"])
logger = logging.getLogger(__name__)
worker_token_header = APIKeyHeader(name="X-Worker-Token", auto_error=False)


class ClaimedFrame(BaseModel):
    frame_id: str
    sha256: str
    filename: str
    view_label: str
    width: int
    height: int


class ClaimedJob(BaseModel):
    job_id: str
    recipe_version: str
    kind: JobKind
    lease_token: str
    lease_seconds: int
    attempt: int
    frames: list[ClaimedFrame]


def worker_access(request: Request, x_worker_token: Annotated[str | None, Depends(worker_token_header)]) -> None:
    expected = request.app.state.worker_token
    if not expected or not secrets.compare_digest(expected.encode(), (x_worker_token or "").encode()):
        raise ApiError(401, "INVALID_WORKER_TOKEN", "Worker 凭据无效。")


def batch_frames(db: Session, revision_id: str, photos: Path) -> list[dict]:
    query = (select(Frame).join(RevisionFrame, RevisionFrame.frame_id == Frame.frame_id)
             .where(RevisionFrame.revision_id == revision_id).order_by(RevisionFrame.position))
    return [
        dict(
            frame_id=frame.frame_id, sha256=frame.sha256, view_label=frame.view_label,
            width=frame.width, height=frame.height,
            filename=photo_path(photos, frame.sha256, frame.media_type).name,
        )
        for frame in db.scalars(query)
    ]


def load_job(db: Session, job_id: str, *, lock: bool = False) -> JobRun:
    query = select(JobRun).where(JobRun.job_id == job_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    job = db.scalar(query)
    if job is None:
        raise ApiError(404, "JOB_NOT_FOUND", "未找到作业。")
    return job


def same_token(job: JobRun, token: str) -> bool:
    return secrets.compare_digest(job.lease_token_hash or "", token_hash(token))


def require_lease(job: JobRun, token: str) -> None:
    if (job.status != "running" or not same_token(job, token)
            or job.lease_until is None or job.lease_until <= datetime.now(timezone.utc)):
        raise ApiError(409, "LEASE_LOST", "作业租约已失效。")


@router.post("/workers/claim", response_model=ClaimedJob, responses={204: {"description": "暂无作业"}},
             dependencies=[Depends(worker_access)])
def claim(request: Request, db: Database, payload: ClaimInput = ClaimInput()) -> ClaimedJob | Response:
    now = datetime.now(timezone.utc)
    expired = and_(JobRun.status == "running", JobRun.lease_until <= now)
    exhausted = select(JobRun.job_id).where(expired, JobRun.attempt >= MAX_ATTEMPTS).with_for_update(skip_locked=True)
    db.execute(update(JobRun).where(JobRun.job_id.in_(exhausted)).values(
        status="failed", error_code="LEASE_EXPIRED", error_message="Worker 租约已超时且达到自动尝试上限。",
        finished_at=now, lease_token_hash=None, lease_until=None,
    ).execution_options(synchronize_session=False))
    job = db.scalar(select(JobRun).where(
        JobRun.kind.in_(payload.kinds), or_(JobRun.status == "queued", and_(expired, JobRun.attempt < MAX_ATTEMPTS)),
    ).order_by(JobRun.kind == "splat", JobRun.created_at, JobRun.job_id).limit(1).with_for_update(skip_locked=True))
    if job is None:
        db.commit()
        return Response(status_code=204)

    token = secrets.token_urlsafe(32)
    job.status = "running"
    job.attempt += 1
    job.lease_token_hash = token_hash(token)
    job.lease_until = now + LEASE
    result = ClaimedJob(
        job_id=job.job_id, recipe_version=job.recipe_version, kind=job.kind, lease_token=token,
        lease_seconds=int(LEASE.total_seconds()), attempt=job.attempt,
        frames=batch_frames(db, job.revision_id, request.app.state.photos),
    )
    db.commit()
    return result


@router.post("/jobs/{job_id}/heartbeat", status_code=204, dependencies=[Depends(worker_access)])
def heartbeat(job_id: str, payload: LeaseInput, db: Database) -> Response:
    job = load_job(db, job_id, lock=True)
    require_lease(job, payload.lease_token)
    job.lease_until = datetime.now(timezone.utc) + LEASE
    db.commit()
    return Response(status_code=204)


def fail_run(job: JobRun, code: str, message: str, coverage=None) -> None:
    job.status = "failed"
    job.error_code = code
    job.error_message = message
    job.result = {"registration": coverage} if coverage is not None else None
    job.lease_until = None
    job.finished_at = datetime.now(timezone.utc)


@router.post("/jobs/{job_id}/fail", status_code=204, dependencies=[Depends(worker_access)])
def fail_execution(job_id: str, payload: FailureInput, request: Request, db: Database) -> Response:
    job = load_job(db, job_id, lock=True)
    if job.status == "failed" and same_token(job, payload.lease_token):
        return Response(status_code=204)
    require_lease(job, payload.lease_token)
    coverage = payload.coverage
    if coverage is not None:
        ids = [frame["frame_id"] for frame in batch_frames(db, job.revision_id, request.app.state.photos)]
        missing = set(coverage.unregistered_frame_ids)
        if (job.kind != "splat" or coverage.total_images != len(ids)
                or coverage.registered_images != len(ids) - len(missing)
                or len(missing) != len(coverage.unregistered_frame_ids) or not missing.issubset(ids)):
            raise ApiError(422, "INVALID_COVERAGE", "失败报告的配准统计与输入批次不匹配。")
    code = payload.error_code if payload.error_code in ERRORS else "EXECUTOR_ERROR"
    fail_run(job, code, payload.error_message or ERRORS[code], coverage.model_dump() if coverage else None)
    db.commit()
    return Response(status_code=204)


@router.post("/jobs/{job_id}/complete", response_model=TeamJob, dependencies=[Depends(worker_access)])
def complete(job_id: str, payload: LeaseInput, request: Request, db: Database) -> JobRun:
    token = payload.lease_token
    job = load_job(db, job_id)
    if job.status in TERMINAL and same_token(job, token):
        return job
    require_lease(job, token)
    frames = batch_frames(db, job.revision_id, request.app.state.photos)
    metadata = dict(job_id=job.job_id, revision_id=job.revision_id, recipe_version=job.recipe_version, kind=job.kind)
    output = request.app.state.staging / job_id / f"attempt-{job.attempt}" / "out"
    artifact_root = request.app.state.artifacts
    db.commit()

    with TemporaryDirectory(dir=artifact_root) as temporary:
        snapshot = Path(temporary) / "result"
        snapshot.mkdir()
        failure = None
        try:
            if output.resolve() != output:
                raise ExecutionError("INVALID_ARTIFACT", "作业产物目录无效。")
            result = prepare_result(output, snapshot, frames, metadata)
        except ExecutionError as error:
            failure = error

        # Copy large output outside the row lock, then verify the lease again before publication.
        job = load_job(db, job_id, lock=True)
        if job.status in TERMINAL and same_token(job, token):
            return job
        require_lease(job, token)
        if failure is not None:
            fail_run(job, failure.code, str(failure), failure.coverage)
            db.commit()
            return job

        destination = artifact_root / uuid4().hex
        snapshot.rename(destination)
        job.result = result
        job.artifact_directory = destination.name
        job.status = "succeeded"
        job.finished_at = datetime.now(timezone.utc)
        job.lease_until = None
        try:
            db.commit()
        except SQLAlchemyError:
            db.rollback()
            try:
                # Preserve the file if the database accepted the commit before the connection failed.
                if load_job(db, job_id).artifact_directory != destination.name:
                    shutil.rmtree(destination)
            except (SQLAlchemyError, OSError, ApiError):
                logger.exception("Could not reconcile publication for job %s", job_id)
            raise
    return job
