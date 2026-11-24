import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, HTTPException, Request

SCHEMA = """
CREATE TABLE IF NOT EXISTS scenes (
    scene_id TEXT PRIMARY KEY, title TEXT NOT NULL, source TEXT NOT NULL,
    target TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS frames (
    frame_id TEXT PRIMARY KEY, scene_id TEXT NOT NULL REFERENCES scenes,
    capture_id TEXT NOT NULL, filename TEXT NOT NULL, view_label TEXT NOT NULL,
    captured_at TEXT NOT NULL, created_at TEXT NOT NULL, sha256 TEXT NOT NULL,
    media_type TEXT NOT NULL, size_bytes INTEGER NOT NULL,
    width INTEGER NOT NULL, height INTEGER NOT NULL,
    UNIQUE (scene_id, sha256)
);
CREATE TABLE IF NOT EXISTS captures (
    scene_id TEXT NOT NULL REFERENCES scenes, capture_id TEXT NOT NULL,
    frame_id TEXT NOT NULL REFERENCES frames, PRIMARY KEY (scene_id, capture_id)
);
CREATE TABLE IF NOT EXISTS revisions (
    revision_id TEXT PRIMARY KEY, scene_id TEXT NOT NULL REFERENCES scenes,
    version INTEGER NOT NULL, frame_ids TEXT NOT NULL, created_at TEXT NOT NULL,
    UNIQUE (scene_id, version), UNIQUE (scene_id, frame_ids)
);
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY, revision_id TEXT NOT NULL REFERENCES revisions,
    kind TEXT NOT NULL, recipe_version TEXT NOT NULL, status TEXT NOT NULL,
    created_at TEXT NOT NULL, UNIQUE (revision_id, kind, recipe_version)
);
"""


class Store:
    def __init__(self, data_dir: Path):
        root = data_dir.resolve()
        self.database = root / "workspace.sqlite3"
        self.photos = root / "photos"
        self.staging = root / "staging"
        self.artifacts = root / "artifacts"

    @contextmanager
    def connection(self, write=False):
        db = sqlite3.connect(self.database, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def initialize(self):
        self.photos.mkdir(parents=True, exist_ok=True)
        self.staging.mkdir(exist_ok=True)
        self.artifacts.mkdir(exist_ok=True)
        db = sqlite3.connect(self.database, timeout=15)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)
        finally:
            db.close()
        with self.connection(write=True) as db:
            columns = {row["name"] for row in db.execute("PRAGMA table_info(jobs)")}
            for name, column in {
                "attempt": "INTEGER NOT NULL DEFAULT 0",
                "lease_token_hash": "TEXT",
                "lease_until": "TEXT",
                "error_code": "TEXT",
                "error_message": "TEXT",
                "result_json": "TEXT",
                "artifact_directory": "TEXT",
            }.items():
                if name not in columns:
                    db.execute(f"ALTER TABLE jobs ADD COLUMN {name} {column}")


def get_store(request: Request) -> Store:
    return request.app.state.store


Storage = Annotated[Store, Depends(get_store)]


def job_record(row):
    record = dict(row)
    stored = record.get("result_json")
    record.update(json.loads(stored) if stored else {})
    return record


def scene_record(db, scene_id):
    row = db.execute("SELECT * FROM scenes WHERE scene_id = ?", (scene_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "未找到该场景")
    return dict(row)


def frame_record(row):
    return {**dict(row), "image_url": f"/api/frames/{row['frame_id']}/image"}


def list_frames(db, scene_id):
    rows = db.execute("SELECT * FROM frames WHERE scene_id = ? ORDER BY created_at, rowid", (scene_id,))
    return [frame_record(row) for row in rows]


def revision_record(row):
    return {**dict(row), "frame_ids": json.loads(row["frame_ids"])}


def list_revisions(db, scene_id):
    rows = db.execute("SELECT * FROM revisions WHERE scene_id = ? ORDER BY version DESC", (scene_id,))
    return [revision_record(row) for row in rows]


def list_jobs(db, scene_id):
    rows = db.execute("""
        SELECT j.* FROM jobs j JOIN revisions r ON r.revision_id = j.revision_id
        WHERE r.scene_id = ? ORDER BY j.created_at DESC, j.rowid DESC
    """, (scene_id,))
    return [job_record(row) for row in rows]
