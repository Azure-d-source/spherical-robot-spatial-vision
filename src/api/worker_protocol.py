"""Request and lease conventions shared by the local Worker endpoints."""

import hashlib
from datetime import timedelta

from pydantic import BaseModel, Field

from .models import JobKind, RegistrationCoverage

LEASE = timedelta(seconds=60)
MAX_ATTEMPTS = 3


class LeaseInput(BaseModel):
    lease_token: str


class FailureInput(LeaseInput):
    error_code: str = Field(pattern=r"^[A-Z_]+$", max_length=64)
    error_message: str | None = Field(default=None, max_length=500, min_length=1)
    coverage: RegistrationCoverage | None = None


class ClaimInput(BaseModel):
    kinds: list[JobKind] = Field(default_factory=lambda: ["splat"], min_length=1, max_length=3)


ERRORS = {
    "INSUFFICIENT_REGISTRATION": "没有可用的配准组件。请补拍清晰、有重叠和位移的机位。",
    "RESOLUTION_MISMATCH": "校正方向后照片画幅不一致。请统一拍摄方向与画幅。",
    "EXECUTOR_ERROR": "作业执行失败，请查看 Worker 日志。",
}


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
