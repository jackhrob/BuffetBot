"""Versioned, data-only boundaries for local research jobs and their durable state."""

from datetime import UTC
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BeforeValidator, Field, StrictInt, StrictStr, field_validator

from buffetbot.contracts import Identifier, Record, Text, Timestamp, VersionedRecord


def uuid_input(value):
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        return value
    raise ValueError("Use a UUID string")


JobUUID = Annotated[UUID, BeforeValidator(uuid_input)]
JobState = Literal["queued", "running", "succeeded", "failed", "interrupted", "cancelled"]


class ResearchProbe(Record):
    """Bounded diagnostic work, used until later stories register real research handlers."""

    message: Annotated[StrictStr, Field(min_length=1, max_length=4_000)]
    delay_ms: Annotated[StrictInt, Field(ge=0, le=30_000)] = 0


class JobRequest(VersionedRecord):
    request_id: JobUUID
    run_id: JobUUID
    kind: Literal["research_probe"]
    payload: ResearchProbe
    submitted_at: Timestamp


class ArtifactReference(Record):
    relative_path: Annotated[StrictStr, Field(pattern=r"^jobs/[0-9a-f-]{36}/[a-z0-9_.-]{1,128}$")]
    sha256: Annotated[StrictStr, Field(pattern=r"^[a-f0-9]{64}$")]
    size_bytes: Annotated[StrictInt, Field(gt=0)]


class JobRecord(VersionedRecord):
    request: JobRequest
    state: JobState
    progress: Annotated[StrictInt, Field(ge=0, le=100)]
    created_at: Timestamp
    updated_at: Timestamp
    worker_id: Identifier | None
    started_at: Timestamp | None
    finished_at: Timestamp | None
    error_code: Identifier | None
    detail: Text | None
    artifact: ArtifactReference | None
    cancellation_requested: bool = False

    @field_validator("updated_at")
    @classmethod
    def update_time(cls, value: AwareDatetime):
        return value.astimezone(UTC)
