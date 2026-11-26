from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import accounts, scenes
from .config import PlatformSettings
from .database import Database
from .errors import ApiError, ErrorResponse, InvalidRequest


def create_app(settings: PlatformSettings | None = None) -> FastAPI:
    settings = settings or PlatformSettings.from_env()
    origin = urlsplit(settings.public_origin)

    def open_database():
        engine = create_engine(settings.database_url, pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                connection.execute(select(accounts.Team.team_id).limit(1))
        except BaseException:
            engine.dispose()
            raise
        return engine

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = await run_in_threadpool(open_database)
        app.state.sessions = sessionmaker(engine, expire_on_commit=False)
        try:
            yield
        finally:
            await run_in_threadpool(engine.dispose)

    app = FastAPI(title="OrbitForge API", version="0.2.0", lifespan=lifespan)
    app.state.secure_cookies = origin.scheme == "https"
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[origin.hostname])

    @app.middleware("http")
    async def browser_origin(request: Request, call_next):
        sender = request.headers.get("origin")
        if request.method in {"POST", "PATCH", "PUT", "DELETE"} and sender and sender != settings.public_origin:
            error = ErrorResponse(code="ORIGIN_FORBIDDEN", message="请求必须来自工作台地址。")
            return JSONResponse(status_code=403, content=error.model_dump())
        response = await call_next(request)
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
        return {"status": "ok"}

    app.include_router(accounts.router)
    app.include_router(scenes.router)
    return app
