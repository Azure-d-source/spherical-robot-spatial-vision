import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import PureWindowsPath
from typing import Annotated
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import store
from .images import UploadLimit, photo_path, read_image, save_image
from .models import Frame, Job, JobInput, Revision, RevisionInput, Scene, SceneDetail, SceneInput


def timestamp():
    return datetime.now(timezone.utc).isoformat()


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.initialize()
    yield


app = FastAPI(title="绕物成景 · 空间视觉 API", version="0.1.0", lifespan=lifespan)
app.add_middleware(UploadLimit)


@app.get("/api/health", tags=["系统"])
def health():
    with store.connection() as db:
        db.execute("SELECT scene_id FROM scenes LIMIT 1").fetchone()
    return {"status": "ok"}


@app.get("/api/scenes", response_model=list[Scene], tags=["场景"])
def scenes():
    with store.connection() as db:
        return [dict(row) for row in db.execute("SELECT * FROM scenes ORDER BY created_at DESC, rowid DESC")]


@app.post("/api/scenes", status_code=201, response_model=Scene, tags=["场景"])
def create_scene(payload: SceneInput):
    scene = dict(scene_id=uuid4().hex, created_at=timestamp(), **payload.model_dump())
    with store.connection(write=True) as db:
        db.execute("""
            INSERT INTO scenes (scene_id, title, source, target, created_at)
            VALUES (:scene_id, :title, :source, :target, :created_at)
        """, scene)
    return scene


@app.get("/api/scenes/{scene_id}", response_model=SceneDetail, tags=["场景"])
def get_scene(scene_id: str):
    with store.connection() as db:
        return {
            **store.scene_record(db, scene_id),
            "frames": store.list_frames(db, scene_id),
            "revisions": store.list_revisions(db, scene_id),
            "jobs": store.list_jobs(db, scene_id),
        }


@app.get("/api/scenes/{scene_id}/frames", response_model=list[Frame], tags=["照片"])
def frames(scene_id: str):
    with store.connection() as db:
        store.scene_record(db, scene_id)
        return store.list_frames(db, scene_id)


@app.post("/api/scenes/{scene_id}/frames", status_code=201, response_model=Frame, tags=["照片"])
def upload_frame(
    scene_id: str,
    response: Response,
    image: Annotated[UploadFile, File()],
    view_label: Annotated[str, Form(min_length=1, max_length=120)],
    capture_id: Annotated[str | None, Form(max_length=128)] = None,
    captured_at: Annotated[datetime | None, Form()] = None,
):
    view_label = view_label.strip()
    if not view_label or (capture_id is not None and not capture_id.strip()):
        raise HTTPException(422, "机位名称和采集编号须包含有效字符")
    capture_id = capture_id.strip() if capture_id else None
    with store.connection() as db:
        store.scene_record(db, scene_id)
    data, digest, media_type, width, height = read_image(image)
    with store.connection(write=True) as db:
        previous = db.execute("""
            SELECT f.* FROM captures c JOIN frames f ON c.frame_id = f.frame_id
            WHERE c.scene_id = ? AND c.capture_id = ?
        """, (scene_id, capture_id)).fetchone()
        if previous is not None:
            if previous["sha256"] != digest:
                raise HTTPException(409, "该采集编号已关联另一张照片")
            response.status_code = 200
            return store.frame_record(previous)

        existing = db.execute("SELECT * FROM frames WHERE scene_id = ? AND sha256 = ?", (scene_id, digest)).fetchone()
        if existing is not None:
            if capture_id:
                db.execute("INSERT INTO captures VALUES (?, ?, ?)", (scene_id, capture_id, existing["frame_id"]))
            response.status_code = 200
            return store.frame_record(existing)

        frame_id = uuid4().hex
        capture_id = capture_id or uuid4().hex
        now = timestamp()
        name = PureWindowsPath(image.filename or "").name[:255] or "photo"
        time_taken = captured_at.isoformat() if captured_at is not None else now
        record = dict(frame_id=frame_id, scene_id=scene_id, capture_id=capture_id, filename=name,
                      view_label=view_label, captured_at=time_taken, created_at=now, sha256=digest,
                      media_type=media_type, size_bytes=len(data), width=width, height=height)
        save_image(data, digest, media_type)
        db.execute("""
            INSERT INTO frames (frame_id, scene_id, capture_id, filename, view_label, captured_at,
                                created_at, sha256, media_type, size_bytes, width, height)
            VALUES (:frame_id, :scene_id, :capture_id, :filename, :view_label, :captured_at,
                    :created_at, :sha256, :media_type, :size_bytes, :width, :height)
        """, record)
        db.execute("INSERT INTO captures VALUES (?, ?, ?)", (scene_id, capture_id, frame_id))
        return store.frame_record(record)


@app.get("/api/frames/{frame_id}/image", response_class=FileResponse, tags=["照片"])
def get_image(frame_id: str):
    with store.connection() as db:
        row = db.execute("SELECT sha256, media_type FROM frames WHERE frame_id = ?", (frame_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "未找到该照片")
    path = photo_path(row["sha256"], row["media_type"])
    if not path.is_file():
        raise HTTPException(404, "原图文件缺失")
    return FileResponse(path, media_type=row["media_type"], headers={"X-Content-Type-Options": "nosniff"})


@app.get("/api/scenes/{scene_id}/revisions", response_model=list[Revision], tags=["批次"])
def revisions(scene_id: str):
    with store.connection() as db:
        store.scene_record(db, scene_id)
        return store.list_revisions(db, scene_id)


@app.post("/api/scenes/{scene_id}/revisions", status_code=201, response_model=Revision, tags=["批次"])
def create_revision(scene_id: str, payload: RevisionInput, response: Response):
    ids = payload.frame_ids
    if len(ids) != len(set(ids)):
        raise HTTPException(422, "同一批次里出现了重复照片")
    frozen = json.dumps(ids, separators=(",", ":"))
    with store.connection(write=True) as db:
        store.scene_record(db, scene_id)
        existing = db.execute("SELECT * FROM revisions WHERE scene_id = ? AND frame_ids = ?", (scene_id, frozen)).fetchone()
        if existing is not None:
            response.status_code = 200
            return store.revision_record(existing)
        placeholders = ",".join("?" for _ in ids)
        count = db.execute(f"SELECT count(*) FROM frames WHERE scene_id = ? AND frame_id IN ({placeholders})",
                           (scene_id, *ids)).fetchone()[0]
        if count != len(ids):
            raise HTTPException(422, "所选照片须全部来自当前场景")
        version = db.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM revisions WHERE scene_id = ?",
                             (scene_id,)).fetchone()[0]
        revision_id = uuid4().hex
        now = timestamp()
        db.execute("INSERT INTO revisions (revision_id, scene_id, version, frame_ids, created_at) VALUES (?, ?, ?, ?, ?)",
                   (revision_id, scene_id, version, frozen, now))
    return dict(revision_id=revision_id, scene_id=scene_id, version=version, frame_ids=ids, created_at=now)


@app.get("/api/scenes/{scene_id}/jobs", response_model=list[Job], tags=["作业"])
def scene_jobs(scene_id: str):
    with store.connection() as db:
        store.scene_record(db, scene_id)
        return store.list_jobs(db, scene_id)


@app.post("/api/jobs", status_code=202, response_model=Job, tags=["作业"])
def submit_job(payload: JobInput):
    """Persist a queued job. GPU workers will consume the queue in a later integration."""
    with store.connection(write=True) as db:
        revision = db.execute("SELECT revision_id FROM revisions WHERE revision_id = ?", (payload.revision_id,)).fetchone()
        if revision is None:
            raise HTTPException(404, "未找到该照片批次")
        args = (payload.revision_id, payload.kind, payload.recipe_version)
        existing = db.execute("SELECT * FROM jobs WHERE revision_id = ? AND kind = ? AND recipe_version = ?", args).fetchone()
        if existing is not None:
            return dict(existing)
        job = dict(job_id=uuid4().hex, status="queued", created_at=timestamp(), **payload.model_dump())
        db.execute("""
            INSERT INTO jobs (job_id, revision_id, kind, recipe_version, status, created_at)
            VALUES (:job_id, :revision_id, :kind, :recipe_version, :status, :created_at)
        """, job)
        return job


@app.get("/api/jobs/{job_id}", response_model=Job, tags=["作业"])
def get_job(job_id: str):
    with store.connection() as db:
        row = db.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "未找到该作业")
    return dict(row)


web_dist = store.ROOT / "src" / "web" / "dist"
if (web_dist / "index.html").is_file():
    app.mount("/", StaticFiles(directory=web_dist, html=True), name="workbench")
