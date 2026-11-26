from pathlib import Path

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles


class WorkbenchFiles(StaticFiles):
    def __init__(self, directory: Path):
        super().__init__(directory=directory, html=True, check_dir=False)
        self.index = directory / "index.html"

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and not await run_in_threadpool(self.index.is_file):
            raise HTTPException(404, "工作台尚未构建")
        await super().__call__(scope, receive, send)

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if Path(path).suffix.lower() == ".wasm" and response.status_code in {200, 206}:
            response.headers["content-type"] = "application/wasm"
        return response
