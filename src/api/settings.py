import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WEB_DIST = ROOT / "src" / "web" / "dist"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    web_dist: Path = DEFAULT_WEB_DIST

    @classmethod
    def from_env(cls):
        return cls(data_dir=Path(os.environ.get("SPATIAL_DATA_DIR", ROOT / "data" / "runtime")))
