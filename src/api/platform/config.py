import os
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy.engine import make_url


@dataclass(frozen=True)
class PlatformSettings:
    database_url: str
    public_origin: str = "http://127.0.0.1:8001"

    def __post_init__(self):
        if make_url(self.database_url).drivername != "postgresql+psycopg":
            raise ValueError("SPATIAL_DATABASE_URL must use postgresql+psycopg")
        url = urlsplit(self.public_origin)
        if (not url.hostname or url.username or url.password
                or url.path or url.query or url.fragment
                or not (url.scheme == "https" or (
                    url.scheme == "http" and url.hostname in {"127.0.0.1", "localhost", "::1"}
                ))):
            raise ValueError("SPATIAL_PUBLIC_ORIGIN must be an HTTPS origin or loopback HTTP")

    @classmethod
    def from_env(cls):
        database_url = os.environ.get("SPATIAL_DATABASE_URL")
        if not database_url:
            raise ValueError("Set SPATIAL_DATABASE_URL before starting the PostgreSQL API")
        return cls(
            database_url=database_url,
            public_origin=os.environ.get("SPATIAL_PUBLIC_ORIGIN", "http://127.0.0.1:8001"),
        )
