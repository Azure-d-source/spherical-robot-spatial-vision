from datetime import datetime, timedelta, timezone
from hashlib import sha256
from secrets import token_urlsafe
from typing import Annotated, Literal

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import APIKeyCookie
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, delete, select
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, Database
from .errors import ApiError, ErrorResponse, InvalidRequest

Role = Literal["member", "admin"]
COOKIE = "orbitforge_session"
SESSION_LIFETIME = timedelta(hours=12)
password_hasher = PasswordHasher()
unknown_password = password_hasher.hash(token_urlsafe(32))
session_cookie = APIKeyCookie(name=COOKIE, auto_error=False)
SessionToken = Annotated[str | None, Depends(session_cookie)]
UNAUTHENTICATED = {401: {"model": ErrorResponse, "description": "需要有效账号会话"}}
router = APIRouter(prefix="/api/auth", tags=["身份"])


class Team(Base):
    __tablename__ = "teams"

    team_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint("role IN ('member', 'admin')", name="ck_accounts_role"),
        UniqueConstraint("team_id", "account_id", name="uq_accounts_team_account"),
    )

    account_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.team_id"))
    email: Mapped[str] = mapped_column(String(254), unique=True)
    role: Mapped[Role] = mapped_column(String(12))
    password_hash: Mapped[str] = mapped_column(String(255))


class LoginSession(Base):
    __tablename__ = "login_sessions"

    session_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=254)]
    password: SecretStr = Field(min_length=1, max_length=256)


class AccountInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    account_id: str
    team_id: str
    email: str
    role: Role


def session_hash(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def current_account(db: Database, token: SessionToken) -> Account:
    if token and len(token) == 43:
        account = db.scalar(
            select(Account).join(LoginSession).where(
                LoginSession.session_hash == session_hash(token),
                LoginSession.expires_at > datetime.now(timezone.utc),
            )
        )
        if account is not None:
            return account
    raise ApiError(401, "LOGIN_REQUIRED", "请先登录。")


CurrentAccount = Annotated[Account, Depends(current_account)]


@router.post("/login", response_model=AccountInfo,
             responses={**UNAUTHENTICATED, 422: {"model": InvalidRequest}})
def login(payload: LoginInput, request: Request, response: Response, db: Database) -> Account:
    account = db.scalar(select(Account).where(Account.email == payload.email.lower()))
    try:
        password_hasher.verify(
            account.password_hash if account else unknown_password,
            payload.password.get_secret_value(),
        )
    except VerifyMismatchError:
        raise ApiError(401, "INVALID_CREDENTIALS", "账号或密码不正确。") from None
    if account is None:
        raise ApiError(401, "INVALID_CREDENTIALS", "账号或密码不正确。")

    now = datetime.now(timezone.utc)
    token = request.cookies.get(COOKIE)
    if token and len(token) == 43:
        db.execute(delete(LoginSession).where(LoginSession.session_hash == session_hash(token)))
    db.execute(delete(LoginSession).where(LoginSession.account_id == account.account_id, LoginSession.expires_at <= now))
    new_token = token_urlsafe(32)
    db.add(LoginSession(session_hash=session_hash(new_token), account_id=account.account_id,
                        expires_at=now + SESSION_LIFETIME))
    db.commit()
    response.set_cookie(COOKIE, new_token, max_age=int(SESSION_LIFETIME.total_seconds()), httponly=True,
                        secure=request.app.state.secure_cookies, samesite="strict")
    return account


@router.get("/me", response_model=AccountInfo, responses=UNAUTHENTICATED)
def me(account: CurrentAccount) -> Account:
    return account


@router.post("/logout", status_code=204)
def logout(request: Request, db: Database) -> Response:
    token = request.cookies.get(COOKIE)
    if token and len(token) == 43:
        db.execute(delete(LoginSession).where(LoginSession.session_hash == session_hash(token)))
        db.commit()
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, httponly=True, secure=request.app.state.secure_cookies, samesite="strict")
    return response
