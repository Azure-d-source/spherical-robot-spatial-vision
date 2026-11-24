from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
SceneSource = Literal["sample", "robot", "simulation"]
JobKind = Literal["depth", "fusion", "splat"]


class SceneInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Title
    source: SceneSource
    target: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] = ""


class Scene(SceneInput):
    scene_id: str
    created_at: datetime


class Frame(BaseModel):
    frame_id: str
    scene_id: str
    capture_id: str
    filename: str
    view_label: str
    captured_at: datetime
    created_at: datetime
    sha256: str
    image_url: str
    media_type: str
    size_bytes: int
    width: int
    height: int


class RevisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    frame_ids: list[Identifier] = Field(min_length=1, max_length=512)


class Revision(RevisionInput):
    revision_id: str
    scene_id: str
    version: int
    created_at: datetime


class JobInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision_id: Identifier
    kind: JobKind
    recipe_version: Identifier = "v1"


class RegistrationCoverage(BaseModel):
    registered_images: int
    total_images: int
    unregistered_frame_ids: list[str]


class JobArtifact(BaseModel):
    filename: str
    url: str


class Job(JobInput):
    model_config = ConfigDict(extra="ignore")
    job_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    created_at: datetime
    error_code: str | None = None
    error_message: str | None = None
    registration: RegistrationCoverage | None = None
    artifacts: list[JobArtifact] = Field(default_factory=list)


class SceneDetail(Scene):
    frames: list[Frame]
    revisions: list[Revision]
    jobs: list[Job]
