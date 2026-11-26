import json
import logging
import os
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse

from ..workers.registration import ExecutionError
from .images import photo_path
from .job_artifacts import ARTIFACT_TYPES, prepare_result
from .models import Job
from .store import Storage, job_record
from .worker_protocol import ERRORS, LEASE, MAX_ATTEMPTS, ClaimInput, FailureInput, LeaseInput, token_hash

router = APIRouter()
logger = logging.getLogger(__name__)


def worker_access(request: Request, x_worker_token: str | None = Header(default=None)):
    expected = os.environ.get("SPATIAL_WORKER_TOKEN")
    if expected:
        if not secrets.compare_digest(expected.encode(), (x_worker_token or "").encode()):
            raise HTTPException(401, "Worker 凭据无效")
    elif request.client is None or request.client.host not in {"127.0.0.1", "::1"}:
        raise HTTPException(401, "远程 Worker 需要凭据")


def load_job(db, job_id):
    row = db.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "未找到该作业")
    return row


def same_token(row, token):
    return secrets.compare_digest(row["lease_token_hash"] or "", token_hash(token))


def check_lease(row, token):
    if (row["status"] != "running" or not same_token(row, token)
            or not row["lease_until"] or row["lease_until"] <= datetime.now(timezone.utc).isoformat()):
        raise HTTPException(409, "作业租约已失效")


def batch_frames(db, revision_id):
    row = db.execute("SELECT frame_ids FROM revisions WHERE revision_id = ?", (revision_id,)).fetchone()
    ids = json.loads(row["frame_ids"])
    placeholders = ",".join("?" for _ in ids)
    indexed = {
        frame["frame_id"]: frame
        for frame in db.execute(f"SELECT * FROM frames WHERE frame_id IN ({placeholders})", ids)
    }
    return [indexed[frame_id] for frame_id in ids]


@router.post("/api/internal/workers/claim", dependencies=[Depends(worker_access)])
def claim(storage: Storage, payload: ClaimInput = ClaimInput()):
    with storage.connection(write=True) as db:
        now = datetime.now(timezone.utc)
        db.execute("""
            UPDATE jobs SET status = 'failed', error_code = 'LEASE_EXPIRED',
                error_message = 'Worker 租约已超时且达到自动尝试上限。', lease_token_hash = NULL, lease_until = NULL
            WHERE status = 'running' AND lease_until <= ? AND attempt >= ?
        """, (now.isoformat(), MAX_ATTEMPTS))
        placeholders = ",".join("?" for _ in payload.kinds)
        row = db.execute(f"""
            SELECT * FROM jobs WHERE kind IN ({placeholders})
                AND (status = 'queued' OR (status = 'running' AND lease_until <= ?))
            ORDER BY (kind = 'splat'), created_at, job_id LIMIT 1
        """, (*payload.kinds, now.isoformat())).fetchone()
        if row is None:
            return Response(status_code=204)
        token = secrets.token_urlsafe(32)
        attempt = row["attempt"] + 1
        db.execute("""
            UPDATE jobs SET status = 'running', attempt = ?, lease_token_hash = ?, lease_until = ?,
                error_code = NULL, error_message = NULL WHERE job_id = ?
        """, (attempt, token_hash(token), (now + LEASE).isoformat(), row["job_id"]))
        frames = batch_frames(db, row["revision_id"])
    return {
        "job_id": row["job_id"], "recipe_version": row["recipe_version"], "kind": row["kind"],
        "lease_token": token, "lease_seconds": int(LEASE.total_seconds()), "attempt": attempt,
        "frames": [{
            "frame_id": frame["frame_id"], "sha256": frame["sha256"],
            "view_label": frame["view_label"], "width": frame["width"], "height": frame["height"],
            "filename": photo_path(storage.photos, frame["sha256"], frame["media_type"]).name,
        } for frame in frames],
    }


@router.post("/api/internal/jobs/{job_id}/heartbeat", status_code=204, dependencies=[Depends(worker_access)])
def heartbeat(job_id: str, payload: LeaseInput, storage: Storage):
    with storage.connection(write=True) as db:
        check_lease(load_job(db, job_id), payload.lease_token)
        until = (datetime.now(timezone.utc) + LEASE).isoformat()
        db.execute("UPDATE jobs SET lease_until = ? WHERE job_id = ?", (until, job_id))


def fail_job(db, job_id, code, message, coverage=None):
    result = json.dumps({"registration": coverage}) if coverage is not None else None
    db.execute("""
        UPDATE jobs SET status = 'failed', error_code = ?, error_message = ?, result_json = ?,
            lease_until = NULL WHERE job_id = ?
    """, (code, message, result, job_id))


@router.post("/api/internal/jobs/{job_id}/fail", status_code=204, dependencies=[Depends(worker_access)])
def fail_execution(job_id: str, payload: FailureInput, storage: Storage):
    with storage.connection(write=True) as db:
        row = load_job(db, job_id)
        if row["status"] == "failed" and same_token(row, payload.lease_token):
            return
        check_lease(row, payload.lease_token)
        code = payload.error_code if payload.error_code in ERRORS else "EXECUTOR_ERROR"
        coverage = payload.coverage
        if coverage is not None:
            ids = [frame["frame_id"] for frame in batch_frames(db, row["revision_id"])]
            missing = set(coverage.unregistered_frame_ids)
            if (row["kind"] != "splat" or coverage.total_images != len(ids)
                    or coverage.registered_images != len(ids) - len(missing)
                    or len(missing) != len(coverage.unregistered_frame_ids) or not missing.issubset(ids)):
                raise HTTPException(422, "失败报告的配准统计与输入批次不匹配")
        fail_job(db, job_id, code, payload.error_message or ERRORS[code], coverage.model_dump() if coverage else None)


@router.post("/api/internal/jobs/{job_id}/complete", response_model=Job, dependencies=[Depends(worker_access)])
def complete(job_id: str, payload: LeaseInput, storage: Storage):
    with storage.connection() as db:
        row = load_job(db, job_id)
        if row["status"] in {"succeeded", "failed"} and same_token(row, payload.lease_token):
            return job_record(row)
        check_lease(row, payload.lease_token)
        frames = batch_frames(db, row["revision_id"])

    output = storage.staging / job_id / f"attempt-{row['attempt']}" / "out"
    with TemporaryDirectory(dir=storage.artifacts) as temporary:
        snapshot = Path(temporary) / "result"
        snapshot.mkdir()
        try:
            if output.resolve() != output:
                raise ExecutionError("INVALID_ARTIFACT", "作业产物目录无效。")
            result = prepare_result(output, snapshot, frames, row)
        except ExecutionError as error:
            with storage.connection(write=True) as db:
                latest = load_job(db, job_id)
                if latest["status"] in {"succeeded", "failed"} and same_token(latest, payload.lease_token):
                    return job_record(latest)
                check_lease(latest, payload.lease_token)
                fail_job(db, job_id, error.code, str(error), error.coverage)
                return job_record(load_job(db, job_id))

        destination = storage.artifacts / uuid4().hex
        try:
            with storage.connection(write=True) as db:
                latest = load_job(db, job_id)
                if latest["status"] in {"succeeded", "failed"} and same_token(latest, payload.lease_token):
                    return job_record(latest)
                check_lease(latest, payload.lease_token)
                snapshot.rename(destination)
                db.execute("""
                    UPDATE jobs SET status = 'succeeded', result_json = ?, artifact_directory = ?,
                        lease_until = NULL WHERE job_id = ?
                """, (json.dumps(result), destination.name, job_id))
                return job_record(load_job(db, job_id))
        except Exception:
            if destination.is_dir():
                try:
                    with storage.connection() as db:
                        if load_job(db, job_id)["artifact_directory"] != destination.name:
                            shutil.rmtree(destination)
                except Exception:
                    logger.exception("Could not clean up 3DGS output for job %s", job_id)
            raise


@router.get("/api/artifacts/{job_id}/{filename}")
def download(job_id: str, filename: str, storage: Storage):
    with storage.connection() as db:
        job = job_record(load_job(db, job_id))
    files = {artifact["filename"] for artifact in job.get("artifacts", [])}
    if job["status"] != "succeeded" or filename not in files:
        raise HTTPException(404, "未找到该产物")
    path = storage.artifacts / job["artifact_directory"] / filename
    if not path.is_file():
        raise HTTPException(404, "产物文件缺失")
    return FileResponse(
        path,
        media_type=ARTIFACT_TYPES.get(filename, "image/jpeg"),
        filename=filename,
        headers={"X-Content-Type-Options": "nosniff"},
    )
