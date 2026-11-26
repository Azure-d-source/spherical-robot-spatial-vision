from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import DeclarativeBase, Session


class Base(DeclarativeBase):
    pass


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.sessions() as db:
        yield db


Database = Annotated[Session, Depends(get_db)]
