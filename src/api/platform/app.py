from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from threading import BoundedSemaphore
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from starlette.middleware.trustedhost import TrustedHostMiddleware

from ..web import WorkbenchFiles
from . import accounts, frames, jobs, revisions, scenes, videos, workers
from .config import LOOPBACK_HOSTS, PlatformSettings
from .database import Database
from .errors import ApiError, ErrorResponse, InvalidRequest


def create_app(settings: PlatformSettings | None = None) -> FastAPI:
    settings = settings or PlatformSettings.from_env()
    origin = urlsplit(settings.public_origin)
    if origin.hostname not in LOOPBACK_HOSTS and not (settings.worker_token or "").strip():
        raise ValueError("Set SPATIAL_WORKER_TOKEN before serving the API on a public HTTPS origin")

    def open_database():
        engine = create_engine(settings.database_url, pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                connection.execute(select(scenes.Scene.archived_at).limit(1))
                connection.execute(select(videos.VideoImport.video_id).limit(1))
        except BaseException:
            engine.dispose()
            raise
        return engine

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = await run_in_threadpool(open_database)
        app.state.sessions = sessionmaker(engine, expire_on_commit=False)
        try:
            await run_in_threadpool(app.state.photos.mkdir, parents=True, exist_ok=True)
            await run_in_threadpool(app.state.staging.mkdir, parents=True, exist_ok=True)
            await run_in_threadpool(app.state.artifacts.mkdir, parents=True, exist_ok=True)
            await run_in_threadpool(app.state.videos.mkdir, parents=True, exist_ok=True)
            yield
        finally:
            await run_in_threadpool(engine.dispose)

    app = FastAPI(title="SplatForge API", version="0.2.0", lifespan=lifespan)
    app.state.secure_cookies = origin.scheme == "https"
    app.state.worker_token = settings.worker_token
    root = settings.data_dir.resolve()
    app.state.photos = root / "photos"
    app.state.staging = root / "staging"
    app.state.artifacts = root / "artifacts"
    app.state.videos = root / "videos"
    app.state.ffmpeg = settings.ffmpeg
    app.state.video_slots = BoundedSemaphore(1)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[origin.hostname, "127.0.0.1", "localhost"])

    @app.middleware("http")
    async def browser_origin(request: Request, call_next):
        sender = request.headers.get("origin")
        if request.method in {"POST", "PATCH", "PUT", "DELETE"} and sender and sender != settings.public_origin:
            error = ErrorResponse(code="ORIGIN_FORBIDDEN", message="请求必须来自工作台地址。")
            return JSONResponse(status_code=403, content=error.model_dump())
        response = await call_next(request)
        if response.status_code == 413 and response.headers.get("content-type", "").startswith("text/plain"):
            error = ErrorResponse(code="PHOTO_LIMIT_EXCEEDED", message="上传请求超过照片大小限制。")
            response = JSONResponse(status_code=413, content=error.model_dump())
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ApiError)
    async def api_error(_request: Request, error: ApiError):
        return JSONResponse(status_code=error.status, content=error.body.model_dump())

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, error: RequestValidationError):
        result = InvalidRequest(
            code="INVALID_REQUEST", message="请求参数不符合接口要求。",
            fields=[".".join(map(str, item["loc"])) for item in error.errors()],
        )
        return JSONResponse(status_code=422, content=result.model_dump())

    @app.get("/api/health", tags=["系统"])
    def health(db: Database):
        db.execute(text("SELECT 1"))
        return {"status": "ok", "workbench": "team"}

    app.include_router(accounts.router)
    app.include_router(scenes.router)
    app.include_router(frames.router)
    app.include_router(videos.router)
    app.include_router(revisions.router)
    app.include_router(jobs.router)
    app.include_router(workers.router)
    app.mount("/", WorkbenchFiles(settings.web_dist.resolve()), name="workbench")
    return app
