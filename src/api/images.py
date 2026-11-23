"""Validation and content-addressed storage for uploaded camera frames."""

import hashlib
import io
import os
import tempfile
from pathlib import Path

from fastapi import HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from starlette.responses import JSONResponse

from . import store

MAX_BYTES = 12 * 1024 * 1024
MAX_REQUEST = MAX_BYTES + 64 * 1024  # Multipart headers and camera metadata.
MAX_PIXELS = 24_000_000
EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
SIZE_ERROR = "单张照片最大为 12 MiB"


class UploadLimit:
    """Cap multipart bodies as they arrive, including requests without Content-Length."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (scope["type"] != "http" or scope["method"] != "POST"
                or not scope["path"].rstrip("/").endswith("/frames")):
            return await self.app(scope, receive, send)
        length = dict(scope["headers"]).get(b"content-length")
        if length and length.isdigit() and int(length) > MAX_REQUEST:
            return await JSONResponse({"detail": SIZE_ERROR}, status_code=413)(scope, receive, send)

        received = 0

        async def bounded_receive():
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > MAX_REQUEST:
                raise HTTPException(413, SIZE_ERROR)
            return message

        await self.app(scope, bounded_receive, send)


def read_image(upload: UploadFile):
    data = upload.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, SIZE_ERROR)
    try:
        formats = ("JPEG", "PNG", "WEBP")
        with Image.open(io.BytesIO(data), formats=formats) as image:
            width, height = image.size
            if width * height > MAX_PIXELS:
                raise HTTPException(413, "照片分辨率须在 2400 万像素以内")
            if getattr(image, "is_animated", False):
                raise HTTPException(422, "请上传静态照片")
            media_type = Image.MIME[image.format]
            image.verify()
        with Image.open(io.BytesIO(data), formats=formats) as decoded:
            decoded.load()
    except Image.DecompressionBombError as exc:
        raise HTTPException(413, "照片分辨率须在 2400 万像素以内") from exc
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        raise HTTPException(422, "请上传可解码的 JPEG、PNG 或 WebP 照片") from exc
    return data, hashlib.sha256(data).hexdigest(), media_type, width, height


def photo_path(digest, media_type):
    return store.PHOTOS / (digest + EXTENSIONS[media_type])


def save_image(data, digest, media_type):
    destination = photo_path(digest, media_type)
    if destination.is_file():
        return
    # Publish the validated bytes before the database makes the frame visible.
    staged = tempfile.NamedTemporaryFile(dir=store.PHOTOS, suffix=".part", delete=False)
    try:
        with staged:
            staged.write(data)
            staged.flush()
            os.fsync(staged.fileno())
        os.replace(staged.name, destination)
    finally:
        Path(staged.name).unlink(missing_ok=True)
